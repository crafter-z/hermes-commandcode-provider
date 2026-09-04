"""Command Code model catalog disk cache + offline fallback.

The Provider API ``/models`` endpoint is live-only and returns bare
``{id, name, context_length}`` records. This module persists the last good
catalog to ``<HERMES_HOME>/cache/commandcode-models.json`` so sessions stay
usable offline and per-model metadata (context window observed live) survives
restarts. ``enrich_models`` merges the checked-in ``catalog.py`` snapshot
(reasoning, vision input, output caps, selectable efforts) onto each record.

Design notes:

* The cache file is a single JSON document ``{"version": 1, "models": [...]}``
  written atomically (temp file + ``os.replace``) so a crash can never leave a
  half-written catalog.
* ``fetch_and_cache`` is the refresh primitive used by the quota plugin's
  ``/commandcode-refresh``: live first, cache on failure, empty when neither.
* ``enrich_models`` is a pure, idempotent transform: feeding it an already
  enriched record (fresh from ``load_cache``) yields the same result.
* ``catalog.py`` is imported lazily so this module can also be loaded as a
  bare file (the quota plugin's fallback loader), not only inside the provider
  package.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

CACHE_VERSION = 1
_CACHE_FILENAME = "commandcode-models.json"
# Env override documented in README; else <HERMES_HOME>/cache/.
_CACHE_ENV_VAR = "COMMANDCODE_MODELS_CACHE"
_HERMES_HOME_ENV_VAR = "HERMES_HOME"
# Windows default used when HERMES_HOME is unset (mirrors Hermes' default).
_WINDOWS_DEFAULT_HOME = Path.home() / "AppData" / "Local" / "hermes"

_USER_AGENT = "hermes-commandcode-provider/1.0 (+model-catalog-cache)"

# Runtime package name Hermes uses for this provider override (see the quota
# plugin's pricing loader); used to reuse the already-imported catalog.
_RUNTIME_PACKAGE = "_hermes_user_provider_commandcode"

_catalog_module: Any = None


def cache_path() -> Path:
    """Return the catalog cache file path.

    ``COMMANDCODE_MODELS_CACHE`` overrides outright; otherwise the file lives
    under ``<HERMES_HOME>/cache/`` (``HERMES_HOME`` unset falls back to
    ``~/AppData/Local/hermes``).
    """
    override = (os.environ.get(_CACHE_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    home = (os.environ.get(_HERMES_HOME_ENV_VAR) or "").strip()
    if not home:
        home = str(_WINDOWS_DEFAULT_HOME)
    return Path(home) / "cache" / _CACHE_FILENAME


def _catalog() -> Any:
    """Return the ``catalog`` snapshot module under any load mode.

    Resolution order: Hermes runtime package attribute, in-package relative
    import, then a bare-file import of the sibling ``catalog.py`` (quota
    plugin lazy fallback). Memoized — catalog.py is static data/functions.
    """
    global _catalog_module
    if _catalog_module is not None:
        return _catalog_module

    catalog = sys.modules.get(f"{_RUNTIME_PACKAGE}.catalog")
    if catalog is None:
        try:
            from . import catalog  # normal in-package import
        except ImportError:
            catalog = None
    if catalog is None:
        # Loaded as a bare file: sibling catalog.py sits right next to us.
        sibling = Path(__file__).resolve().parent / "catalog.py"
        if sibling.is_file():
            spec = importlib.util.spec_from_file_location(
                "_cc_catalog_lazy", str(sibling)
            )
            catalog = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(catalog)
    _catalog_module = catalog
    return catalog


def _write(cache_path: Path, models: list[dict]) -> None:
    """Atomically persist ``{"version": 1, "models": [...]}`` to disk."""
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"version": CACHE_VERSION, "models": models}, ensure_ascii=False, indent=2
    )
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_cache(cache_path: Path) -> list[dict] | None:
    """Read the cache; ``None`` when missing, unreadable, or wrong version."""
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    models = data.get("models")
    if not isinstance(models, list):
        return None
    return [m for m in models if isinstance(m, dict)]


def enrich_models(models: list[dict]) -> list[dict]:
    """Merge catalog metadata onto raw ``{id, name, context_length}`` records.

    Adds ``api`` (``claude-*`` → anthropic-messages, else
    openai-completions), ``reasoning``, ``contextWindow`` (from the live
    ``context_length``), ``maxTokens``, ``input`` modalities, and selectable
    ``efforts``. Input records without ``context_length`` (catalog-only
    synthesis) simply omit ``contextWindow``.
    """
    catalog = _catalog()
    enriched: list[dict] = []
    for record in models:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        model_id = record["id"]
        out = dict(record)
        out["api"] = (
            "anthropic-messages"
            if model_id.startswith("claude-")
            else "openai-completions"
        )
        out["reasoning"] = model_id in catalog.MODEL_REASONING
        if record.get("context_length") is not None:
            out["contextWindow"] = record["context_length"]
        out["maxTokens"] = catalog.max_output_tokens_for_model(model_id)
        out["input"] = catalog.MODEL_INPUT_MODALITIES.get(model_id, ("text",))
        out["efforts"] = catalog.MODEL_EFFORTS.get(model_id, ())
        enriched.append(out)
    return enriched


def _fetch_records(models_url: str, timeout: float) -> list[dict]:
    """GET ``/models`` and return the raw record list. Raises on failure."""
    req = urllib.request.Request(models_url)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", _USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    records = data.get("data", []) if isinstance(data, dict) else []
    return [m for m in records if isinstance(m, dict) and m.get("id")]


def fetch_and_cache(
    models_url: str, timeout: float, cache_path: Path
) -> tuple[list[dict], str]:
    """Live refresh with cache fallback.

    Returns ``(models, source)`` where ``source`` is:

    * ``"live"`` — fresh catalog fetched and persisted (enriched).
    * ``"cache"`` — live fetch failed; last good catalog loaded from disk.
    * ``"empty"`` — live fetch failed and no usable cache exists.

    An empty/odd live payload is treated as a fetch failure so a bad upstream
    response can never overwrite a good cache or report a bogus success.
    """
    try:
        records = _fetch_records(models_url, timeout)
    except Exception:
        records = []
    if records:
        enriched = enrich_models(records)
        try:
            _write(cache_path, enriched)
        except OSError:
            # A cache-write failure must never fail a live fetch.
            pass
        return enriched, "live"
    cached = load_cache(cache_path)
    if cached:
        return cached, "cache"
    return [], "empty"

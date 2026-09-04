"""Handlers for ``/commandcode-refresh`` and ``/commandcode-status``.

``/commandcode-refresh`` re-fetches the Command Code model catalog through
``cache.fetch_and_cache`` (live first, on-disk fallback) and reports which
source served the result. ``/commandcode-status`` prints redacted diagnostics:
last refresh outcome, on-disk cache state, endpoint, and cache path.

The cache module lives in the sibling ``model-providers/commandcode/`` package.
At runtime it is imported under Hermes as ``_hermes_user_provider_commandcode``;
this module reuses that import when present and otherwise falls back to a
bare-file import of ``cache.py`` — the same two-step resolution the plugin's
pricing loader uses. Diagnostics never leak credentials: URLs are trimmed to
``protocol://host/path`` and key/token/secret patterns are scrubbed.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_CC_DEFAULT_MODELS_URL = "https://api.commandcode.ai/provider/v1/models"
_DEFAULT_TIMEOUT_MS = 10_000
_RUNTIME_PACKAGE = "_hermes_user_provider_commandcode"

# ── Refresh bookkeeping (module-level: one flag + outcome stamps per session) ─
_refresh_in_progress = False
_last_refresh_source: str | None = None  # "live" | "cache" | "empty"
_last_success_at: str | None = None  # ISO-8601 UTC
_last_attempt_at: str | None = None  # ISO-8601 UTC
_last_warning: str | None = None


# ── Redaction helpers ─────────────────────────────────────────────────────────
def redact_url(url: str) -> str:
    """Trim a URL to ``protocol://host/path`` — drop query, fragment, userinfo.

    Also collapses any empty path so output stays ``https://host``.
    """
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    netloc = hostname
    if parts.port is not None:
        netloc = f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


_REDACT_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_REDACT_PREFIXED = re.compile(r"(?i)\b(?:user_|cc_)[A-Za-z0-9._-]+")
_REDACT_KEY_VALUE = re.compile(
    r"(?i)\b([A-Za-z0-9._-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token"
    r"|secret|password|token)[A-Za-z0-9._-]*)(\s*[:=]\s*)(\S+)"
)


def redact_text(text: str) -> str:
    """Scrub credentials from free text: Bearer values, ``user_*``/``cc_*``
    handles, and ``key``/``token``/``secret``/``password`` assignments."""
    if not text:
        return text
    text = _REDACT_BEARER.sub("Bearer [redacted]", text)
    text = _REDACT_PREFIXED.sub("[redacted]", text)
    return _REDACT_KEY_VALUE.sub(r"\1\2[redacted]", text)


# ── Cache-module resolution (mirrors the plugin's pricing loader) ────────────
_cache_module = None


def _cache():
    """Return the sibling provider's ``cache`` module, or None if missing."""
    global _cache_module
    if _cache_module is not None:
        return _cache_module
    module = sys.modules.get(f"{_RUNTIME_PACKAGE}.cache")
    if module is None:
        here = Path(__file__).resolve().parent.parent
        candidate = here / "plugins" / "model-providers" / "commandcode" / "cache.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("_cc_cache_lazy", str(candidate))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
    _cache_module = module
    return module


# ── Endpoint resolution ───────────────────────────────────────────────────────
def _models_url() -> str:
    """Resolve the catalog endpoint: explicit override, base override, default.

    ``COMMANDCODE_MODELS_URL`` (documented for tests/mocks) wins; then
    ``COMMANDCODE_BASE_URL`` + ``/models``; then the default provider URL.
    """
    override = (os.environ.get("COMMANDCODE_MODELS_URL") or "").strip()
    if override:
        return override
    base = (os.environ.get("COMMANDCODE_BASE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}/models"
    return _CC_DEFAULT_MODELS_URL


def _timeout_seconds() -> float:
    """Refresh timeout: ``COMMANDCODE_MODELS_TIMEOUT_MS`` or 10000 ms default."""
    raw = (os.environ.get("COMMANDCODE_MODELS_TIMEOUT_MS") or "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_MS / 1000.0
    try:
        return max(1, int(raw)) / 1000.0
    except ValueError:
        return _DEFAULT_TIMEOUT_MS / 1000.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Command handlers ──────────────────────────────────────────────────────────
def _handle_refresh(raw_args: str) -> str:
    """Refresh the model catalog: live first, cached fallback, honest report."""
    global _refresh_in_progress, _last_refresh_source
    global _last_success_at, _last_attempt_at, _last_warning

    if _refresh_in_progress:
        return "Command Code model catalog refresh already in progress."
    cache = _cache()
    if cache is None:
        return (
            "Command Code model catalog refresh unavailable: provider cache "
            "module not found."
        )

    _refresh_in_progress = True
    try:
        models, source = cache.fetch_and_cache(
            _models_url(), _timeout_seconds(), cache.cache_path()
        )
        _last_attempt_at = _now_iso()
        _last_refresh_source = source
        count = len(models)
        if source == "live":
            _last_success_at = _last_attempt_at
            _last_warning = None
            return f"Command Code model catalog refreshed ({count} models from live)."
        if source == "cache":
            _last_warning = "live fetch failed; serving the cached catalog"
            return (
                f"Command Code model catalog unchanged ({count} models remain "
                f"available). {_last_warning}."
            )
        # source == "empty"
        _last_warning = "live fetch failed and no cached catalog exists"
        return (
            f"Command Code model catalog unavailable (0 models cached). "
            f"{_last_warning}."
        )
    except Exception as exc:
        _last_attempt_at = _now_iso()
        _last_warning = f"refresh failed: {redact_text(str(exc))}"
        return (
            "Command Code model catalog refresh failed: "
            f"{redact_text(str(exc))}"
        )
    finally:
        _refresh_in_progress = False


def _handle_status(raw_args: str) -> str:
    """Redacted diagnostics: source, counts, timestamps, cache path, endpoint."""
    cache = _cache()
    if cache is None:
        return (
            "Command Code provider diagnostics unavailable: provider cache "
            "module not found."
        )
    try:
        path = cache.cache_path()
        cached = cache.load_cache(path)
    except Exception as exc:
        return (
            "Command Code provider diagnostics failed: "
            f"{redact_text(str(exc))}"
        )

    count = len(cached) if cached else 0
    if _last_refresh_source is not None:
        source = _last_refresh_source
    elif cached:
        source = "cache"
    else:
        source = "empty"

    lines = [
        "Command Code provider diagnostics",
        f"  source: {source}",
        f"  model count: {count}",
        f"  last success: {_last_success_at or 'never'}",
        f"  last attempt: {_last_attempt_at or 'never'}",
        f"  cache path: {path}",
        f"  endpoint: {redact_url(_models_url())}",
        f"  warning: {_last_warning or 'none'}",
    ]
    return "\n".join(lines)


__all__ = [
    "_handle_refresh",
    "_handle_status",
    "redact_text",
    "redact_url",
]

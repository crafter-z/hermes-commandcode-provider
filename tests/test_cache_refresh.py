"""Cache + /commandcode-refresh + /commandcode-status contract test.

Mirrors the real hermes loader the same way ``test_quota_plugin.py`` does:
copies plugin sources into a temp ``hermes_plugins`` tree and imports them as
packages, then exercises ``cache.fetch_and_cache``/``enrich_models`` against a
local fake ``/models`` server and drives the real ``status`` handlers.

Run with ``python tests/test_cache_refresh.py`` (no pytest required).
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

SRC_PROVIDER = Path(__file__).resolve().parent.parent / "plugins" / "model-providers" / "commandcode"
SRC_QUOTA = Path(__file__).resolve().parent.parent / "plugins" / "commandcode-quota"

# ── temp hermes_plugins tree: provider cache/catalog + quota status.py ───────
tmp = Path(tempfile.mkdtemp(prefix="cccache_"))
pkg_root = tmp / "hermes_plugins"
(pkg_root / "provider").mkdir(parents=True)
(pkg_root / "quota").mkdir()
for name in ("cache.py", "catalog.py", "catalog_overrides.py"):
    shutil.copy(SRC_PROVIDER / name, pkg_root / "provider" / name)
(pkg_root / "provider" / "__init__.py").write_text("", encoding="utf-8")
shutil.copy(SRC_QUOTA / "status.py", pkg_root / "quota" / "status.py")
(pkg_root / "quota" / "__init__.py").write_text("", encoding="utf-8")
sys.path.insert(0, str(tmp))

import hermes_plugins.provider.cache as cache  # noqa: E402
import hermes_plugins.provider.catalog as catalog  # noqa: E402
import hermes_plugins.quota.status as status  # noqa: E402

# Hermes registers the provider override under this runtime package name; the
# status handlers resolve the cache module through sys.modules first.
sys.modules["_hermes_user_provider_commandcode.cache"] = cache

_SAVED_ENV = dict(os.environ)


def set_env(**values: str | None) -> None:
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def reset_env() -> None:
    os.environ.clear()
    os.environ.update(_SAVED_ENV)


# ── fake /models server ──────────────────────────────────────────────────────
LIVE_MODELS = [
    {"id": "claude-sonnet-5", "name": "Claude Sonnet 5", "context_length": 200_000},
    {"id": "claude-opus-5", "name": "Claude Opus 5", "context_length": 200_000},
    {"id": "deepseek/deepseek-v4-flash", "name": "DeepSeek V4 Flash", "context_length": 131_072},
    {"id": "deepseek/deepseek-v4.1-flash", "name": "DeepSeek V4.1 Flash", "context_length": 1_000_000},
    {"id": "google/gemini-3.5-flash", "name": "Gemini 3.5 Flash", "context_length": 1_000_000},
]


class Handler(http.server.BaseHTTPRequestHandler):
    fail = False

    def do_GET(self):  # noqa: N802
        if Handler.fail:
            self.send_error(500)
            return
        body = json.dumps({"data": LIVE_MODELS}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
MODELS_URL = f"http://127.0.0.1:{server.server_port}/models"

passed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed
    assert cond, f"{label}: {detail}"
    passed += 1
    print(f"  ok  {label}" + (f"  ({detail})" if detail else ""))


# ── 1. live success → cache written, source "live" ───────────────────────────
work = Path(tempfile.mkdtemp(prefix="case1_"))
cache_file = work / "cache" / "commandcode-models.json"
Handler.fail = False
models, source = cache.fetch_and_cache(MODELS_URL, 5.0, cache_file)
check("live fetch returns 'live'", source == "live", source)
check("live fetch returns every model", len(models) == len(LIVE_MODELS), len(models))
raw = json.loads(cache_file.read_text(encoding="utf-8"))
check("cache file has version 1", raw.get("version") == 1, raw.get("version"))
check("cache file stores models", len(raw.get("models", [])) == len(LIVE_MODELS))
first = raw["models"][0]
check(
    "cached record is enriched",
    all(k in first for k in ("api", "reasoning", "contextWindow", "maxTokens", "input", "efforts")),
    sorted(first),
)
v41 = next((m for m in raw["models"] if m["id"] == "deepseek/deepseek-v4.1-flash"), {})
check(
    "catalog_overrides reaches enriched records",
    tuple(v41.get("efforts") or ()) == ("low", "medium", "high", "xhigh", "max"),
    v41.get("efforts"),
)
check(
    "image modality survives enrichment + JSON round-trip",
    "image" in tuple(v41.get("input") or ()),
    v41.get("input"),
)

# ── 4. enrich_models api/reasoning mapping (raw records, not from disk) ──────
enriched = cache.enrich_models(LIVE_MODELS)
by_id = {m["id"]: m for m in enriched}
for record in LIVE_MODELS:
    mid = record["id"]
    out = by_id[mid]
    expected_api = "anthropic-messages" if mid.startswith("claude-") else "openai-completions"
    check(
        f"api for {mid}",
        out["api"] == expected_api and out["reasoning"] == (mid in catalog.MODEL_REASONING),
        f"{out['api']} reasoning={out['reasoning']}",
    )
    check(
        f"contextWindow for {mid}",
        out["contextWindow"] == record["context_length"],
        out["contextWindow"],
    )
    check(
        f"maxTokens for {mid}",
        out["maxTokens"] == catalog.max_output_tokens_for_model(mid),
        out["maxTokens"],
    )
    check(
        f"input/efforts for {mid}",
        out["input"] == catalog.MODEL_INPUT_MODALITIES.get(mid, ("text",))
        and out["efforts"] == catalog.MODEL_EFFORTS.get(mid, ()),
        f"input={out['input']} efforts={out['efforts']}",
    )
check("enrich idempotent on cached records", cache.enrich_models(enriched) == enriched)

# ── 2. live failure + existing cache → "cache" ────────────────────────────────
Handler.fail = True
models, source = cache.fetch_and_cache(MODELS_URL, 5.0, cache_file)
check("failure falls back to cache", source == "cache", source)
check("fallback returns cached models", len(models) == len(LIVE_MODELS), len(models))

# ── 3. live failure + no cache → "empty" ──────────────────────────────────────
empty_file = work / "cache" / "never-written.json"
models, source = cache.fetch_and_cache(MODELS_URL, 5.0, empty_file)
check("no cache + failure is 'empty'", source == "empty" and models == [], f"{source} {models}")

# ── cache_path(): env precedence ──────────────────────────────────────────────
try:
    set_env(HERMES_HOME=str(work / "home"), COMMANDCODE_MODELS_CACHE=None)
    check(
        "cache_path honors HERMES_HOME",
        cache.cache_path() == work / "home" / "cache" / "commandcode-models.json",
        str(cache.cache_path()),
    )
    override = work / "elsewhere" / "models.json"
    set_env(COMMANDCODE_MODELS_CACHE=str(override))
    check("cache_path honors COMMANDCODE_MODELS_CACHE", cache.cache_path() == override, str(cache.cache_path()))
    set_env(HERMES_HOME=None, COMMANDCODE_MODELS_CACHE=None)
    check(
        "cache_path defaults to ~/AppData/Local/hermes",
        cache.cache_path() == Path.home() / "AppData" / "Local" / "hermes" / "cache" / "commandcode-models.json",
        str(cache.cache_path()),
    )
finally:
    reset_env()

# ── redaction helpers ─────────────────────────────────────────────────────────
check(
    "redact_url trims userinfo/query/fragment",
    status.redact_url("https://user:pass@api.commandcode.ai/provider/v1/models?api-key=zzz#frag")
    == "https://api.commandcode.ai/provider/v1/models",
    status.redact_url("https://user:pass@api.commandcode.ai/provider/v1/models?api-key=zzz#frag"),
)
check(
    "redact_url keeps explicit port",
    status.redact_url("https://host:8443/a/b") == "https://host:8443/a/b",
)
secret_text = "Bearer sk-live-abc123 user_12345 cc_proj_9 secret=hunter2 api-key=zzz ?token=abc"
redacted = status.redact_text(secret_text)
check("redact_text scrubs every secret", "[redacted]" in redacted and "hunter2" not in redacted and "sk-live" not in redacted, redacted)

# ── end-to-end handlers: /commandcode-refresh + /commandcode-status ──────────
try:
    run_dir = Path(tempfile.mkdtemp(prefix="e2e_"))
    set_env(
        HERMES_HOME=str(run_dir / "home"),
        COMMANDCODE_MODELS_URL=MODELS_URL,
        COMMANDCODE_MODELS_CACHE=None,
        COMMANDCODE_MODELS_TIMEOUT_MS=None,
    )
    Handler.fail = False
    out = status._handle_refresh("")
    check("refresh live message", out == f"Command Code model catalog refreshed ({len(LIVE_MODELS)} models from live).", out)

    status._refresh_in_progress = True
    out = status._handle_refresh("")
    check("overlapping refresh coalesced", out == "Command Code model catalog refresh already in progress.", out)
    status._refresh_in_progress = False

    out = status._handle_status("")
    lines = dict(line.strip().split(": ", 1) for line in out.splitlines()[1:])
    check(
        "status shows live source + count + stamps",
        lines.get("source") == "live"
        and lines.get("model count") == str(len(LIVE_MODELS))
        and lines.get("last success") != "never"
        and lines.get("last attempt") != "never",
        out,
    )
    check(
        "status cache path under HERMES_HOME",
        lines.get("cache path") == str(run_dir / "home" / "cache" / "commandcode-models.json"),
        lines.get("cache path"),
    )
    check(
        "status endpoint redacted",
        lines.get("endpoint") == f"http://127.0.0.1:{server.server_port}/models",
        lines.get("endpoint"),
    )

    Handler.fail = True
    out = status._handle_refresh("")
    check(
        "refresh cache-fallback message",
        out == (
            f"Command Code model catalog unchanged ({len(LIVE_MODELS)} models remain "
            "available). live fetch failed; serving the cached catalog."
        ),
        out,
    )
    out = status._handle_status("")
    lines = dict(line.strip().split(": ", 1) for line in out.splitlines()[1:])
    check(
        "status reflects cache fallback + warning",
        lines.get("source") == "cache" and "serving the cached catalog" in lines.get("warning", ""),
        out,
    )

    # status with no refresh run and no cache file → source "empty", stamps never
    clean = importlib.util.spec_from_file_location(
        "status_clean", pkg_root / "quota" / "status.py"
    )
    clean_mod = importlib.util.module_from_spec(clean)
    sys.modules["status_clean"] = clean_mod
    clean.loader.exec_module(clean_mod)
    set_env(HERMES_HOME=str(run_dir / "empty-home"))
    out = clean_mod._handle_status("")
    lines = dict(line.strip().split(": ", 1) for line in out.splitlines()[1:])
    check(
        "status empty-source defaults",
        lines.get("source") == "empty"
        and lines.get("model count") == "0"
        and lines.get("last success") == "never"
        and lines.get("last attempt") == "never",
        out,
    )
finally:
    reset_env()

server.shutdown()
shutil.rmtree(tmp, ignore_errors=True)

print(f"\nALL CACHE/REFRESH/STATUS TESTS PASSED ({passed} checks)")

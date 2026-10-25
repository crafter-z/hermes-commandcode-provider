"""Metadata-sync parser contract test (offline, no npm).

Guards the exit-code contract the workflow keys on:

* 0 — snapshot current,
* 1 — drift → draft PR,
* 2 — the check could not run → red job.

Two regressions this suite exists for, both of which turned a routine upstream
release into a red scheduled job that never opened the drift PR:

1. ``models.md`` gained ``off`` as a selectable effort for the DeepSeek V4
   family, and the parser validated effort values against a frozen allowlist.
2. ``command-code@1.82.3`` re-serialized the catalog in ``dist/cli.mjs`` and
   deleted the ``new Set([...text-only ids...])`` declaration. The parser keyed
   on both, so it exited 2 with "Extra data: line 1 column 23" instead of
   reporting drift.

The rules now are:

* a well-formed but previously unseen level is *data drift* (exit 1),
* a re-serialized but still readable bundle is parsed, not failed,
* only an unreadable table is "could not run" (exit 2).

Run with ``python tests/test_sync_catalog_parser.py`` (no pytest required).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_sync():
    spec = importlib.util.spec_from_file_location(
        "_cc_sync_catalog", str(REPO_ROOT / "scripts" / "sync_catalog.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = _load_sync()

passed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed
    assert cond, f"{label}: {detail}"
    passed += 1
    print(f"  ok  {label}" + (f"  ({detail})" if detail else ""))


def raises(fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except Exception:
        return True
    return False


# ── a models.md shaped like upstream's ───────────────────────────────────────

HEADER = "| Model | Provider | Context | Reasoning efforts |\n| --- | --- | --- | --- |\n"


def models_md(*rows: str) -> str:
    return HEADER + "\n".join(rows) + "\n"


# The exact row that broke the CI run: `off` first, then levels.
ROW_OFF = "| `deepseek/deepseek-v4-pro` | DeepSeek | 1M | off, high, max |"
ROW_LEVELS = "| `acme/vision-1` | Acme | 1M | low, medium, high, xhigh, max |"
ROW_NONE = "| `moonshotai/Kimi-K2.7-Code` | Moonshot | 256K | — |"

# ── 1. `off` is a known, accepted value (the CI regression) ──────────────────

parsed = sync.parse_models_reference(models_md(ROW_OFF, ROW_LEVELS, ROW_NONE))
check(
    "the CI-braking row parses instead of raising",
    parsed["reasoning_efforts"]["deepseek/deepseek-v4-pro"] == ["off", "high", "max"],
    parsed["reasoning_efforts"]["deepseek/deepseek-v4-pro"],
)
check(
    "`off` is a known value, not an unrecognised one",
    parsed["unrecognized_efforts"] == [],
    parsed["unrecognized_efforts"],
)
check("em-dash row declares no selectable efforts", "moonshotai/Kimi-K2.7-Code" not in parsed["reasoning_efforts"])
check(
    "known vocabulary covers every level upstream ships today",
    {"off", "minimal", "low", "medium", "high", "xhigh", "max"} <= sync.KNOWN_EFFORTS,
    sorted(sync.KNOWN_EFFORTS),
)

# ── 2. a brand-new level is drift (exit 1), never "could not run" (exit 2) ───

new_level = sync.parse_models_reference(models_md(ROW_OFF, "| `vendor/new-model` | Vendor | 1M | low, ultra |"))
check(
    "an unseen but well-formed level is accepted",
    new_level["reasoning_efforts"]["vendor/new-model"] == ["low", "ultra"],
    new_level["reasoning_efforts"].get("vendor/new-model"),
)
check(
    "the unseen level is called out for review",
    new_level["unrecognized_efforts"] == ["ultra"],
    new_level["unrecognized_efforts"],
)
current = sync.ModelMetadata(
    image_model_ids=[], reasoning_model_ids=[], reasoning_efforts={}, max_output_tokens={}
)
upstream = sync.ModelMetadata(
    image_model_ids=[],
    reasoning_model_ids=[],
    reasoning_efforts=new_level["reasoning_efforts"],
    max_output_tokens={},
    unrecognized_efforts=new_level["unrecognized_efforts"],
)
drift = sync.ModelMetadataDiff(current, upstream, "1.0.0", "1.0.0")
check("an unseen level reports as drift", drift.has_diff())
check(
    "the report shows the unseen level",
    "ultra" in sync.metadata_report("1.0.0", current, upstream, drift),
)

# ── 3. genuinely unreadable input is still a hard error ─────────────────────

check("no model rows → error", raises(sync.parse_models_reference, "# empty\n"))
check(
    "a malformed effort token → error",
    raises(sync.parse_models_reference, models_md("| `vendor/bad` | V | 1M | HIGH! |")),
)
check(
    "an empty effort column → error",
    raises(sync.parse_models_reference, models_md("| `vendor/bad` | V | 1M |  |")),
)

# The reference is split into one table per vendor, so a row can repeat. A repeat
# that agrees is the same metadata twice; one that disagrees is ambiguous.
repeated = sync.parse_models_reference(models_md(ROW_OFF, ROW_LEVELS, ROW_OFF))
check(
    "an identical repeated row is accepted once",
    repeated["reasoning_efforts"]["deepseek/deepseek-v4-pro"] == ["off", "high", "max"]
    and repeated["model_ids"].count("deepseek/deepseek-v4-pro") == 1,
    repeated["model_ids"],
)
check(
    "a conflicting repeated row → error",
    raises(
        sync.parse_models_reference,
        models_md(ROW_OFF, "| `deepseek/deepseek-v4-pro` | DeepSeek | 1M | low, high |"),
    ),
)

# ── 4. the bundle parser survives upstream re-serialization ─────────────────
#
# This is the command-code@1.82.3 shape: `id:` is no longer the first field of
# the object literal, and the `new Set([...text-only ids...])` declaration is
# gone. The old parser keyed on both, grabbed the unrelated
# `new Set(["anthropic","openai"])`, and died with a JSON error.

BUNDLE = (
    'const t=new Set(["anthropic","openai"]),'
    '__name(isKnownTextOnlyModel,"isKnownTextOnlyModel");'
    'const M={A:{display:{label:"DeepSeek V4 Pro"},id:"deepseek/deepseek-v4-pro",'
    'inputModalities:["text"],reasoning:!0,reasoningEfforts:["off","high","max"],'
    'maxOutputTokens:65536},'
    'B:{display:{label:"Acme Vision"},id:"acme/vision-1",inputModalities:["text","image"],'
    'reasoning:!0,reasoningEfforts:["low","medium","high","xhigh","max"]},'
    'C:{display:{label:"Kimi"},id:"moonshotai/Kimi-K2.7-Code",inputModalities:["text"]}};'
)

caps = sync.parse_bundle_model_capabilities(
    BUNDLE, ["deepseek/deepseek-v4-pro", "acme/vision-1", "moonshotai/Kimi-K2.7-Code"]
)
check(
    "capabilities are read regardless of field order",
    caps["reasoning_model_ids"] == ["acme/vision-1", "deepseek/deepseek-v4-pro"]
    and caps["max_output_tokens"] == {"deepseek/deepseek-v4-pro": 65536},
    caps,
)
check(
    "image support comes from inputModalities, not a deleted id Set",
    caps["image_model_ids"] == ["acme/vision-1"],
    caps["image_model_ids"],
)
check(
    "a missing model object → error",
    raises(sync.parse_bundle_model_capabilities, BUNDLE, ["nope/nope"]),
)
check(
    "conflicting duplicate listings → error",
    raises(
        sync.parse_bundle_model_capabilities,
        'const M={A:{id:"acme/v1",inputModalities:["text"]},'
        'B:{id:"acme/v1",inputModalities:["text","image"]}};',
        ["acme/v1"],
    ),
)
check(
    "a bundle carrying no text-only Set still parses",
    sync.parse_bundle_model_capabilities(
        'const M={A:{id:"acme/v1",inputModalities:["text"]}};', ["acme/v1"]
    )
    == {"image_model_ids": [], "reasoning_model_ids": [], "max_output_tokens": {}},
)
check(
    "a model with no inputModalities → error",
    raises(sync.parse_bundle_model_capabilities, 'const M={A:{id:"acme/v1"}};', ["acme/v1"]),
)

# ── 5. derived metadata → renderable, importable catalog ────────────────────

derived = sync.command_code_model_metadata_from_contents(
    models_md(ROW_OFF, ROW_LEVELS, ROW_NONE), BUNDLE
)
check(
    "derived metadata keeps `off` in the mirrored table",
    derived.reasoning_efforts["deepseek/deepseek-v4-pro"] == ["off", "high", "max"],
    derived.reasoning_efforts.get("deepseek/deepseek-v4-pro"),
)
check(
    "image ids come from the bundle's inputModalities",
    derived.image_model_ids == ["acme/vision-1"],
    derived.image_model_ids,
)
check(
    "reasoning ids come from the bundle's model objects",
    derived.reasoning_model_ids == ["acme/vision-1", "deepseek/deepseek-v4-pro"],
    derived.reasoning_model_ids,
)
rendered = sync.render_catalog("1.2.3", derived)
namespace: dict = {}
exec(compile(rendered, "catalog.py", "exec"), namespace)  # noqa: S102 - generated source
check("rendered catalog reports the package version", namespace["COMMAND_CODE_CLI_VERSION"] == "1.2.3")
check(
    "rendered catalog round-trips the declared efforts",
    namespace["efforts_for_model"]("deepseek/deepseek-v4-pro") == ("off", "high", "max"),
    namespace["efforts_for_model"]("deepseek/deepseek-v4-pro"),
)
check(
    "rendered catalog keeps the em-dash model off the effort table",
    namespace["efforts_for_model"]("moonshotai/Kimi-K2.7-Code") == (),
)

# ── 6. README version rewrite ───────────────────────────────────────────────

check(
    "the README snapshot version is rewritten",
    sync.update_readme_catalog_version("snapshot is command-code@1.65.2 today", "1.81.0")
    == "snapshot is command-code@1.81.0 today",
)
check(
    "a README without a version → error",
    raises(sync.update_readme_catalog_version, "no version here", "1.81.0"),
)

# ── 7. exit codes are the documented ones ───────────────────────────────────

check(
    "exit codes match the workflow contract",
    (sync.EXIT_OK, sync.EXIT_DRIFT, sync.EXIT_ERROR) == (0, 1, 2),
    (sync.EXIT_OK, sync.EXIT_DRIFT, sync.EXIT_ERROR),
)

print(f"\nALL SYNC CATALOG PARSER TESTS PASSED ({passed} checks)")

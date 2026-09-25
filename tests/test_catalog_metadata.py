"""Catalog snapshot + overrides contract test.

Guards the two data sources behind the provider profile's per-model metadata:

* ``catalog.py`` — the generated upstream mirror. Catches a stale snapshot (a
  model the CLI already ships but this repo does not declare) and a regression in
  the entries the profile depends on.
* ``catalog_overrides.py`` — this project's own declarations. Catches a dropped
  override and an override that leaks onto unrelated models.

Run with ``python tests/test_catalog_metadata.py`` (no pytest required).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_DIR = (
    Path(__file__).resolve().parent.parent / "plugins" / "model-providers" / "commandcode"
)


def _load(name: str):
    """Import a plugin module by path (same bare-file mode the quota plugin uses)."""
    spec = importlib.util.spec_from_file_location(f"_cc_test_{name}", str(PLUGIN_DIR / f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"_cc_test_{name}"] = module
    spec.loader.exec_module(module)
    return module


catalog = _load("catalog")
overrides = _load("catalog_overrides")
overrides.apply_overrides(catalog)

passed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed
    assert cond, f"{label}: {detail}"
    passed += 1
    print(f"  ok  {label}" + (f"  ({detail})" if detail else ""))


MODEL = "deepseek/deepseek-v4.1-flash"

check("v4.1-flash is image-capable", catalog.supports_image_input(MODEL))
check("v4.1-flash is a reasoning model", catalog.is_reasoning_model(MODEL))
check(
    "override restores the full accepted effort set",
    catalog.efforts_for_model(MODEL) == ("low", "medium", "high", "xhigh", "max"),
    catalog.efforts_for_model(MODEL),
)
check(
    "snapshot ships the models added upstream after 1.47.0",
    catalog.supports_image_input("gpt-6-astra") and catalog.is_reasoning_model("gpt-6-astra"),
)
check(
    "override does not leak onto other models",
    catalog.efforts_for_model("deepseek/deepseek-v4-flash") == ("high", "max"),
    catalog.efforts_for_model("deepseek/deepseek-v4-flash"),
)
overrides.apply_overrides(catalog)
check(
    "apply_overrides is idempotent",
    catalog.efforts_for_model(MODEL) == ("low", "medium", "high", "xhigh", "max"),
)
check(
    "generated snapshot version is reported",
    bool(catalog.COMMAND_CODE_CLI_VERSION),
    catalog.COMMAND_CODE_CLI_VERSION,
)

print(f"\nALL CATALOG METADATA TESTS PASSED ({passed} checks)")

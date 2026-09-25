"""Pricing table contract test (Hermes ``agent.usage_pricing`` stubbed).

Hermes looks a price up with ``_lookup_official_docs_pricing(route)`` →
``_OFFICIAL_DOCS_PRICING[(route.provider, route.model.lower())]``, where
``resolve_billing_route`` has already reduced the model to its bare last path
segment. This test stubs ``PricingEntry`` + ``_OFFICIAL_DOCS_PRICING`` with the
same shape and asserts what the plugin's ``install_pricing()`` puts there:

* every live model family has a base rate, tiered models also a threshold,
* a tier carries ALL FOUR ``*_above`` rates (a dropped cache-write rate silently
  under-bills long requests),
* keys are bare + lowercased and split per wire (Claude → commandcode-anthropic).

Run with ``python tests/test_pricing.py`` (no pytest required).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import types
from decimal import Decimal
from pathlib import Path

PLUGIN_DIR = (
    Path(__file__).resolve().parent.parent / "plugins" / "model-providers" / "commandcode"
)

# ── stub the Hermes pricing surface ─────────────────────────────────────────


@dataclasses.dataclass
class PricingEntry:
    input_cost_per_million: Decimal | None = None
    output_cost_per_million: Decimal | None = None
    cache_read_cost_per_million: Decimal | None = None
    cache_write_cost_per_million: Decimal | None = None
    request_cost: Decimal | None = None
    source: str = ""
    source_url: str = ""
    pricing_version: str = ""
    fetched_at: str | None = None
    tier_threshold_tokens: int | None = None
    input_cost_per_million_above: Decimal | None = None
    output_cost_per_million_above: Decimal | None = None
    cache_read_cost_per_million_above: Decimal | None = None
    cache_write_cost_per_million_above: Decimal | None = None


agent_module = types.ModuleType("agent")
usage_pricing = types.ModuleType("agent.usage_pricing")
usage_pricing.PricingEntry = PricingEntry
usage_pricing._OFFICIAL_DOCS_PRICING = {}
agent_module.usage_pricing = usage_pricing
sys.modules["agent"] = agent_module
sys.modules["agent.usage_pricing"] = usage_pricing

spec = importlib.util.spec_from_file_location("cc_pricing_test", PLUGIN_DIR / "pricing.py")
pricing = importlib.util.module_from_spec(spec)
sys.modules["cc_pricing_test"] = pricing
spec.loader.exec_module(pricing)

TABLE = usage_pricing._OFFICIAL_DOCS_PRICING

passed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed
    assert cond, f"{label}: {detail}"
    passed += 1
    print(f"  ok  {label}" + (f"  ({detail})" if detail else ""))


# ── 1. install ran at import and injected every key ─────────────────────────
check("import-time install succeeded", pricing._installed is True)
check(
    "every flat rate is injected",
    all(k in TABLE for k in pricing.FLAT_PRICING),
    sorted(set(pricing.FLAT_PRICING) - set(TABLE))[:5],
)
check(
    "every tiered model is injected",
    all(k in TABLE for k in pricing.SINGLE_TIERS),
    sorted(set(pricing.SINGLE_TIERS) - set(TABLE))[:5],
)
before = len(TABLE)
check("re-install is idempotent", pricing.install_pricing() and len(TABLE) == before, len(TABLE))

# ── 2. key contract: bare + lowercased, split per wire ──────────────────────
check(
    "keys are bare model ids",
    all("/" not in model for _, model in TABLE),
    [k for k in TABLE if "/" in k[1]][:3],
)
check(
    "keys are lowercased",
    all(model == model.lower() for _, model in TABLE),
    [k for k in TABLE if k[1] != k[1].lower()][:3],
)
check(
    "only the plugin's own providers are keyed",
    {provider for provider, _ in TABLE} == {"commandcode", "commandcode-anthropic"},
    {provider for provider, _ in TABLE},
)
claude_providers = {provider for provider, model in TABLE if model.startswith("claude-")}
check(
    "claude ids are keyed under the anthropic profile only (their only wire)",
    claude_providers == {"commandcode-anthropic"},
    claude_providers,
)
check(
    "no claude id leaks onto the openai profile",
    not any(provider == "commandcode" and model.startswith("claude-") for provider, model in TABLE),
)

# ── 3. tiers carry all four *_above rates ───────────────────────────────────
for key, tier in pricing.SINGLE_TIERS.items():
    entry = TABLE[key]
    threshold, input_a, output_a, cache_read_a, cache_write_a = tier
    check(
        f"tier {key[1]} keeps base + threshold + every *_above rate",
        entry.tier_threshold_tokens == threshold
        and entry.input_cost_per_million_above == Decimal(str(input_a))
        and entry.output_cost_per_million_above == Decimal(str(output_a))
        and entry.cache_read_cost_per_million_above == Decimal(str(cache_read_a))
        and entry.cache_write_cost_per_million_above == Decimal(str(cache_write_a)),
        f"threshold={entry.tier_threshold_tokens} cache_write_above={entry.cache_write_cost_per_million_above}",
    )

# ── 4. rates that were missing or stale before the re-sync ──────────────────
spot = {
    ("commandcode", "deepseek-v4.1-flash"): ("0.15", "0.6", "0.003", "0"),
    ("commandcode", "deepseek-v4-flash"): ("0.15", "0.6", "0.003", "0"),
    ("commandcode-anthropic", "claude-opus-5-5"): ("4", "20", "0.2", "5"),
    ("commandcode", "grok-4.7"): ("1.2", "3.6", "0.3", "0"),
}
for key, expected in spot.items():
    entry = TABLE.get(key)
    check(f"{key[1]} is priced", entry is not None)
    if entry is None:
        continue
    got = (
        str(entry.input_cost_per_million),
        str(entry.output_cost_per_million),
        str(entry.cache_read_cost_per_million),
        str(entry.cache_write_cost_per_million),
    )
    check(f"{key[1]} rates match the reference table", got == expected, got)

# Free models must stay free rather than vanish from the table.
free = TABLE.get(("commandcode", "laguna-s-2.1-free"))
check(
    "free models are priced at zero",
    free is not None and free.input_cost_per_million == Decimal("0"),
)

# ── 5. divergence notes must not rot ────────────────────────────────────────
check(
    "every divergence note names a real key",
    all(model in {m for _, m in TABLE} for model in pricing.MODEL_COST_DIVERGENCE),
    [m for m in pricing.MODEL_COST_DIVERGENCE if m not in {x for _, x in TABLE}],
)

print(f"\nALL PRICING TESTS PASSED ({passed} checks)")

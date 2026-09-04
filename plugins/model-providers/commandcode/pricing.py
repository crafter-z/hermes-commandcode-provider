"""Command Code pricing table (static snapshot).

Ported from the reference pi plugin's ``src/pricing.ts`` (``MODEL_COSTS``).
The Command Code Provider API does not include prices in its model catalog, so
this table supplies estimated per-request cost for Hermes cost display and
``estimate_usage_cost``.

Rates are USD per million tokens. Context-dependent rates use request-wide
input pricing tiers: the highest threshold exceeded by input + cache reads +
cache writes applies to the full request. The Command Code Usage page remains
authoritative for the amount billed for an individual request.

Hermes ``PricingEntry`` supports ONE ``tier_threshold_tokens`` with ``*_above``
rates replacing the base for the whole request (not marginal/bracketed). The
reference pi tables are full-rate tier tables with their own cache-write
semantics and, for DeepSeek V4, time-dependent rates. Faithful mapping:

* Single-threshold models encode exactly via ``tier_threshold_tokens`` +
  ``*_above`` (``grok-4.6``, ``qwen3.7-plus``).
* Multi-threshold models (``qwen3.8-max``, ``qwen3.7-flash``) and the
  DeepSeek 1h-write=2x-input rule have no direct ``PricingEntry`` target; they
  fall back to their dominant/highest tier as a flat rate (see
  ``MODEL_COST_DIVERGENCE``).
* DeepSeek V4 uses time-dependent rates; the documented off-peak rate (17h/day)
  is used, matching the reference plugin's display choice.

Keys are ``(provider, model)`` with the model id BARE (no ``vendor/`` prefix)
and lowercased, exactly what ``resolve_billing_route`` produces and what
``_lookup_official_docs_pricing`` looks up. ``provider`` is ``commandcode`` or
``commandcode-anthropic`` depending on which profile routes the model.
"""

from __future__ import annotations

from typing import Optional

# (provider, bare_model) → (input, output, cache_read, cache_write) USD/1M.
FLAT_PRICING: dict[tuple[str, str], tuple[float, float, float, float]] = {
    # Free models
    ("commandcode", "laguna-s-2.1-free"): (0.0, 0.0, 0.0, 0.0),
    # Open / open-weight
    ("commandcode", "hy3-paid"): (0.14, 0.58, 0.035, 0.0),
    ("commandcode", "hy4-preview"): (0.834, 2.501, 0.042, 0.0),
    ("commandcode", "kimi-k3"): (3.0, 15.0, 0.3, 0.0),
    ("commandcode", "kimi-k2.7-code"): (0.95, 4.0, 0.19, 0.0),
    ("commandcode", "kimi-k2.7-code-highspeed"): (1.9, 8.0, 0.38, 0.0),
    ("commandcode", "kimi-k2.6"): (0.95, 4.0, 0.16, 0.0),
    ("commandcode", "kimi-k2.5"): (0.6, 3.0, 0.1, 0.0),
    ("commandcode", "glm-5.3-flash"): (0.15, 0.5, 0.03, 0.0),
    ("commandcode", "glm-5.3"): (1.4, 4.4, 0.26, 0.0),
    ("commandcode", "glm-5.2"): (1.4, 4.4, 0.26, 0.0),
    ("commandcode", "glm-5.2-fast"): (3.0, 10.25, 0.5, 0.0),
    ("commandcode", "glm-5.1"): (1.4, 4.4, 0.26, 0.0),
    ("commandcode", "glm-5"): (1.0, 3.2, 0.2, 0.0),
    ("commandcode", "minimax-m3"): (0.3, 1.2, 0.06, 0.0),
    ("commandcode", "minimax-m2.7"): (0.3, 1.2, 0.06, 0.0),
    ("commandcode", "minimax-m2.5"): (0.3, 1.2, 0.03, 0.0),
    # DeepSeek V4 — off-peak rates (apply 17h/day)
    ("commandcode", "deepseek-v4-pro"): (0.66, 1.98, 0.022, 0.0),
    ("commandcode", "deepseek-v4-flash"): (0.22, 0.66, 0.007, 0.0),
    ("commandcode", "deepseek-v4-flash-vision-exp"): (0.22, 0.66, 0.007, 0.0),
    ("commandcode", "deepseek-v4-flash-fast"): (0.28, 0.56, 0.07, 0.0),
    # Qwen — multi-threshold models use flat dominant rate (see divergence)
    ("commandcode", "qwen3.8-max"): (2.0, 6.0, 0.25, 2.5),
    ("commandcode", "qwen3.8-27b"): (0.4, 3.0, 0.04, 0.0),
    ("commandcode", "qwen3.8-flash"): (0.16, 0.47, 0.016, 0.0),
    ("commandcode", "qwen3.7-max"): (2.5, 7.5, 0.5, 3.13),
    ("commandcode", "qwen3.7-plus"): (0.4, 1.6, 0.08, 0.5),
    ("commandcode", "qwen3.7-flash"): (0.2, 0.8, 0.04, 0.25),
    ("commandcode", "qwen3.6-max-preview"): (1.3, 7.8, 0.26, 1.63),
    ("commandcode", "qwen3.6-plus"): (0.5, 3.0, 0.1, 0.0),
    # StepFun
    ("commandcode", "step-3.7-flash"): (0.2, 1.15, 0.04, 0.0),
    ("commandcode", "step-3.5-flash"): (0.1, 0.3, 0.02, 0.0),
    # Xiaomi / NVIDIA / Sakana / Thinking Machines / Meta
    ("commandcode", "mimo-v2.5-pro"): (0.435, 0.87, 0.0036, 0.0),
    ("commandcode", "mimo-v2.5"): (0.14, 0.28, 0.0028, 0.0),
    ("commandcode", "nemotron-3-ultra-550b-a55b"): (0.6, 2.4, 0.12, 0.0),
    ("commandcode", "fugu-ultra"): (5.0, 30.0, 0.5, 0.0),
    ("commandcode", "inkling"): (1.0, 4.05, 0.17, 0.0),
    ("commandcode", "inkling-small"): (0.5, 1.2, 0.1, 0.0),
    ("commandcode", "muse-spark-1.1"): (1.25, 4.25, 0.15, 0.0),
    ("commandcode", "muse-spark-1.2"): (1.25, 4.25, 0.15, 0.0),
    ("commandcode", "muse-spark-1.2-contributor"): (0.1, 0.2, 0.002, 0.0),
    # Anthropic (commandcode-anthropic profile)
    ("commandcode-anthropic", "claude-sonnet-5"): (2.0, 10.0, 0.2, 2.5),
    ("commandcode-anthropic", "claude-sonnet-4-6"): (3.0, 15.0, 0.3, 3.75),
    ("commandcode-anthropic", "claude-fable-5-1"): (10.0, 50.0, 0.25, 12.5),
    ("commandcode-anthropic", "claude-fable-5"): (10.0, 50.0, 1.0, 12.5),
    ("commandcode-anthropic", "claude-opus-5"): (5.0, 25.0, 0.5, 6.25),
    ("commandcode-anthropic", "claude-opus-4-8"): (5.0, 25.0, 0.5, 6.25),
    ("commandcode-anthropic", "claude-opus-4-7"): (5.0, 25.0, 0.5, 6.25),
    ("commandcode-anthropic", "claude-haiku-4-5-20251001"): (1.0, 5.0, 0.1, 1.25),
    # OpenAI
    ("commandcode", "gpt-5.6-sol"): (5.0, 30.0, 0.5, 6.25),
    ("commandcode", "gpt-5.6-terra"): (2.0, 12.0, 0.2, 2.5),
    ("commandcode", "gpt-5.6-luna"): (0.2, 1.2, 0.02, 0.25),
    ("commandcode", "gpt-5.5"): (5.0, 30.0, 0.5, 0.0),
    ("commandcode", "gpt-5.4"): (2.5, 15.0, 0.25, 0.0),
    ("commandcode", "gpt-5.3-codex"): (2.0, 8.0, 0.5, 0.0),
    ("commandcode", "gpt-5.4-mini"): (0.75, 4.5, 0.075, 0.0),
    # Google
    ("commandcode", "gemini-3.7-flash"): (1.5, 7.5, 0.15, 0.08334),
    ("commandcode", "gemini-3.6-flash"): (1.5, 7.5, 0.15, 0.0),
    ("commandcode", "gemini-3.5-flash"): (1.5, 9.0, 0.15, 0.0),
    ("commandcode", "gemini-3.5-flash-lite"): (0.3, 2.5, 0.03, 0.0),
    ("commandcode", "gemini-3.1-flash-lite"): (0.25, 1.5, 0.03, 0.0),
    # xAI
    ("commandcode", "grok-4.5"): (2.0, 6.0, 0.5, 0.0),
    ("commandcode", "grok-4.6"): (2.0, 6.0, 0.5, 0.0),
}

# (provider, bare_model) → (threshold_tokens, input_above, output_above,
# cache_read_above, cache_write_above). Replaces the base rate for the WHOLE
# request once prompt_tokens (input + cache_read + cache_write) exceeds the
# threshold. Single-threshold models only.
SINGLE_TIERS: dict[tuple[str, str], tuple[int, float, float, float, float]] = {
    ("commandcode", "qwen3.7-plus"): (256_000, 1.2, 4.8, 0.24, 1.5),
    ("commandcode", "grok-4.6"): (200_000, 4.0, 12.0, 1.0, 0.0),
}

# Models whose reference pi table cannot be encoded exactly in PricingEntry.
# Documented divergence for reviewers; the Command Code Usage page is
# authoritative for the billed amount.
MODEL_COST_DIVERGENCE: dict[str, str] = {
    "qwen3.8-max": "multi-threshold (256k+) collapsed to flat dominant rate",
    "qwen3.7-flash": "multi-threshold (32k/256k) collapsed to flat dominant rate",
    "deepseek-v4-pro": "time-dependent rates; off-peak rate shown (17h/day)",
    "deepseek-v4-flash": "time-dependent rates; off-peak rate shown (17h/day)",
    "deepseek-v4-flash-vision-exp": "time-dependent rates; off-peak rate shown (17h/day)",
    "deepseek-v4-flash-fast": "time-dependent rates; off-peak rate shown (17h/day)",
}

PRICING_SOURCE_URL = "https://commandcode.ai/docs/resources/pricing-limits"
PRICING_LAST_VERIFIED = "2026-09-01"


def _decimal(value: float):
    from decimal import Decimal

    return Decimal(str(value))


def _make_entry(
    rates: tuple[float, float, float, float],
    tier: Optional[tuple[int, float, float, float, float]] = None,
):
    from agent.usage_pricing import PricingEntry

    input_r, output_r, cache_read_r, cache_write_r = rates
    if tier is None:
        return PricingEntry(
            input_cost_per_million=_decimal(input_r),
            output_cost_per_million=_decimal(output_r),
            cache_read_cost_per_million=_decimal(cache_read_r),
            cache_write_cost_per_million=_decimal(cache_write_r),
            source="official_docs_snapshot",
            source_url=PRICING_SOURCE_URL,
            pricing_version=PRICING_LAST_VERIFIED,
        )

    threshold, input_a, output_a, cache_read_a, _cache_write_a = tier
    return PricingEntry(
        input_cost_per_million=_decimal(input_r),
        output_cost_per_million=_decimal(output_r),
        cache_read_cost_per_million=_decimal(cache_read_r),
        cache_write_cost_per_million=_decimal(cache_write_r),
        source="official_docs_snapshot",
        source_url=PRICING_SOURCE_URL,
        pricing_version=PRICING_LAST_VERIFIED,
        tier_threshold_tokens=threshold,
        input_cost_per_million_above=_decimal(input_a),
        output_cost_per_million_above=_decimal(output_a),
        cache_read_cost_per_million_above=_decimal(cache_read_a),
    )


def install_pricing() -> bool:
    """Inject Command Code pricing into Hermes' official-docs pricing table.

    Returns True on success, False when ``agent.usage_pricing`` is not yet
    importable (circular-import guard during ``providers`` discovery). Callers
    may retry later — idempotent, so re-running replaces the same keys.

    Keys are added for the canonical profile names (``commandcode``,
    ``commandcode-anthropic``) AND for the custom-provider strings users may
    configure (e.g. ``custom:commandcode-goat``, ``commandcode-goat``), so
    ``resolve_billing_route`` matches whichever provider string the runtime
    carries. All resolvable because ``resolve_billing_route`` strips the
    vendor prefix and ``_lookup_official_docs_pricing`` lowercases the model.
    """
    try:
        from agent.usage_pricing import _OFFICIAL_DOCS_PRICING
    except (ImportError, AttributeError):
        # During providers/ discovery, agent.usage_pricing may be mid-import
        # (it imports agent.model_metadata). Don't crash the provider load;
        # the profile's get_pricing_entry path will still work, and retry on
        # a later call.
        return False

    # Provider strings the pricing must resolve for. Canonical profiles first,
    # then common custom-provider aliases a user might have in config.yaml.
    provider_aliases: dict[str, tuple[str, ...]] = {
        "commandcode": ("commandcode", "commandcode-goat", "custom:commandcode-goat"),
        "commandcode-anthropic": ("commandcode-anthropic",),
    }

    def _provider_names(canonical: str) -> tuple[str, ...]:
        return provider_aliases.get(canonical, (canonical,))

    for (provider, model), rates in FLAT_PRICING.items():
        for provider_name in _provider_names(provider):
            _OFFICIAL_DOCS_PRICING[(provider_name, model)] = _make_entry(rates)
    for (provider, model), tier in SINGLE_TIERS.items():
        for provider_name in _provider_names(provider):
            _OFFICIAL_DOCS_PRICING[(provider_name, model)] = _make_entry(
                (0.0, 0.0, 0.0, 0.0), tier=tier
            )
    return True


# Defer until agent.usage_pricing is importable; retry on later sessions when
# the provider profile is loaded after agent packages. Never fatal here.
_installed = False
try:
    _installed = install_pricing()
except Exception:  # noqa: BLE001 — the provider must load regardless.
    _installed = False

if not _installed:
    # During providers/ discovery agent.usage_pricing may be partially
    # initialized (its own import of agent.model_metadata). Re-inject the
    # moment that module finishes loading via a meta-path finder; idempotent,
    # so a later import just replaces the same keys. Minimal and harmless to a
    # normal session (find_spec returns None → import machinery proceeds).
    import importlib.abc
    import sys as _sys


    def _ensure_pricing() -> bool:
        global _installed
        if _installed:
            return True
        try:
            _installed = install_pricing()
        except Exception:  # noqa: BLE001
            _installed = False
        return _installed


    class _PricingInjector(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "agent.usage_pricing":
                _ensure_pricing()
            return None


    if not any(isinstance(f, _PricingInjector) for f in _sys.meta_path):
        _sys.meta_path.insert(0, _PricingInjector())

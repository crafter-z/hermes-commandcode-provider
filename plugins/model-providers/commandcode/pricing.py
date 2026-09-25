"""Command Code pricing table (static snapshot).

Ported from the reference pi plugin's ``src/pricing.ts`` (``MODEL_COSTS``),
re-synced on 2026-09-24. The Command Code Provider API does not include prices in
its model catalog, so this table supplies estimated per-request cost for
Hermes cost display and ``estimate_usage_cost``.

Rates are USD per million tokens. Context-dependent rates use request-wide
input pricing tiers: the highest threshold exceeded by input + cache reads +
cache writes applies to the full request. The Command Code Usage page remains
authoritative for the amount billed for an individual request.

Hermes ``PricingEntry`` supports ONE ``tier_threshold_tokens`` with ``*_above``
rates replacing the base for the whole request (not marginal/bracketed), for
every field it carries — including cache writes. Faithful mapping:

* Single-threshold models encode exactly via ``tier_threshold_tokens`` +
  ``*_above`` (``grok-4.6``, ``qwen3.7-plus``, the ``gpt-6`` family, …).
* Multi-threshold models (``qwen3.7-flash``) have no direct ``PricingEntry``
  target: the reference base rates are kept and the highest tier is encoded as
  ``*_above``, so short requests stay exact and only the intermediate tiers are
  approximate (see ``MODEL_COST_DIVERGENCE``). The DeepSeek V4 time-dependent
  rates show the documented off-peak rate (17h/day), matching the reference
  plugin's choice.
* ``xai/grok-4.7`` is priced at its 40% launch discount, which the reference
  table lists as expiring 2026-09-27 — re-sync before relying on it.

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
    ("commandcode", "ling-3.0-flash-sante:free"): (0, 0, 0, 0),
    ("commandcode", "laguna-s-2.1-free"): (0, 0, 0, 0),
    ("commandcode", "space-bunny-alpha"): (0, 0, 0, 0),
    # Open and open-weight models
    ("commandcode", "hy3-paid"): (0.14, 0.58, 0.035, 0),
    ("commandcode", "hy4-preview"): (0.834, 2.501, 0.042, 0),
    ("commandcode", "kimi-k3"): (3, 15, 0.3, 0),
    ("commandcode", "kimi-k2.7-code"): (0.95, 4, 0.19, 0),
    ("commandcode", "kimi-k2.7-code-highspeed"): (1.9, 8, 0.38, 0),
    ("commandcode", "kimi-k2.6"): (0.95, 4, 0.16, 0),
    ("commandcode", "kimi-k2.5"): (0.6, 3, 0.1, 0),
    ("commandcode", "glm-5.3-flash"): (0.15, 0.5, 0.03, 0),
    ("commandcode", "glm-5.3-flashx"): (0.37, 1.25, 0.075, 0),
    ("commandcode", "glm-5.3"): (1.4, 4.4, 0.26, 0),
    ("commandcode", "glm-5.2"): (1.4, 4.4, 0.26, 0),
    ("commandcode", "glm-5.2-fast"): (3, 10.25, 0.5, 0),
    ("commandcode", "glm-5.1"): (1.4, 4.4, 0.26, 0),
    ("commandcode", "glm-5"): (1, 3.2, 0.2, 0),
    ("commandcode", "minimax-m3"): (0.3, 1.2, 0.06, 0),
    ("commandcode", "minimax-m2.7"): (0.3, 1.2, 0.06, 0),
    ("commandcode", "minimax-m2.5"): (0.3, 1.2, 0.03, 0),
    # DeepSeek V4 uses time-dependent rates. Display the documented off-peak
    # rates, which apply for 17 hours per day; the Usage page remains authoritative.
    ("commandcode", "deepseek-v4-pro"): (0.66, 1.98, 0.022, 0),
    ("commandcode", "deepseek-v4-flash"): (0.15, 0.6, 0.003, 0),
    ("commandcode", "deepseek-v4-flash-vision-exp"): (0.15, 0.6, 0.003, 0),
    ("commandcode", "deepseek-v4-flash-fast"): (0.28, 0.56, 0.07, 0),
    ("commandcode", "deepseek-v4.1-flash"): (0.15, 0.6, 0.003, 0),
    ("commandcode", "qwen3.8-max"): (2, 6, 0.25, 2.5),
    ("commandcode", "qwen3.8-max-0902"): (2, 6, 0.25, 0),
    ("commandcode", "qwen3.8-27b"): (0.4, 3, 0.04, 0),
    ("commandcode", "qwen3.8-flash"): (0.16, 0.47, 0.016, 0),
    ("commandcode", "qwen3.8-omni-flash"): (0.15, 0.47, 0.016, 0),
    ("commandcode", "qwen3.7-max"): (2.5, 7.5, 0.5, 3.13),
    ("commandcode", "qwen3.7-plus"): (0.4, 1.6, 0.08, 0.5),
    ("commandcode", "qwen3.7-flash"): (0.03, 0.13, 0.006, 0.038),
    ("commandcode", "qwen3.6-max-preview"): (1.3, 7.8, 0.26, 1.63),
    ("commandcode", "qwen3.6-plus"): (0.5, 3, 0.1, 0),
    ("commandcode", "longcat-2.0"): (0.3, 1.2, 0.006, 0),
    ("commandcode", "step-5-preview"): (1, 2.7, 0.05, 0),
    ("commandcode", "step-3.7-flash"): (0.2, 1.15, 0.04, 0),
    ("commandcode", "step-3.5-flash"): (0.1, 0.3, 0.02, 0),
    # Permanent discounted rates.
    ("commandcode", "mimo-v2.5-pro"): (0.435, 0.87, 0.0036, 0),
    ("commandcode", "mimo-v2.5"): (0.14, 0.28, 0.0028, 0),
    ("commandcode", "mimo-v2.6-pro"): (0.435, 0.87, 0.0036, 0),
    ("commandcode", "mimo-v2.6-pro-ultraspeed"): (4.35, 8.7, 0.036, 0),
    ("commandcode", "mimo-v2.6-flash"): (0.14, 0.28, 0.0028, 0),
    ("commandcode", "nemotron-3-ultra-550b-a55b"): (0.6, 2.4, 0.12, 0),
    ("commandcode", "fugu-ultra"): (5, 30, 0.5, 0),
    ("commandcode", "inkling"): (1, 4.05, 0.17, 0),
    ("commandcode", "inkling-small"): (0.5, 1.2, 0.1, 0),
    ("commandcode", "muse-spark-1.1"): (1.25, 4.25, 0.15, 0),
    ("commandcode", "muse-spark-1.2"): (1.25, 4.25, 0.15, 0),
    ("commandcode", "muse-spark-1.3"): (1.25, 4.25, 0.15, 0),
    ("commandcode", "muse-spark-1.2-contributor"): (0.1, 0.2, 0.002, 0),
    ("commandcode", "muse-spark-1.3-contributor"): (0.1, 0.2, 0.002, 0),
    # Anthropic
    ("commandcode-anthropic", "claude-sonnet-5"): (2, 10, 0.2, 2.5),
    ("commandcode-anthropic", "claude-sonnet-4-6"): (3, 15, 0.3, 3.75),
    ("commandcode-anthropic", "claude-fable-5-1"): (10, 50, 0.25, 12.5),
    ("commandcode-anthropic", "claude-fable-5"): (10, 50, 1, 12.5),
    ("commandcode-anthropic", "claude-opus-5-5"): (4, 20, 0.2, 5),
    ("commandcode-anthropic", "claude-opus-5"): (5, 25, 0.5, 6.25),
    ("commandcode-anthropic", "claude-opus-4-8"): (5, 25, 0.5, 6.25),
    ("commandcode-anthropic", "claude-opus-4-7"): (5, 25, 0.5, 6.25),
    ("commandcode-anthropic", "claude-haiku-4-5-20251001"): (1, 5, 0.1, 1.25),
    # OpenAI
    ("commandcode", "gpt-6-astra"): (10, 50, 1, 12.5),
    ("commandcode", "gpt-6-sol"): (2, 10, 0.2, 2.5),
    ("commandcode", "gpt-6-luna"): (0.1, 0.5, 0.01, 0.125),
    ("commandcode", "gpt-5.6-sol"): (5, 30, 0.5, 6.25),
    ("commandcode", "gpt-5.6-terra"): (2, 12, 0.2, 2.5),
    ("commandcode", "gpt-5.6-luna"): (0.2, 1.2, 0.02, 0.25),
    ("commandcode", "gpt-5.5"): (5, 30, 0.5, 0),
    ("commandcode", "gpt-5.4"): (2.5, 15, 0.25, 0),
    ("commandcode", "gpt-5.3-codex"): (2, 8, 0.5, 0),
    ("commandcode", "gpt-5.4-mini"): (0.75, 4.5, 0.075, 0),
    # Google and xAI
    ("commandcode", "gemini-3.7-flash"): (1.5, 7.5, 0.15, 0.08334),
    ("commandcode", "gemini-3.8-flash"): (1.5, 7.5, 0.15, 0),
    ("commandcode", "gemini-3.6-flash"): (1.5, 7.5, 0.15, 0),
    ("commandcode", "gemini-3.5-flash"): (1.5, 9, 0.15, 0),
    ("commandcode", "gemini-3.5-flash-lite"): (0.3, 2.5, 0.03, 0),
    ("commandcode", "gemini-3.1-flash-lite"): (0.25, 1.5, 0.03, 0),
    ("commandcode", "grok-4.5"): (2, 6, 0.5, 0),
    ("commandcode", "grok-4.6"): (2, 6, 0.5, 0),
    # 40% launch discount; list price is 2 / 6 / 0.5, doubled above 200K.
    ("commandcode", "grok-4.7"): (1.2, 3.6, 0.3, 0),
}

# (provider, bare_model) → (threshold_tokens, input_above, output_above,
# cache_read_above, cache_write_above). Replaces the base rate for the WHOLE
# request once prompt_tokens (input + cache_read + cache_write) exceeds the
# threshold. Single-threshold models only; each key also has a FLAT_PRICING
# entry so below-threshold cost is the real base rate, not zero.
SINGLE_TIERS: dict[tuple[str, str], tuple[int, float, float, float, float]] = {
    ("commandcode", "qwen3.7-plus"): (256_000, 1.2, 4.8, 0.24, 1.5),
    ("commandcode", "qwen3.7-flash"): (256_000, 0.2, 0.8, 0.04, 0.25),
    ("commandcode", "gpt-6-astra"): (272_000, 20, 75, 2, 25),
    ("commandcode", "gpt-6-sol"): (272_000, 4, 15, 0.4, 5),
    ("commandcode", "gpt-6-luna"): (272_000, 0.2, 0.75, 0.02, 0.25),
    ("commandcode", "gpt-5.6-sol"): (272_000, 10, 45, 1, 12.5),
    ("commandcode", "gpt-5.6-terra"): (272_000, 4, 18, 0.4, 5),
    ("commandcode", "gpt-5.6-luna"): (272_000, 0.4, 1.8, 0.04, 0.5),
    ("commandcode", "grok-4.6"): (200_000, 4, 12, 1, 0),
    ("commandcode", "grok-4.7"): (200_000, 2.4, 7.2, 0.6, 0),
}

# Models whose reference table cannot be encoded exactly in PricingEntry.
# Documented divergence for reviewers; the Command Code Usage page is
# authoritative for the billed amount.
MODEL_COST_DIVERGENCE: dict[str, str] = {
    "qwen3.7-flash": "multi-threshold (32k/256k): base + 256k tier encoded; intermediate tiers dropped",
    "mimo-v2.5-pro": "launch discount reflected; list price is higher",
    "grok-4.7": "launch discount reflected; list price is higher",
    "qwen3.8-max": "multi-threshold (256k+) collapsed to flat dominant rate",
    "deepseek-v4-pro": "time-dependent rates; off-peak rate shown (17h/day)",
    "deepseek-v4-flash": "time-dependent rates; off-peak rate shown (17h/day)",
    "deepseek-v4-flash-vision-exp": "time-dependent rates; off-peak rate shown (17h/day)",
    "deepseek-v4-flash-fast": "time-dependent rates; off-peak rate shown (17h/day)",
}

PRICING_SOURCE_URL = "https://commandcode.ai/docs/resources/pricing-limits"
PRICING_LAST_VERIFIED = "2026-09-24"


def _decimal(value: float):
    from decimal import Decimal

    return Decimal(str(value))


def _make_entry(
    rates: tuple[float, float, float, float],
    tier: Optional[tuple[int, float, float, float, float]] = None,
):
    from agent.usage_pricing import PricingEntry

    input_r, output_r, cache_read_r, cache_write_r = rates
    kwargs = dict(
        input_cost_per_million=_decimal(input_r),
        output_cost_per_million=_decimal(output_r),
        cache_read_cost_per_million=_decimal(cache_read_r),
        cache_write_cost_per_million=_decimal(cache_write_r),
        source="official_docs_snapshot",
        source_url=PRICING_SOURCE_URL,
        pricing_version=PRICING_LAST_VERIFIED,
    )
    if tier is None:
        return PricingEntry(**kwargs)

    threshold, input_a, output_a, cache_read_a, cache_write_a = tier
    kwargs.update(
        tier_threshold_tokens=threshold,
        input_cost_per_million_above=_decimal(input_a),
        output_cost_per_million_above=_decimal(output_a),
        cache_read_cost_per_million_above=_decimal(cache_read_a),
        cache_write_cost_per_million_above=_decimal(cache_write_a),
    )
    return PricingEntry(**kwargs)


def install_pricing() -> bool:
    """Inject Command Code pricing into Hermes' official-docs pricing table.

    Returns True on success, False when ``agent.usage_pricing`` is not yet
    importable (circular-import guard during ``providers`` discovery). Callers
    may retry later — idempotent, so re-running replaces the same keys.

    Keys are ``(provider, model)`` for the plugin's own provider profiles:
    ``commandcode`` and ``commandcode-anthropic``. ``resolve_billing_route``
    strips the vendor prefix and ``_lookup_official_docs_pricing`` lowercases
    the model, so keys are the bare, lowercased model ids exactly as written in
    ``FLAT_PRICING``/``SINGLE_TIERS``.
    """
    try:
        from agent.usage_pricing import _OFFICIAL_DOCS_PRICING
    except (ImportError, AttributeError):
        # During providers/ discovery, agent.usage_pricing may be mid-import
        # (it imports agent.model_metadata). Don't crash the provider load;
        # the profile's get_pricing_entry path will still work, and retry on
        # a later call.
        return False

    for (provider, model), rates in FLAT_PRICING.items():
        _OFFICIAL_DOCS_PRICING[(provider, model)] = _make_entry(rates)
    for (provider, model), tier in SINGLE_TIERS.items():
        # Use the model's real base rates (they are also in FLAT_PRICING), so
        # below-threshold cost is correct rather than zero.
        base = FLAT_PRICING.get((provider, model), (0.0, 0.0, 0.0, 0.0))
        _OFFICIAL_DOCS_PRICING[(provider, model)] = _make_entry(base, tier=tier)
    return True


# Defer until agent.usage_pricing is importable; retry on later sessions when
# the provider profile is loaded after agent packages. Never fatal here.
_installed = False
try:
    _installed = install_pricing()
except Exception:  # noqa: BLE001 — the provider must load regardless.
    _installed = False


def ensure_pricing() -> bool:
    """Idempotently (re)inject Command Code pricing.

    Safe to call from a profile hot method (fetch_models /
    supported_reasoning_efforts) if the import-time injection was deferred by
    the circular-import guard. Returns True when pricing is installed.
    """
    global _installed
    if _installed:
        return True
    try:
        _installed = install_pricing()
    except Exception:  # noqa: BLE001 — never crash the provider path.
        _installed = False
    return _installed

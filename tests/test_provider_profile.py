"""Provider profile contract test (Hermes core stubbed).

Hermes' plugin loader imports this package with ``providers`` already on
``sys.path``; here the two things the profile actually touches are stubbed:
``providers.register_provider`` and ``providers.base.ProviderProfile`` /
``_profile_user_agent``. The live ``/models`` call is replaced by a fixture, so
the checks below are the *observable* contract of the two profiles:

* which model ids each wire publishes (a Claude id on the OpenAI card 400s),
* the vision model handed to ``default_vision_model``,
* the ``reasoning_effort`` field put on the wire for a given config,
* the per-model output cap.

Run with ``python tests/test_provider_profile.py`` (no pytest required).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PLUGIN_DIR = (
    Path(__file__).resolve().parent.parent / "plugins" / "model-providers" / "commandcode"
)

# ── stub the Hermes core surface the profile imports ─────────────────────────
providers = types.ModuleType("providers")
base = types.ModuleType("providers.base")


class ProviderProfile:  # noqa: D101 - mirrors core's dataclass-ish profile
    # Core declares this as a dataclass field with a None default.
    default_max_tokens = None

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


base.ProviderProfile = ProviderProfile
base._profile_user_agent = lambda: "hermes-cli/test"
providers.register_provider = lambda profile: None
providers.base = base
sys.modules["providers"] = providers
sys.modules["providers.base"] = base

spec = importlib.util.spec_from_file_location(
    "_hermes_user_provider_commandcode",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
profile_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = profile_module
spec.loader.exec_module(profile_module)

openai_profile = profile_module.commandcode
anthropic_profile = profile_module.commandcode_anthropic
catalog = profile_module._catalog_module

# ── fixture catalog, as the live /models endpoint would return it ────────────
LIVE_IDS = [
    "claude-sonnet-5",
    "claude-opus-5",
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-flash-vision-exp",
    "Qwen/Qwen3.8-Max",
    "zai-org/GLM-5.1",
]
profile_module._fetch_commandcode_models = lambda **_: list(LIVE_IDS)

passed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global passed
    assert cond, f"{label}: {detail}"
    passed += 1
    print(f"  ok  {label}" + (f"  ({detail})" if detail else ""))


# ── 1. each wire publishes exactly the ids it can serve ──────────────────────
openai_models = openai_profile.fetch_models()
anthropic_models = anthropic_profile.fetch_models()
check("openai wire drops every claude id", not any(m.startswith("claude-") for m in openai_models), openai_models)
check(
    "openai wire keeps every other id",
    openai_models == [m for m in LIVE_IDS if not m.startswith("claude-")],
    openai_models,
)
check(
    "anthropic wire keeps claude ids only",
    anthropic_models == [m for m in LIVE_IDS if m.startswith("claude-")],
    anthropic_models,
)
check("the two wires partition the live catalog", sorted(openai_models + anthropic_models) == sorted(LIVE_IDS), sorted(openai_models + anthropic_models))
profile_module._fetch_commandcode_models = lambda **_: None
check(
    "unreachable /models still reports None (Hermes uses fallback_models)",
    openai_profile.fetch_models() is None and anthropic_profile.fetch_models() is None,
)
profile_module._fetch_commandcode_models = lambda **_: list(LIVE_IDS)

# ── 2. vision default stays on the profile's own wire ───────────────────────
openai_vision = openai_profile.default_vision_model()
anthropic_vision = anthropic_profile.default_vision_model()
check(
    "openai vision default is a vision-capable model it can call",
    openai_vision == "deepseek/deepseek-v4-flash-vision-exp",
    openai_vision,
)
check(
    "anthropic vision default is a claude id (or None), never another vendor's",
    anthropic_vision is None or anthropic_vision.startswith("claude-"),
    anthropic_vision,
)
check(
    "anthropic vision default is image-capable when set",
    anthropic_vision is None or catalog.supports_image_input(anthropic_vision),
    anthropic_vision,
)

# ── 3. reasoning_effort is always something the endpoint accepts ─────────────
V41 = "deepseek/deepseek-v4.1-flash"
declared_v41 = openai_profile.supported_reasoning_efforts(V41)
check(
    "override expands v4.1-flash to the live-probed effort set",
    declared_v41 == ("low", "medium", "high", "xhigh", "max"),
    declared_v41,
)
check("no model → no effort knob", openai_profile.supported_reasoning_efforts(None) is None)
check("unknown model → no effort knob", openai_profile.supported_reasoning_efforts("nope/nope") == ())

cases = [
    (V41, "medium", "medium"),
    (V41, "xhigh", "xhigh"),
    (V41, "minimal", "low"),  # below the floor → the floor, never an invalid level
    (V41, "garbage", None),
    ("deepseek/deepseek-v4-flash", "medium", "high"),  # clamped DOWN to a declared level
    ("deepseek/deepseek-v4-flash", "xhigh", "high"),
    ("deepseek/deepseek-v4-flash", "max", "max"),
]
for model, requested, expected in cases:
    _, top_level = openai_profile.build_api_kwargs_extras(
        reasoning_config={"enabled": True, "effort": requested}, model=model
    )
    sent = top_level.get("reasoning_effort")
    allowed = set(openai_profile.supported_reasoning_efforts(model) or ())
    check(
        f"effort {requested!r} on {model} → {sent!r}",
        sent == expected and (sent is None or sent in allowed),
        f"expected {expected!r}, allowed {sorted(allowed)}",
    )

for config in ({"enabled": False, "effort": "high"}, {"effort": "none"}, {}):
    _, top_level = openai_profile.build_api_kwargs_extras(reasoning_config=config, model=V41)
    check(f"no effort sent for {config}", top_level == {}, top_level)
check("no model → no effort sent", openai_profile.build_api_kwargs_extras(model=None) == ({}, {}))

# ``off`` / ``none`` are disable sentinels, not levels. Upstream declares
# ("off", "high", "max") for the DeepSeek V4 family; the endpoint answers 400 for
# ``reasoning_effort:"off"``, and the CLI omits the field for it instead. So `off`
# must never be advertised as a selectable effort and never reach the wire.
ENDPOINT_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
OFF_MODEL = "deepseek/deepseek-v4-flash"
check(
    "the snapshot mirrors upstream's `off`",
    "off" in catalog.efforts_for_model(OFF_MODEL),
    catalog.efforts_for_model(OFF_MODEL),
)
check(
    "a model declaring `off` advertises levels only",
    openai_profile.supported_reasoning_efforts(OFF_MODEL) == ("high", "max"),
    openai_profile.supported_reasoning_efforts(OFF_MODEL),
)
for requested in ("off", "none"):
    _, top_level = openai_profile.build_api_kwargs_extras(
        reasoning_config={"enabled": True, "effort": requested}, model=OFF_MODEL
    )
    check(f"effort {requested!r} sends no reasoning_effort", top_level == {}, top_level)

# Sweep every declared model: the profile is only ever allowed to emit a level the
# endpoint accepts, whatever Hermes asks for.
sentinels_advertised = {}
emitted: set[str] = set()
for model_id in sorted(catalog.MODEL_EFFORTS):
    advertised = openai_profile.supported_reasoning_efforts(model_id) or ()
    if set(advertised) & {"off", "none"}:
        sentinels_advertised[model_id] = advertised
    for requested in ("minimal", "low", "medium", "high", "xhigh", "max", "off", "none", "garbage"):
        _, top_level = openai_profile.build_api_kwargs_extras(
            reasoning_config={"enabled": True, "effort": requested}, model=model_id
        )
        sent = top_level.get("reasoning_effort")
        if sent is not None:
            emitted.add(sent)
check(
    "no model advertises a disable sentinel as an effort level",
    not sentinels_advertised,
    sentinels_advertised,
)
check(
    "the profile can only emit endpoint-accepted efforts",
    emitted <= ENDPOINT_EFFORTS,
    sorted(emitted),
)

# The snapshot may legitimately carry a level this project cannot vouch for: the
# parser reports a new upstream value as reviewable drift rather than failing.
# That value must not leak past the wire boundary — no advertising it as
# selectable, no putting it on the wire, and no treating it as a floor that a
# low request could be escalated to.
FAKE = "vendor/foreign-levels"
_original = catalog.MODEL_EFFORTS.get(FAKE)
catalog.MODEL_EFFORTS[FAKE] = ("ultra", "very-high", "max")
try:
    check(
        "an unverified level is not advertised as selectable",
        openai_profile.supported_reasoning_efforts(FAKE) == ("max",),
        openai_profile.supported_reasoning_efforts(FAKE),
    )
    for requested, expected in (("ultra", None), ("very-high", None), ("max", "max"), ("low", None)):
        _, top_level = openai_profile.build_api_kwargs_extras(
            reasoning_config={"enabled": True, "effort": requested}, model=FAKE
        )
        sent = top_level.get("reasoning_effort")
        check(
            f"unverified levels: {requested!r} → {sent!r}",
            sent == expected,
            f"expected {expected!r}",
        )
    catalog.MODEL_EFFORTS[FAKE] = ("ultra",)
    _, top_level = openai_profile.build_api_kwargs_extras(
        reasoning_config={"enabled": True, "effort": "high"}, model=FAKE
    )
    check(
        "a model declaring only unverified levels gets no effort knob",
        openai_profile.supported_reasoning_efforts(FAKE) == () and top_level == {},
        (openai_profile.supported_reasoning_efforts(FAKE), top_level),
    )
finally:
    if _original is None:
        del catalog.MODEL_EFFORTS[FAKE]
    else:
        catalog.MODEL_EFFORTS[FAKE] = _original

# ── 4. per-model output caps ────────────────────────────────────────────────
capped = catalog.MODEL_MAX_OUTPUT_TOKENS
if capped:
    model_id, cap = sorted(capped.items())[0]
    check(
        "per-model output cap is reported",
        openai_profile.get_max_tokens(model_id) == cap,
        f"{model_id} → {cap}",
    )
check(
    "unknown model falls back to the default cap",
    openai_profile.get_max_tokens("nope/nope") == catalog.DEFAULT_MAX_OUTPUT_TOKENS,
    openai_profile.get_max_tokens("nope/nope"),
)
check("no model falls back to the profile default", openai_profile.get_max_tokens(None) is None)

# ── 5. the profiles do not invent hooks core never calls ────────────────────
check(
    "no get_model_metadata hook (not part of ProviderProfile)",
    not hasattr(openai_profile, "get_model_metadata"),
)

print(f"\nALL PROVIDER PROFILE TESTS PASSED ({passed} checks)")

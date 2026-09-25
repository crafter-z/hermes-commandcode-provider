"""Manual capability overrides layered over the generated catalog.

``catalog.py`` is generated from the ``command-code`` npm CLI package and must
stay byte-identical to upstream so ``scripts/sync_catalog.py`` keeps working as
a drift check ("Do not edit manually"). Anything this project wants to declare
beyond that snapshot belongs here: entries are merged onto the generated tables
at load time (see ``cache._catalog`` and the provider ``__init__``) and survive
``sync_catalog.py --write``.

Mirrors the reference pi plugin's ``commandcode-catalog-overrides.ts``.

Rules: add an override only with live evidence that the endpoint honours it, and
remove it once the CLI snapshot ships the same value.
"""

from __future__ import annotations

from typing import Any

# Reasoning efforts the endpoint accepts but the CLI snapshot under-declares.
#
# Live-probed 2026-09-10 against POST https://api.commandcode.ai/provider/v1/chat/completions:
# the `reasoning_effort` field answers 200 for low|medium|high|xhigh|max and 400
# ("Invalid option: expected one of \"low\"|\"medium\"|\"high\"|\"xhigh\"|\"max\"")
# for minimal and garbage values, while the CLI ships only ("low", "high", "max")
# for this model.
#
# Declaring the full accepted set matters because the profile clamps a requested
# effort DOWN to the nearest declared level, never up: against the 3-tier list a
# configured "medium" silently degrades to "low".
MODEL_EFFORT_OVERRIDES: dict[str, tuple[str, ...]] = {
    "deepseek/deepseek-v4.1-flash": ("low", "medium", "high", "xhigh", "max"),
}


def apply_overrides(catalog_module: Any) -> None:
    """Merge :data:`MODEL_EFFORT_OVERRIDES` onto a loaded ``catalog`` module.

    Idempotent. ``MODEL_EFFORTS`` is a plain dict so the generated table is
    updated in place and every accessor (``efforts_for_model``) sees the result.
    """
    for model_id, efforts in MODEL_EFFORT_OVERRIDES.items():
        catalog_module.MODEL_EFFORTS[model_id] = tuple(efforts)

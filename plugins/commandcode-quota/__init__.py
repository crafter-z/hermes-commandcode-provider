"""Command Code quota slash command.

Standalone Hermes plugin providing ``/commandcode-quota`` — a dashboard-style
report of the Command Code account's usage and quota, mirroring the reference
pi plugin's ``/commandcode-quota`` command.

Reads the same alpha usage endpoints the Command Code CLI ``/usage`` command
uses (whoami, billing/credits, billing/subscriptions, usage/summary) with the
same API key the provider already uses. Requires ``COMMANDCODE_API_KEY`` (or
``COMMAND_CODE_API_KEY``) in the environment; Command Code keys do not expire,
so no OAuth flow is needed.

Installed as a user plugin at ``$HERMES_HOME/plugins/commandcode-quota/`` and
enabled via ``hermes plugins enable commandcode-quota``.
"""

from __future__ import annotations

import os

from .quota import QuotaError, fetch_quota
from .quota_format import format_quota
from .status import _handle_refresh, _handle_status

_HELP_TEXT = "Usage: /commandcode-quota — show Command Code account usage and quota."


def _resolve_api_key() -> str | None:
    """Resolve the Command Code key from env vars.

    Mirrors the provider profile's env resolution: ``COMMANDCODE_API_KEY``
    first (the profile's primary var), then the legacy ``COMMAND_CODE_API_KEY``.
    """
    return os.environ.get("COMMANDCODE_API_KEY") or os.environ.get("COMMAND_CODE_API_KEY")


def _handle_quota(raw_args: str) -> str | None:
    if raw_args.strip() in {"help", "-h", "--help"}:
        return _HELP_TEXT

    api_key = _resolve_api_key()
    if not api_key:
        return (
            "/commandcode-quota requires an API key. Set COMMANDCODE_API_KEY "
            "(or COMMAND_CODE_API_KEY), or configure the Command Code provider."
        )

    try:
        quota = fetch_quota(api_key)
    except QuotaError as exc:
        return f"Command Code quota unavailable: {exc}"
    except (OSError, ValueError) as exc:
        # urllib URLError/HTTPError both subclass OSError; ValueError covers
        # schema mismatches. Never crash the session on a transient error.
        return f"Command Code quota failed: {exc}"
    except Exception as exc:  # never let a plugin error surface as a traceback
        return f"Command Code quota failed: {exc}"

    return format_quota(quota)


def _ensure_commandcode_pricing() -> None:
    """Idempotently inject Command Code pricing at session start.

    The provider profile's ``fetch_models``/``supported_reasoning_efforts`` call
    ``ensure_pricing()``, but those fire only when that profile path is used.
    An ``on_session_start`` hook guarantees the keys are present before any
    session turn computes cost, regardless of whether the user opened ``/model``
    or how the provider was resolved.
    """
    import sys
    import importlib.util
    from pathlib import Path

    pricing = sys.modules.get("_hermes_user_provider_commandcode.pricing")
    if pricing is None:
        # Locate the sibling model-provider override's pricing module.
        home = Path(__file__).resolve().parent.parent
        candidate = home / "plugins" / "model-providers" / "commandcode" / "pricing.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "_cc_pricing_lazy", str(candidate)
            )
            pricing = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pricing)
    ensure = getattr(pricing, "ensure_pricing", None)
    if callable(ensure):
        try:
            ensure()
        except Exception:
            # Never let a pricing side-effect break session start.
            pass


def register(ctx) -> None:
    """Register the slash command + session-start pricing hook.

    Called once by the Hermes plugin loader. The on_session_start hook injects
    Command Code pricing before any cost computation, covering custom-provider
    sessions that never exercise the provider profile's hot methods.
    """
    ctx.register_command(
        "commandcode-quota",
        handler=_handle_quota,
        description="Show Command Code account usage and quota.",
    )
    ctx.register_command(
        "commandcode-refresh",
        handler=_handle_refresh,
        description="Refresh the Command Code model catalog",
    )
    ctx.register_command(
        "commandcode-status",
        handler=_handle_status,
        description="Show redacted Command Code provider diagnostics",
    )
    ctx.register_hook("on_session_start", lambda **_: _ensure_commandcode_pricing())


__all__ = [
    "register",
    "_handle_quota",
    "_handle_refresh",
    "_handle_status",
    "_resolve_api_key",
]

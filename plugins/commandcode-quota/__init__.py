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


def register(ctx) -> None:
    """Register the slash command. Called once by the Hermes plugin loader."""
    ctx.register_command(
        "commandcode-quota",
        handler=_handle_quota,
        description="Show Command Code account usage and quota.",
    )


__all__ = ["register", "_handle_quota", "_resolve_api_key"]

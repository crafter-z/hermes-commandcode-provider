"""Format Command Code quota/usage as plain text.

Ported from the reference pi plugin's ``src/quota-format.ts``. Produces a
dashboard-style layout: credits remaining/used with a percentage, monthly /
purchased / free sources, the current plan, available usage totals, the API
key name, and the 5-hour and weekly usage windows.

Output is plain text so it renders across any host (here: an in-session slash
command in Hermes). Unavailable sections are listed explicitly rather than
shown as zero usage.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from .quota import Credits, Quota, Subscription

_WINDOW_LABELS = {"fiveHour": "5-hour", "weekly": "Weekly"}


def _format_reset_clock(reset_at_seconds: int, now: float) -> str:
    """Format seconds-until-reset as a short relative clock (e.g. 'in 2h 5m')."""
    try:
        reset_dt = datetime.fromtimestamp(reset_at_seconds, tz=timezone.utc)
        diff_ms = (reset_dt.timestamp() * 1000) - (now * 1000)
    except (OverflowError, OSError, ValueError):
        return "unknown"

    if diff_ms <= 0:
        return "soon"
    minutes = math.ceil(diff_ms / 60_000)
    if minutes < 60:
        return f"in {minutes}m"
    hours = minutes // 60
    remaining = minutes % 60
    if hours < 24:
        return f"in {hours}h {remaining}m" if remaining > 0 else f"in {hours}h"
    days = hours // 24
    return "in 1 day" if days == 1 else f"in {days} days"


def _format_window_limits(limits, now: float) -> list[str]:
    lines = []
    for limit in limits:
        used = f"{limit.used:.2f}"
        cap = f"{limit.cap:.2f}"
        percent = round((limit.used / limit.cap) * 100) if limit.cap > 0 else 0
        label = _WINDOW_LABELS.get(limit.window, limit.window)
        reset = f" (resets {_format_reset_clock(limit.reset_at, now)})" if limit.reset_at else ""
        lines.append(f"{label}: {used} / {cap} credits ({percent}% used){reset}")
    return lines


def _credits_detail(credits: Optional[Credits]) -> Optional[str]:
    if not credits:
        return None
    parts = [
        f"monthly ${credits.monthly_credits:.2f}",
        f"purchased ${credits.purchased_credits:.2f}",
    ]
    if credits.free_credits > 0:
        parts.append(f"free ${credits.free_credits:.2f}")
    return f"Sources: {' / '.join(parts)}"


def _parse_period_end(value: str) -> Optional[datetime]:
    trimmed = value.strip()
    if trimmed.isdigit():
        ts = float(trimmed)
    else:
        try:
            mid = datetime.fromisoformat(trimmed.replace("Z", "+00:00"))
            return mid if mid.tzinfo else mid.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if ts >= 1e12:
        ts /= 1000.0
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _subscription_line(subscription: Subscription, now: float) -> str:
    plan = (subscription.plan_id or "Unknown").replace("_", " ").replace("-", " ").strip()
    status = f" ({subscription.status})" if subscription.status else ""
    renewal = ""
    if subscription.current_period_end:
        end = _parse_period_end(subscription.current_period_end)
        if end:
            diff_ms = (end.timestamp() * 1000) - (now * 1000)
            days = math.ceil(diff_ms / 86_400_000)
            # Windows strftime rejects %-d, so build "Mon 5" manually.
            date_str = f"{end.strftime('%b')} {end.day}"
            if days > 0:
                renewal = f" · renews {date_str} ({days}d)"
            elif days == 0:
                renewal = f" · renews {date_str} (today)"
            else:
                renewal = f" · renewed {date_str}"
    return f"Plan: {plan}{status}{renewal}"


def _format_tokens(tokens: int) -> str:
    if tokens >= 1_000_000_000:
        return f"{tokens / 1_000_000_000:.1f}B"
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k"
    return str(tokens)


def format_quota(quota: Quota, now: Optional[float] = None) -> str:
    now = now if now is not None else datetime.now(tz=timezone.utc).timestamp()
    lines: list[str] = []
    remaining = quota.credits.remaining_credits if quota.credits else 0.0
    spent = quota.summary.total_cost if quota.summary else 0.0
    pool = remaining + spent

    if quota.credits or quota.summary:
        lines.append("Credits")
        lines.append(f"  Remaining: ${remaining:.2f} of ${pool:.2f}")
        lines.append(f"  Used: ${spent:.2f}")
        lines.append(f"  {round((spent / pool) * 100) if pool > 0 else 0}% used")

    detail = _credits_detail(quota.credits)
    if detail:
        lines.append(detail)
    if quota.subscription:
        lines.append(_subscription_line(quota.subscription, now))

    if quota.summary:
        lines.append("")
        lines.append("Usage (billing period)" if quota.subscription and quota.subscription.current_period_start else "Usage")
        lines.append(f"  Cost: ${quota.summary.total_cost:.2f}")
        lines.append(f"  Requests: {quota.summary.total_count:,}")
        if quota.summary.total_tokens is not None:
            lines.append(f"  Tokens: {_format_tokens(quota.summary.total_tokens)}")

    lines.append("")
    lines.append("Account")
    lines.append(f"  {quota.account.key_name or quota.account.login}")

    limits = quota.credits.window_limits if quota.credits else []
    if limits:
        lines.append("")
        lines.append("Usage windows:")
        lines.extend(f"  {line}" for line in _format_window_limits(limits, now))

    if quota.unavailable:
        lines.append("")
        labels = {"credits": "credits", "subscription": "subscription", "usage": "usage"}
        lines.append(f"Unavailable: {', '.join(labels.get(s, s) for s in quota.unavailable)}")

    lines.append("")
    lines.append("Full detail: https://commandcode.ai/usage")
    return "\n".join(lines)

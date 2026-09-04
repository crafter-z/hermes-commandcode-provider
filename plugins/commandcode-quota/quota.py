"""Command Code quota/usage fetch.

Ported from the reference pi plugin's ``src/quota.ts``. Reads the same alpha
usage endpoints the Command Code CLI ``/usage`` command uses:

    /alpha/whoami
    /alpha/billing/credits
    /alpha/billing/subscriptions
    /alpha/usage/summary

Authenticates with the same API key the provider already uses. Unavailable or
schema-mismatched sections are reported explicitly instead of being shown as
zero usage. Output is plain text via the plugin's command handler.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.commandcode.ai"
QUOTA_TIMEOUT_MS = 15_000

WindowName = str  # "fiveHour" | "weekly"


@dataclass(frozen=True)
class WindowLimit:
    window: WindowName
    used: float
    cap: float
    reset_at: Optional[int]


@dataclass(frozen=True)
class Credits:
    monthly_credits: float
    purchased_credits: float
    free_credits: float
    remaining_credits: float
    window_limits: list[WindowLimit] = field(default_factory=list)


@dataclass(frozen=True)
class Subscription:
    plan_id: Optional[str]
    status: Optional[str]
    current_period_start: Optional[str]
    current_period_end: Optional[str]


@dataclass(frozen=True)
class UsageSummary:
    total_cost: float
    total_count: int
    total_tokens: Optional[int]


@dataclass(frozen=True)
class Account:
    login: str
    org_id: Optional[str]
    key_name: Optional[str]


@dataclass(frozen=True)
class Quota:
    account: Account
    credits: Optional[Credits]
    subscription: Optional[Subscription]
    summary: Optional[UsageSummary]
    unavailable: tuple[str, ...] = ()


class QuotaError(Exception):
    """Raised when the quota fetch fails in a way we surface to the user."""


# ── Small JSON helpers ───────────────────────────────────────────────────────

def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _number_nonneg(value: Any) -> Optional[float]:
    n = _number(value)
    return n if n is not None and n >= 0 else None


def _string(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _timestamp(value: Any) -> Optional[str]:
    text = _string(value)
    if text:
        return text
    n = _number_nonneg(value)
    return str(int(n)) if n is not None else None


def _normalize_reset_at(value: Any) -> Optional[int]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        ts = value
    elif isinstance(value, str) and value:
        trimmed = value.strip()
        if trimmed.isdigit():
            ts = float(trimmed)
        else:
            # Date.parse equivalent: best-effort ISO → epoch seconds.
            try:
                from datetime import datetime, timezone

                parsed = datetime.fromisoformat(trimmed.replace("Z", "+00:00"))
                ts = parsed.timestamp()
            except ValueError:
                return None
    else:
        return None
    if ts >= 1e12:
        ts /= 1000.0
    return int(round(ts))


# ── Parsers ──────────────────────────────────────────────────────────────────

def parse_window_limits(value: Any) -> list[WindowLimit]:
    if not _is_record(value):
        return []
    limits: list[WindowLimit] = []
    for window, entry in (("fiveHour", value.get("fiveHour")), ("weekly", value.get("weekly"))):
        if not _is_record(entry):
            continue
        used = _number_nonneg(entry.get("used"))
        cap = _number_nonneg(entry.get("cap"))
        if used is None or cap is None or (used == 0 and cap == 0):
            continue
        limits.append(
            WindowLimit(
                window=window,
                used=used,
                cap=cap,
                reset_at=_normalize_reset_at(entry.get("resetAt")),
            )
        )
    return limits


def parse_credits(value: Any) -> Optional[Credits]:
    if not _is_record(value) or not _is_record(value.get("credits")):
        return None
    credits = value["credits"]
    monthly = _number_nonneg(credits.get("monthlyCredits"))
    purchased = _number_nonneg(credits.get("purchasedCredits"))
    free = _number_nonneg(credits.get("freeCredits"))
    if monthly is None and purchased is None and free is None:
        return None
    monthly = monthly or 0.0
    purchased = purchased or 0.0
    free = free or 0.0
    return Credits(
        monthly_credits=monthly,
        purchased_credits=purchased,
        free_credits=free,
        remaining_credits=monthly + purchased + free,
        window_limits=parse_window_limits(value.get("windowLimits")),
    )


def parse_subscription(value: Any) -> Optional[Subscription]:
    if not _is_record(value) or not _is_record(value.get("data")):
        return None
    data = value["data"]
    plan_id = _string(data.get("planId"))
    status = _string(data.get("status"))
    current_period_start = _timestamp(data.get("currentPeriodStart"))
    current_period_end = _timestamp(data.get("currentPeriodEnd"))
    if not plan_id and not status and not current_period_start and not current_period_end:
        return None
    return Subscription(
        plan_id=plan_id,
        status=status,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
    )


def parse_summary(value: Any) -> Optional[UsageSummary]:
    if not _is_record(value):
        return None
    total_cost = _number_nonneg(value.get("totalCost"))
    total_count = _number_nonneg(value.get("totalCount"))
    if total_cost is None or total_count is None:
        return None
    total_tokens = _number_nonneg(value.get("totalTokens"))
    if total_tokens is None:
        total_tokens = _number_nonneg(value.get("tokens"))
    return UsageSummary(
        total_cost=total_cost,
        total_count=int(total_count),
        total_tokens=int(total_tokens) if total_tokens is not None else None,
    )


def parse_whoami(value: Any) -> Optional[Account]:
    if not _is_record(value):
        return None
    org = value.get("org") if _is_record(value.get("org")) else None
    user = value.get("user") if _is_record(value.get("user")) else None
    login = (
        _string(org.get("login")) if org else None
    ) or (
        (_string(user.get("userName")) or _string(user.get("name"))) if user else None
    )
    if not login:
        return None
    org_id = _string(org.get("id")) if org else None
    key_name = (_string(user.get("keyName")) or _string(user.get("displayName"))) if user else None
    return Account(login=login, org_id=org_id, key_name=key_name)


# ── HTTP ─────────────────────────────────────────────────────────────────────

class _HttpError(Exception):
    def __init__(self, status: int, message: str, body: str):
        super().__init__(message)
        self.status = status
        self.body = body


class _QuotaTimeoutError(Exception):
    pass


_BUILD_URL_QUERY_KEYS = ("orgId", "since")


def _build_url(path: str, params: dict[str, Optional[str]]) -> str:
    query_parts = []
    for key in _BUILD_URL_QUERY_KEYS:
        value = params.get(key)
        if value:
            query_parts.append(f"{key}={urllib.parse.quote(str(value), safe='')}")
    return f"{path}?{'&'.join(query_parts)}" if query_parts else path


def fetch_quota(
    api_key: str,
    *,
    base_url: str = DEFAULT_API_BASE,
    extra_headers: Optional[dict[str, str]] = None,
    timeout_ms: int = QUOTA_TIMEOUT_MS,
) -> Quota:
    """Fetch and parse Command Code account usage/quota.

    Raises ``QuotaError`` with a user-facing message when the account cannot be
    resolved or every section fails. Individual sections that are unreachable
    or schema-mismatched are reported in ``Quota.unavailable`` instead of
    being treated as zero.
    """
    headers = {"accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    # One wall-clock budget for the whole fetch (whoami + 3 sections), matching
    # the reference plugin's single AbortController. Each individual request
    # times out against the *remaining* budget so a slow whoami cannot be
    # followed by three more full 15s waits.
    deadline = time.monotonic() + (timeout_ms / 1000.0)

    def request(path: str) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _QuotaTimeoutError()
        req = urllib.request.Request(base_url.rstrip("/") + path, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=remaining) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            return _HttpError(exc.code, exc.reason or "", body)
        except (TimeoutError, socket.timeout) as exc:
            raise _QuotaTimeoutError() from exc
        except urllib.error.URLError as exc:
            raise QuotaError(f"Failed to fetch Command Code quota: {exc.reason}") from exc

    # whoami is authoritative; a 401/403 here means the key is wrong.
    whoami_raw = request("/alpha/whoami")
    if isinstance(whoami_raw, _HttpError):
        _raise_http(whoami_raw, "whoami")
    account = parse_whoami(whoami_raw)
    if not account:
        raise QuotaError("Command Code returned an unrecognized account response")

    def safe_request(path: str) -> Any:
        try:
            return request(path)
        except _QuotaTimeoutError:
            return ("__timeout__",)
        except QuotaError:
            raise

    org_id = account.org_id
    credits_raw = safe_request(_build_url("/alpha/billing/credits", {"orgId": org_id}))
    subscription_raw = safe_request(_build_url("/alpha/billing/subscriptions", {"orgId": org_id}))

    unavailable: list[str] = []
    credits: Optional[Credits] = None
    subscription: Optional[Subscription] = None
    if isinstance(credits_raw, _HttpError):
        if credits_raw.status in (401, 403):
            _raise_http(credits_raw, "credits")
    elif credits_raw != ("__timeout__",):
        credits = parse_credits(credits_raw)
    if credits is None:
        unavailable.append("credits")

    if isinstance(subscription_raw, _HttpError):
        if subscription_raw.status in (401, 403):
            _raise_http(subscription_raw, "subscription")
    elif subscription_raw != ("__timeout__",):
        subscription = parse_subscription(subscription_raw)
    if subscription is None:
        unavailable.append("subscription")

    summary_raw = safe_request(
        _build_url(
            "/alpha/usage/summary",
            {"orgId": org_id, "since": subscription.current_period_start if subscription else None},
        )
    )
    summary: Optional[UsageSummary] = None
    if isinstance(summary_raw, _HttpError):
        if summary_raw.status in (401, 403):
            _raise_http(summary_raw, "summary")
    elif summary_raw != ("__timeout__",):
        summary = parse_summary(summary_raw)
    if summary is None:
        unavailable.append("usage")

    if credits is None and subscription is None and summary is None:
        raise QuotaError("Command Code returned no recognized usage data for the account")

    return Quota(
        account=account,
        credits=credits,
        subscription=subscription,
        summary=summary,
        unavailable=tuple(unavailable),
    )


def _raise_http(error: _HttpError, context: str) -> None:
    detail = error.body.strip()[:200]
    raise QuotaError(
        f"{context} request failed ({error.status}): {detail or error.message}"
    )

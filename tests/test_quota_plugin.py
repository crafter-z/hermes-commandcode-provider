"""Quota plugin fetch/format contract test.

Mirrors the real hermes loader: a ``hermes_plugins`` namespace parent plus a
package dir with ``__init__.py``, then a standard ``import``. Verifies
``fetch_quota`` against a local fake server and ``format_quota`` on the result.
Run with ``python tests/test_quota_plugin.py`` (no pytest required).
"""

from __future__ import annotations

import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "plugins" / "commandcode-quota"

# Build a temp hermes_plugins/commandcode_quota package mirroring the loader.
tmp = Path(tempfile.mkdtemp(prefix="ccquota_"))
pkg_root = tmp / "hermes_plugins"
pkg_dir = pkg_root / "commandcode_quota"
pkg_dir.mkdir(parents=True)
for name in ("__init__.py", "status.py", "quota.py", "quota_format.py"):
    shutil.copy(SRC / name, pkg_dir / name)
sys.path.insert(0, str(tmp))

import hermes_plugins.commandcode_quota as plugin  # noqa: E402

from hermes_plugins.commandcode_quota.quota import (  # noqa: E402
    parse_credits,
    parse_subscription,
    parse_summary,
    parse_whoami,
)
from hermes_plugins.commandcode_quota.quota_format import format_quota  # noqa: E402

fetch_quota = plugin._handle_quota  # not used here; we test module directly

# ── parser unit checks ──────────────────────────────────────────────────────
who = {"org": {"login": "alice", "id": "org1"}, "user": {"userName": "alice", "keyName": "dev"}}
a = parse_whoami(who)
assert a and a.login == "alice" and a.org_id == "org1" and a.key_name == "dev", a

cred = {
    "credits": {"monthlyCredits": 100, "purchasedCredits": 20, "freeCredits": 5},
    "windowLimits": {"fiveHour": {"used": 3, "cap": 10, "resetAt": "2030-01-01T00:00:00Z"}},
}
c = parse_credits(cred)
assert c and c.remaining_credits == 125.0 and len(c.window_limits) == 1, c

sub = {"data": {"planId": "goat", "status": "active", "currentPeriodEnd": "2030-01-01"}}
s = parse_subscription(sub)
assert s and s.plan_id == "goat" and s.status == "active", s

sm = {"totalCost": 3.5, "totalCount": 12, "totalTokens": 42000}
u = parse_summary(sm)
assert u and u.total_cost == 3.5 and u.total_count == 12 and u.total_tokens == 42000, u

# ── end-to-end fetch via local server ───────────────────────────────────────
responses = {
    "/alpha/whoami": who,
    "/alpha/billing/credits": cred,
    "/alpha/billing/subscriptions": sub,
    "/alpha/usage/summary": sm,
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = None
        for path_prefix, payload in responses.items():
            if self.path.startswith(path_prefix):
                body = payload
                break
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

from hermes_plugins.commandcode_quota.quota import fetch_quota  # noqa: E402

q = fetch_quota("test-key", base_url=f"http://127.0.0.1:{port}")
assert q.account.login == "alice"
assert q.credits and q.credits.remaining_credits == 125.0
assert q.subscription and q.subscription.plan_id == "goat"
assert q.summary and q.summary.total_cost == 3.5
assert q.unavailable == ()

out = format_quota(q)
assert "Credits" in out and "Remaining: $125.00" in out, out
assert "Plan: goat" in out and "Usage" in out, out
print("=== format_quota output ===")
print(out)

# ── timeout must surface a real message, never an empty error ───────────────
from hermes_plugins.commandcode_quota.quota import QuotaError  # noqa: E402

try:
    fetch_quota("test-key", base_url=f"http://127.0.0.1:{port}", timeout_ms=0)
except QuotaError as exc:
    timeout_message = str(exc)
else:
    raise AssertionError("a zero-ms budget must raise QuotaError")
assert "timed out" in timeout_message, repr(timeout_message)
print("=== quota plugin smoke OK ===")

srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)

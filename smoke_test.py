#!/usr/bin/env python3
"""ARGUS production smoke test (v10.38) — the refactor safety net.

Probes the live backend and asserts STRUCTURE, not just HTTP 200: each endpoint
must return the fields the app/inference depend on. Designed to NOT false-alarm
on weekends / market-closed (it checks shape, not "is it live right now"), and
to catch exactly the class of regression a scanner.py split could introduce —
e.g. a moved scoring function that stops producing callJa/assessment.

Run:  python3 smoke_test.py [BASE_URL]
Exit: 0 = all passed, 1 = one or more failed. Used by .github/workflows/smoke-test.yml
"""
import sys
import json
import time
import urllib.request
import urllib.error

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://argus-backend-3j2m.onrender.com").rstrip("/")
KNOWN_REGIME = {"RISK_ON", "RISK_OFF", "CAUTIOUS", "EVENT_WAIT", "MIXED"}
KNOWN_FRESH = {"fresh", "persisted", "stale", "not_run_yet"}
KNOWN_AI = {"live", "partial", "disabled", "missing_keys", "not_run_yet", "no_cached_result"}


def _get(path, timeout=45):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "argus-smoke"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), json.loads(r.read().decode("utf-8"))


def check(name, fn):
    """Run a validator with up to 3 attempts (transient cold-start / rate-limit
    tolerance). fn returns (ok, detail) or raises."""
    last = ""
    for attempt in range(3):
        try:
            ok, detail = fn()
            if ok:
                return (name, True, detail)
            last = detail
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:80]}"
        time.sleep(4)
    return (name, False, last)


# ── validators ──────────────────────────────────────────────────────────────
def v_healthz():
    c, d = _get("/healthz")
    return d.get("status") == "ok", f"build={d.get('buildSha')}"

def v_action_labels():
    c, d = _get("/api/argus/action-labels")
    mp = (d.get("marketPosture") or {}).get("label")
    return bool(mp), f"posture={mp} status={d.get('status')}"

def v_regime():
    c, d = _get("/api/argus/market-regime")
    lab = (d.get("regime") or {}).get("label")
    return lab in KNOWN_REGIME, f"regime={lab}"

def v_events():
    c, d = _get("/api/argus/events")
    return isinstance(d.get("events"), list), f"{len(d.get('events', []))} events"

def v_jp():
    c, d = _get("/api/argus/japan-watchlist")
    qf = d.get("quoteFreshness")
    ent_ok = (qf is None) or (qf.get("entitlement") in ("realtime", "delayed", "unknown", "mixed"))
    return isinstance(d.get("stocks"), list) and ent_ok, f"{len(d.get('stocks', []))} stocks ent={qf.get('entitlement') if qf else None}"

def v_us():
    c, d = _get("/api/argus/us-watchlist")
    return isinstance(d.get("stocks"), list), f"{len(d.get('stocks', []))} stocks"

def v_crypto():
    c, d = _get("/api/argus/crypto-watchlist")
    return isinstance(d.get("quotes"), list), f"{len(d.get('quotes', []))} quotes"

def v_scout_jp():
    # The key refactor regression check: moved scoring must still produce output.
    c, d = _get("/api/argus/entry-scout?symbol=7203")
    if d.get("status") != "live":
        return False, f"status={d.get('status')} (expected live for 7203)"
    a = d.get("assessment") or {}
    ok = bool(d.get("callJa")) and isinstance(a.get("reasonsJa"), list) and a.get("reasonsJa") \
        and isinstance((d.get("metrics") or {}).get("rsi14"), (int, float))
    return ok, f"call={str(d.get('callJa'))[:24]} reasons={len(a.get('reasonsJa') or [])}"

def v_scout_us():
    c, d = _get("/api/argus/entry-scout?symbol=AAPL&market=US")
    # US can be transiently rate-limited; just require a valid shape + status.
    return isinstance(d.get("status"), str), f"status={d.get('status')}"

def v_scout_batch():
    c, d = _get("/api/argus/scout-batch")
    return isinstance(d.get("records"), list), f"{len(d.get('records', []))} records"

def v_ledger_health():
    c, d = _get("/api/argus/ledger-health")
    ids = {L.get("id") for L in d.get("ledgers", [])}
    return ids == {"prediction", "scout", "closepin", "ai"}, f"ledgers={sorted(ids)}"

def v_ai_judgment():
    c, d = _get("/api/argus/ai-judgment")
    fr, st = d.get("freshness"), d.get("status")
    return (fr in KNOWN_FRESH) or (st in KNOWN_AI), f"freshness={fr} status={st}"

def v_calibration_deprecated():
    c, d = _get("/api/argus/calibration")
    return d.get("deprecated") is True and d.get("source") == "ledger-branch-summary", "deprecated->real summary"

def v_catalysts():
    c, d = _get("/api/argus/catalysts")
    return isinstance(d.get("items"), list), f"{len(d.get('items', []))} items"

def v_symbol_search():
    c, d = _get("/api/argus/symbol-search?q=7203&market=JP")
    res = d.get("results") or []
    return len(res) >= 1 and res[0].get("symbol") == "7203", f"{len(res)} results"

def v_integrations():
    c, d = _get("/api/argus/integrations")
    return "providers" in d, f"keys={list(d.keys())[:4]}"

def v_events_active():
    c, d = _get("/api/argus/events-active")
    return isinstance(d.get("events"), list) and "enabled" in d, f"enabled={d.get('enabled')} count={d.get('count')}"

def v_event_status():
    c, d = _get("/api/argus/event-backbone-status")
    return ("enabled" in d) and d.get("schemaVersion") == "event-v1", \
        f"enabled={d.get('enabled')} ntfy={d.get('ntfyConfigured')} jp={d.get('sessionJp')}"

def v_admin_gated_401(path):
    def fn():
        try:
            _get(path)
            return False, "expected 401, got 200 (admin endpoint UNPROTECTED!)"
        except urllib.error.HTTPError as e:
            return e.code == 401, f"HTTP {e.code} (correct: admin-gated)"
    return fn


CHECKS = [
    ("healthz", v_healthz),
    ("action-labels", v_action_labels),
    ("market-regime", v_regime),
    ("events", v_events),
    ("japan-watchlist", v_jp),
    ("us-watchlist", v_us),
    ("crypto-watchlist", v_crypto),
    ("entry-scout JP (moved code)", v_scout_jp),
    ("entry-scout US", v_scout_us),
    ("scout-batch", v_scout_batch),
    ("ledger-health", v_ledger_health),
    ("ai-judgment freshness", v_ai_judgment),
    ("calibration deprecated", v_calibration_deprecated),
    ("catalysts", v_catalysts),
    ("symbol-search", v_symbol_search),
    ("integrations", v_integrations),
    ("events-active", v_events_active),
    ("event-backbone-status", v_event_status),
    ("security-status 401", v_admin_gated_401("/api/argus/security-status")),
    ("ai-provider-status 401", v_admin_gated_401("/api/argus/ai-provider-status")),
]


def main():
    print(f"ARGUS smoke test → {BASE}\n" + "─" * 64)
    results = [check(name, fn) for name, fn in CHECKS]
    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"  {'✅' if ok else '❌'} {name:30} {detail}")
    print("─" * 64)
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", ", ".join(r[0] for r in failed))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())

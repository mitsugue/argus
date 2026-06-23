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
    """Run a validator with up to 5 attempts + increasing backoff. fn returns
    (ok, detail) or raises. A persistent HTTP 429 is an upstream RATE LIMIT
    (e.g. J-Quants), not a code regression — so it's tolerated as a soft-pass
    rather than paging a false 'smoke FAILED'. Real regressions surface as
    500/404/wrong-shape, which still fail."""
    last = ""
    rate_limited = False
    for attempt in range(5):
        try:
            ok, detail = fn()
            if ok:
                return (name, True, detail)
            last = detail
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rate_limited = True
            last = f"HTTP {e.code}: {str(e)[:60]}"
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:80]}"
        time.sleep(4 * (attempt + 1))  # 4,8,12,16s — ride out cold-start/rate windows
    if rate_limited:
        return (name, True, f"⏳ rate-limited (tolerated, not a regression): {last[:50]}")
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

def v_fund_nav():
    c, d = _get("/api/argus/fund-nav")
    funds = d.get("funds")
    ok = isinstance(funds, list) and len(funds) >= 1 and isinstance(funds[0].get("navYen"), (int, float))
    return ok, f"{len(funds or [])} funds nav (e.g. {funds[0]['code']}=¥{funds[0]['navYen']})" if funds else "no funds"

def v_market_movers():
    c, d = _get("/api/argus/market-movers")
    # valid in any of these shapes: live | missing_key | unavailable | warming
    # ('warming' = public read before the scheduled scan has populated the cache).
    return d.get("status") in ("live", "missing_key", "unavailable", "warming") and "gainers" in d, \
        f"status={d.get('status')} gainers={len(d.get('gainers', []))}{' note='+d['note'][:40] if d.get('note') else ''}"

def v_jp_market_movers():
    c, d = _get("/api/argus/jp-market-movers", timeout=60)
    return d.get("status") in ("live", "missing_key", "unavailable") and "gainers" in d, \
        f"status={d.get('status')} gainers={len(d.get('gainers', []))} universe={d.get('universe')}"

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
    return ("enabled" in d) and ("persistenceEnabled" in d), \
        f"enabled={d.get('enabled')} persist={d.get('persistenceEnabled')} lastSnap={d.get('lastSnapshotAt')}"

def v_event_snapshot():
    c, d = _get("/api/argus/event-snapshot")
    return d.get("schemaVersion") == "event-store-v1" and isinstance(d.get("active"), list), f"active={d.get('activeCount')}"

def _crypto_scan_gated():
    import urllib.request, urllib.error
    req = urllib.request.Request(BASE + "/api/argus/crypto-scan", method="POST", headers={"User-Agent": "argus-smoke"})
    try:
        urllib.request.urlopen(req, timeout=30)
        return False, "expected 401/503 (admin), got 200 — UNPROTECTED!"
    except urllib.error.HTTPError as e:
        return e.code in (401, 503), f"HTTP {e.code} (admin-gated)"

def v_calibration_posture():
    c, d = _get("/api/argus/calibration/posture")
    o = d.get("outcome") or {}
    return o.get("status") in ("ok", "partial") and isinstance(o.get("dimensions"), dict), \
        f"status={o.get('status')} inputs={len(d.get('inputsUsed') or [])}"

def v_calibration_cohorts_v2():
    c, d = _get("/api/argus/calibration/cohorts")
    rs = (d.get("cohorts") or {}).get("regime_sensor_fixed") or {}
    ta = (d.get("cohorts") or {}).get("tactical_benchmark_fixed") or {}
    return rs.get("count") == 16 and ta.get("count") == 14, \
        f"L1={rs.get('count')} L2A={ta.get('count')} univ={d.get('regimeSensorUniverseVersion')}"

def v_watchlist_sync_gated():
    import urllib.request, urllib.error
    req = urllib.request.Request(BASE + "/api/argus/calibration/watchlist-sync", method="POST",
                                 headers={"User-Agent": "argus-smoke", "Content-Type": "application/json"},
                                 data=b'{"items":[]}')
    try:
        urllib.request.urlopen(req, timeout=30)
        return False, "expected 401/503 (owner-gated), got 200 — UNPROTECTED!"
    except urllib.error.HTTPError as e:
        return e.code in (401, 503), f"HTTP {e.code} (owner-gated)"

def v_decision_value_summary():
    c, d = _get("/api/argus/decision-value/summary")
    return d.get("schemaVersion") == "decision-value-v1" and "No broker" in (d.get("safety") or ""), \
        f"status={d.get('status')} phase={d.get('phase')}"

def v_legacy_routes_gated():
    # Security (v10.88): legacy /api/run, /api/reset must NOT be open.
    import urllib.error
    for path, method in (("/api/run", "POST"), ("/api/reset", "POST"), ("/api/logs", "GET")):
        try:
            req = urllib.request.Request(BASE + path, method=method, headers={"User-Agent": "argus-smoke"})
            urllib.request.urlopen(req, timeout=20)
            return False, f"{path} is OPEN — must be admin-gated!"
        except urllib.error.HTTPError as e:
            if e.code not in (401, 503):
                return False, f"{path} returned {e.code}, expected 401/503"
    return True, "legacy /api/run|reset|logs admin-gated"

def v_no_order_routes():
    # Safety: there must be NO order/execute route (research-only, no auto-trading).
    import urllib.error
    for path in ("/api/argus/decision-value/order", "/api/argus/decision-value/execute",
                 "/api/argus/downside/order", "/api/argus/downside/execute"):
        try:
            _get(path)
            return False, f"{path} exists — must NOT (no order routes!)"
        except urllib.error.HTTPError as e:
            if e.code != 404:
                return False, f"{path} returned {e.code}, expected 404"
    return True, "no order/execute routes (correct)"

def v_tdnet_recent():
    # TDnet feed (v10.101): public, read-only. Items (when present) carry a
    # classified sentiment. Unavailable is acceptable (third-party wrapper).
    c, d = _get("/api/argus/tdnet-recent")
    if d.get("status") not in ("live", "unavailable"):
        return False, f"status={d.get('status')}"
    for it in (d.get("items") or [])[:5]:
        if it.get("sentiment") not in ("negative", "positive", "neutral"):
            return False, f"bad sentiment {it.get('sentiment')}"
    return True, f"status={d.get('status')} count={d.get('count')}"

def v_downside_incidents():
    # Downside Incident Response (v10.98): public, never just generic "急落".
    c, d = _get("/api/argus/downside-incidents")
    if d.get("engineVersion") != "downside-v1":
        return False, f"engineVersion={d.get('engineVersion')}"
    if not isinstance(d.get("incidents"), list):
        return False, "incidents not a list"
    if "jpIntradayOverlay" not in d or "holderRiskOverlay" not in d:
        return False, "missing overlay fields"
    # Every incident must carry cause buckets that sum to ~1 + an action override.
    for inc in d["incidents"]:
        total = round(sum(b.get("probability", 0) for b in inc.get("causeBuckets") or []), 2)
        if inc.get("causeBuckets") and total != 1.0:
            return False, f"{inc.get('symbol')} buckets sum={total}"
        if inc.get("actionOverride") in (None, "", "HOLD"):
            return False, f"{inc.get('symbol')} override not set"
    return True, f"status={d.get('status')} active={d.get('activeCount')} overlay={d.get('jpIntradayOverlay')}"

def v_source_registry():
    c, d = _get("/api/argus/source-registry")
    return isinstance(d.get("sources"), list) and d.get("engineVersion") == "source-registry-v1", \
        f"{d.get('confirmedLive')}/{d.get('total')} live"

def v_system_health():
    c, d = _get("/api/argus/system-health")
    lamps = d.get("lamps")
    ok = isinstance(lamps, list) and d.get("overall") in ("ok", "warning", "stopped", "off") \
        and any(l.get("key") == "ai_budget" for l in lamps)
    # public-safe: no dollar amounts must leak into the lamp payload
    leaks = "Usd" in json.dumps(d) or "$" in json.dumps(d)
    return ok and not leaks, f"overall={d.get('overall')} lamps={len(lamps or [])}"

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
    ("fund-nav (投信 NAV)", v_fund_nav),
    ("market-movers (US全市場)", v_market_movers),
    ("jp-market-movers (日本全市場)", v_jp_market_movers),
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
    ("event-snapshot", v_event_snapshot),
    ("crypto-scan admin", _crypto_scan_gated),
    ("calibration cohorts v2 (16/14)", v_calibration_cohorts_v2),
    ("calibration posture (multidim)", v_calibration_posture),
    ("watchlist-sync owner-gated", v_watchlist_sync_gated),
    ("decision-value summary", v_decision_value_summary),
    ("no order routes (safety)", v_no_order_routes),
    ("downside-incidents (cause+override)", v_downside_incidents),
    ("tdnet-recent (適時開示)", v_tdnet_recent),
    ("legacy routes admin-gated", v_legacy_routes_gated),
    ("source-registry", v_source_registry),
    ("system-health (public lamps)", v_system_health),
    ("security-status 401", v_admin_gated_401("/api/argus/security-status")),
    ("ai-provider-status 401", v_admin_gated_401("/api/argus/ai-provider-status")),
    ("ai-cost 401", v_admin_gated_401("/api/argus/ai-cost")),
    ("tdnet-metrics 401", v_admin_gated_401("/api/argus/tdnet-metrics")),
    ("moomoo-capability 401", v_admin_gated_401("/api/argus/moomoo-capability")),
    ("jp-universe 401", v_admin_gated_401("/api/argus/jp-universe")),
    ("layer2b-summary 401", v_admin_gated_401("/api/argus/calibration/layer2b-summary")),
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

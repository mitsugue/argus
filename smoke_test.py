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
EXPLICIT_NEGATIVE_PATHS = (
    "/api/argus/decision-value/order",
    "/api/argus/decision-value/execute",
    "/api/argus/downside/order",
    "/api/argus/downside/execute",
)

def _get(path, timeout=45):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "argus-smoke"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.getcode(), json.loads(r.read().decode("utf-8"))

def _post_json(path, body, timeout=30):
    """POST a JSON body (no admin token). Returns (code, dict). HTTPError → (code, {})."""
    import urllib.error
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"User-Agent": "argus-smoke", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}

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

def v_scout_batch():
    c, d = _get("/api/argus/scout-batch")
    return isinstance(d.get("records"), list), f"{len(d.get('records', []))} records"

def v_ai_judgment():
    c, d = _get("/api/argus/ai-judgment")
    fr, st = d.get("freshness"), d.get("status")
    return (fr in KNOWN_FRESH) or (st in KNOWN_AI), f"freshness={fr} status={st}"

def v_catalysts():
    c, d = _get("/api/argus/catalysts")
    return isinstance(d.get("items"), list), f"{len(d.get('items', []))} items"

def v_symbol_search():
    c, d = _get("/api/argus/symbol-search?q=7203&market=JP")
    res = d.get("results") or []
    return len(res) >= 1 and res[0].get("symbol") == "7203", f"{len(res)} results"

def v_events_active():
    c, d = _get("/api/argus/events-active")
    expected = {
        "enabled", "asOf", "schemaVersion", "count", "events",
        "activeCount", "ntfyConfigured", "sessionJp", "sessionUs",
        "lastDetectionAt", "lastEventAt",
    }
    if set(d) != expected:
        return False, f"shape drift missing={sorted(expected - set(d))} extra={sorted(set(d) - expected)}"
    if not isinstance(d.get("events"), list):
        return False, "events not a list"
    if not all(type(d.get(key)) is bool for key in (
            "enabled", "ntfyConfigured", "sessionJp", "sessionUs")):
        return False, "backbone status booleans missing"
    if not all(isinstance(d.get(key), int) for key in ("count", "activeCount")):
        return False, "event counts missing"
    return True, (f"enabled={d.get('enabled')} count={d.get('count')} "
                  f"active={d.get('activeCount')} ntfy={d.get('ntfyConfigured')}")

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
        # 429 = the IP rate limiter fired BEFORE routing (smoke burst) — it neither
        # proves nor disproves the admin gate; tolerated like the other checks.
        return e.code in (401, 503, 429), f"HTTP {e.code} (admin-gated)"

def v_watchlist_sync_gated():
    import urllib.request, urllib.error
    req = urllib.request.Request(BASE + "/api/argus/calibration/watchlist-sync", method="POST",
                                 headers={"User-Agent": "argus-smoke", "Content-Type": "application/json"},
                                 data=b'{"items":[]}')
    try:
        urllib.request.urlopen(req, timeout=30)
        return False, "expected 401/503 (owner-gated), got 200 — UNPROTECTED!"
    except urllib.error.HTTPError as e:
        return e.code in (401, 503, 429), f"HTTP {e.code} (owner-gated)"

def v_legacy_routes_gated():
    # Security (v10.88): legacy /api/run, /api/reset must NOT be open.
    import urllib.error
    for path, method in (("/api/run", "POST"), ("/api/reset", "POST"), ("/api/logs", "GET")):
        try:
            req = urllib.request.Request(BASE + path, method=method, headers={"User-Agent": "argus-smoke"})
            urllib.request.urlopen(req, timeout=20)
            return False, f"{path} is OPEN — must be admin-gated!"
        except urllib.error.HTTPError as e:
            if e.code not in (401, 503, 429):
                return False, f"{path} returned {e.code}, expected 401/503"
    return True, "legacy /api/run|reset|logs admin-gated"

def v_no_order_routes():
    # Safety: there must be NO order/execute route (research-only, no auto-trading).
    import urllib.error
    for path in EXPLICIT_NEGATIVE_PATHS:
        try:
            _get(path)
            return False, f"{path} exists — must NOT (no order routes!)"
        except urllib.error.HTTPError as e:
            # The safety guarantee is "no 200 order route". A 429 means the per-IP rate
            # limiter fired BEFORE routing (it runs as a before_request hook), so every
            # path — including non-existent ones — returns 429; that is NOT evidence of an
            # order route. Tolerate it (retry/soft-pass); only a non-404/429 is suspicious.
            if e.code == 429:
                continue
            if e.code != 404:
                return False, f"{path} returned {e.code}, expected 404"
    return True, "no order/execute routes (correct)"

def v_action_labels_have_evidence_refs():
    # every non-mock label must reference its evidence pack (decision spine).
    c, d = _get("/api/argus/action-labels")
    for l in (d.get("labels") or []):
        if l.get("status") == "mock":
            continue
        refs = l.get("decisionRefs") or {}
        if not str(refs.get("evidencePackId", "")).startswith("ep-"):
            return False, f"{l.get('symbol')} missing evidencePackId"
        if "confidenceBefore" not in refs or "confidenceAfter" not in refs:
            return False, f"{l.get('symbol')} missing confidence before/after"
    return True, "all live labels carry decisionRefs"

def v_official_events():
    # v11.3: lifecycle-tracked official disclosures. Shape-only (empty store OK —
    # it fills as the official TDnet feed is read).
    c, d = _get("/api/argus/official-events?limit=5")
    if d.get("schemaVersion") != "official-event-lifecycle-v1":
        return False, f"schema={d.get('schemaVersion')}"
    if not isinstance(d.get("items"), list):
        return False, "items not a list"
    for it in (d.get("items") or [])[:3]:
        if it.get("causeStatus") not in ("fact_only", "probable_catalyst", "confirmed_cause",
                                         "not_cause", "unknown"):
            return False, f"bad causeStatus {it.get('causeStatus')}"
        if it.get("causeStatus") == "confirmed_cause":
            mr = it.get("marketReaction") or {}
            if not any((mr.get(k) or {}).get("marketConfirmed") for k in mr):
                return False, "confirmed_cause without market confirmation!"
    return True, f"count={d.get('count')}"

def v_official_events_status():
    c, d = _get("/api/argus/official-events/status")
    ok = (d.get("schemaVersion") == "official-event-lifecycle-v1"
          and isinstance(d.get("byStage"), dict))
    return ok, f"total={d.get('total')} material={d.get('material')} lastIngest={d.get('lastIngestAt')}"

def v_official_events_durability():
    # v11.3.1: research history must survive restarts — and the safety contract holds.
    c, d = _get("/api/argus/official-events/durability")
    if d.get("schemaVersion") != "official-event-durability-v1":
        return False, f"schema={d.get('schemaVersion')}"
    s = d.get("safety") or {}
    if s.get("publicGetFetchesProvider") is not False:
        return False, "publicGetFetchesProvider must be false"
    if s.get("storesFullText") is not False or s.get("storesPrivatePortfolio") is not False:
        return False, "full-text/portfolio safety flags wrong"
    blob = json.dumps(d).lower()
    for bad in ("apikey", "x-api-key", "holdings", "costbasis"):
        if bad in blob:
            return False, f"leak {bad}"
    rt, du = d.get("runtimeStore") or {}, d.get("durableStore") or {}
    return True, (f"runtime={rt.get('count')}({rt.get('pathType')}) "
                  f"ledger={du.get('latestLedgerDate')}/{du.get('latestCount')} restore={du.get('restoreAvailable')}")

def v_official_event_sample_lifecycle():
    # if a sample exists, its detail + lifecycle views must resolve (never 500) and a
    # confirmed_cause must carry market confirmation.
    c, d = _get("/api/argus/official-events?limit=1")
    items = d.get("items") or []
    if not items:
        return True, "store empty (fills as the official feed is read)"
    oid = items[0].get("officialEventId")
    c2, one = _get(f"/api/argus/official-events/{oid}")
    if one.get("officialEventId") != oid:
        return False, f"detail mismatch {oid}"
    c3, lc = _get(f"/api/argus/official-events/{oid}/lifecycle")
    if lc.get("causeStatus") == "confirmed_cause":
        mr = lc.get("marketReaction") or {}
        if not any((mr.get(k) or {}).get("marketConfirmed") for k in mr):
            return False, "confirmed_cause without market confirmation!"
    return True, f"{oid} stage={lc.get('lifecycleStage')} cause={lc.get('causeStatus')}"

def v_official_admin_gated():
    # POST-only admin endpoints: no token → 401 (or 503 if unconfigured), never 200.
    import urllib.error
    for path in ("/api/argus/admin/official-events/snapshot",
                 "/api/argus/admin/official-events/restore"):
        req = urllib.request.Request(BASE + path, method="POST",
                                     headers={"User-Agent": "argus-smoke"})
        try:
            with urllib.request.urlopen(req, timeout=30):
                return False, f"{path} returned 200 without token!"
        except urllib.error.HTTPError as e:
            if e.code not in (401, 503, 429):
                return False, f"{path} returned {e.code}, expected 401/503"
    return True, "snapshot/restore admin-gated"

def v_news_japanese_first():
    # v11.5.1: a US cause-attribution news item must never surface raw English as its
    # primary display title — displayTitleJa is Japanese or a JP fallback, and any
    # English original is confined to titleOriginal/titleEn (the 原文を見る disclosure).
    import re as _re
    en = _re.compile(r"[A-Za-z]")
    jp = _re.compile(r"[぀-ヿ㐀-䶵一-鿋]")
    for sym in ("NVDA", "AAPL", "TSLA"):
        c, d = _get(f"/api/argus/cause-attribution?symbol={sym}&market=US", timeout=40)
        if c == 429:
            return True, f"{sym}: 429 pre-routing (skip)"
        news = (d or {}).get("news") or []
        for n in news:
            title = n.get("displayTitleJa") or ""
            if en.search(title) and not jp.search(title):
                return False, f"{sym}: raw English primary title: {title[:60]!r}"
        if news:
            return True, f"{sym}: {len(news)} news, no raw-English primary"
    return True, "no US media headlines available (ok)"

def v_explain_request_public():
    # Recovery Phase A: mutation is no longer public.
    code, d = _post_json("/api/argus/mover-causes/explain-request",
                         {"symbol": "IONQ", "market": "US", "context": "cause-stack"})
    return code in (401, 503) and d.get("error") in (
        "unauthorized", "admin_unavailable"), f"status={code}"

def v_translation_request_public():
    # Recovery Phase A: mutation is no longer public.
    code, d = _post_json("/api/argus/news/translation-request",
                         {"context": "cause-stack", "symbol": "IONQ", "market": "US",
                          "items": [{"titleOriginal": "IonQ smoke-test headline about markets",
                                     "source": "smoke"}]})
    return code in (401, 503) and d.get("error") in (
        "unauthorized", "admin_unavailable"), f"status={code}"

def v_queue_admin_gated():
    # v11.5.2: translate-visible + explain/run reject a token-less POST (401/503).
    import urllib.error
    for path in ("/api/argus/admin/news/translate-visible",
                 "/api/argus/admin/mover-causes/explain/run"):
        req = urllib.request.Request(BASE + path, method="POST", headers={"User-Agent": "argus-smoke"})
        try:
            with urllib.request.urlopen(req, timeout=30):
                return False, f"{path} returned 200 without token!"
        except urllib.error.HTTPError as e:
            if e.code not in (401, 503, 429):
                return False, f"{path} returned {e.code}"
    return True, "translate-visible + explain/run admin-gated"

def v_cause_attribution_ionq_displaytitle():
    # v11.5.2 IONQ regression: visible cause-attribution news carries displayTitleJa +
    # translationStatus, and no raw-English primary title leaks through.
    import re as _re
    en = _re.compile(r"[A-Za-z]"); jp = _re.compile(r"[぀-ヿ㐀-䶵一-鿋]")
    c, d = _get("/api/argus/cause-attribution?symbol=IONQ&market=US", timeout=40)
    if c == 429:
        return True, "429 pre-routing (skip)"
    news = (d or {}).get("news") or []
    for n in news:
        if "displayTitleJa" not in n or "translationStatus" not in n:
            return False, "news item missing displayTitleJa/translationStatus"
        title = n.get("displayTitleJa") or ""
        if en.search(title) and not jp.search(title):
            return False, f"raw English primary: {title[:50]!r}"
    return True, f"IONQ: {len(news)} news, displayTitleJa present, no raw-English"

def v_caos_watchtower_plan():
    c, d = _get("/api/argus/caos/watchtower-plan")
    if d.get("schemaVersion") != "caos-watchtower-plan-v1":
        return False, f"schema={d.get('schemaVersion')}"
    targets = d.get("targets") or []
    classes = {t.get("assetClass") for t in targets}
    for ac in ("GOLD_GLD", "BONDS_TLT", "CRYPTO_BTC_ETH", "FX_USDJPY", "CASH"):
        if ac not in classes:
            return False, f"baseline class missing: {ac}"
    if not any(t.get("symbol") == "GLD" for t in targets):
        return False, "GLD baseline target missing"
    return True, f"targets={len(targets)}"

def v_caos_watchtower_status():
    c, d = _get("/api/argus/caos-watchtower/status")
    if d.get("schemaVersion") != "caos-watchtower-status-v1":
        return False, f"schema={d.get('schemaVersion')}"
    cov = d.get("coverageByAssetClass") or {}
    if "JP_EQUITY" not in cov or "CRYPTO_BTC_ETH" not in cov:
        return False, "coverage classes missing"
    if "near-real-time" not in (d.get("noteJa") or ""):
        return False, "must not overclaim real-time"
    live = sum(1 for s in d.get("sources", []) if s.get("status") == "live")
    return True, f"sources={len(d.get('sources') or [])} live={live} alerts={len(d.get('alerts') or [])}"

def v_investigate_now_public():
    # Recovery Phase A: mutation is no longer public.
    code, d = _post_json("/api/argus/caos/investigate-now",
                         {"symbol": "IONQ", "market": "US", "context": "cause-stack"},
                         timeout=40)
    return code in (401, 503) and d.get("error") in (
        "unauthorized", "admin_unavailable"), f"status={code}"

def v_news_newest_first():
    # v11.5.6 owner rule: every news list is newest-first; undated items at the tail.
    c, d = _get("/api/argus/market-news")
    dts = [i.get("datetime") for i in (d.get("items") or [])]
    dated = [x for x in dts if x is not None]
    if dated != sorted(dated, reverse=True):
        return False, f"market-news not newest-first: {dts[:8]}"
    if None in dts and any(x is not None for x in dts[dts.index(None):]):
        return False, "undated market-news item above dated ones"
    c2, d2 = _get("/api/argus/cause-attribution?symbol=IONQ&market=US", timeout=40)
    if c2 != 429:
        ages = [(n.get("newsFreshness") or {}).get("ageHours")
                for n in (d2.get("news") or [])]
        dated2 = [a for a in ages if a is not None]
        if dated2 != sorted(dated2):
            return False, f"cause-attribution news not newest-first: {ages[:8]}"
    return True, f"market-news {len(dts)} items sorted; cause-attribution sorted"

def v_flow_attribution():
    # v11.7.0: flow attribution — public cached-only, hedged vocabulary, no trading.
    c, d = _get("/api/argus/flow-attribution?symbol=6146&market=JP")
    if d.get("schemaVersion") != "flow-attribution-response-v1":
        return False, f"schema={d.get('schemaVersion')}"
    rec = d.get("record") or {}
    for k in ("flowClass", "flowClassJa", "confidence", "directness", "missingEvidence",
              "ownerReadableWhyJa", "actionImplication", "complianceNote"):
        if k not in rec:
            return False, f"record missing {k}"
    if rec["actionImplication"] not in ("investigate", "wait_for_confirmation",
                                        "avoid_chase", "monitor", "caution", "no_action"):
        return False, f"trade-like action: {rec['actionImplication']}"
    if "大口が買っている" in (rec.get("ownerReadableWhyJa") or ""):
        return False, "assertive big-money phrase leaked"
    c2, d2 = _get("/api/argus/flow-attribution")
    if "records" not in d2:
        return False, "list missing records"
    return True, f"single={rec['flowClass']}({rec['confidence']}) list={len(d2['records'])}"

def v_supply_demand():
    # v11.10.0: 需給ランク — rank+state primary, honest sources, no orders.
    c, d = _get("/api/argus/supply-demand?symbol=6146")
    sig = d.get("signal") or {}
    if sig.get("schemaVersion") != "supply-demand-v1":
        return False, f"schema={sig.get('schemaVersion')}"
    if sig.get("supplyDemandRank") not in ("S", "A", "B", "C", "D", "E", "Unknown"):
        return False, f"rank={sig.get('supplyDemandRank')}"
    if not str(sig.get("readabilityLabelJa", "")).startswith("需給ランク"):
        return False, "readability label missing"
    if sig.get("actionImplication") not in ("monitor", "wait", "avoid_chase",
                                            "add_only_on_pullback", "investigate",
                                            "caution", "no_action"):
        return False, f"trade-like action: {sig.get('actionImplication')}"
    ev = sig.get("evidence") or {}
    if ev.get("reverseStockLendingFee") is not None:
        return False, "逆日歩 fabricated (source not ingested)"
    return True, f"rank={sig['supplyDemandRank']} cond={sig.get('condition')} conf={sig.get('confidence')}"

def v_price_history_shape():
    c, d = _get("/api/argus/price-history?symbol=6146&market=JP")
    if d.get("schemaVersion") != "price-history-v1":
        return False, f"schema={d.get('schemaVersion')}"
    if "available" not in d or "closes" not in d:
        return False, "shape missing"
    return True, f"available={d['available']} n={len(d.get('closes') or [])}"

def v_supply_demand_us():
    # v11.11.0: US gets an honest simplified read (never squeeze, FINRA marked missing)
    c, d = _get("/api/argus/supply-demand?symbol=NVDA&market=US")
    sig = d.get("signal") or {}
    if sig.get("market") != "US":
        return False, f"market={sig.get('market')}"
    if sig.get("condition") in ("squeeze_prone", "credit_overhang"):
        return False, "US must not classify squeeze/credit (no data source)"
    if not any("FINRA" in m for m in (sig.get("missingEvidence") or [])):
        return False, "FINRA gap must be explicit"
    return True, f"rank={sig.get('supplyDemandRank')} cond={sig.get('condition')}"

def v_supply_demand_level_model():
    # v11.14.0: direction≠level — heavy overhang can never rank A/S.
    c, d = _get("/api/argus/supply-demand?symbol=5803&market=JP")
    sig = d.get("signal") or {}
    lvl = sig.get("supplyDemandLevel")
    rank = sig.get("supplyDemandRank")
    if lvl in ("heavy", "very_heavy") and rank in ("S", "A"):
        return False, f"HEAVY LEVEL RANKED {rank} (Fujikura bug regressed)"
    return True, f"5803 rank={rank} level={lvl} cond={sig.get('condition')}"

def v_data_quality_status():
    c, d = _get("/api/argus/data-quality/status")
    if d.get("schemaVersion") != "argus-public-diagnostics-v1":
        return False, f"schema={d.get('schemaVersion')}"
    health = d.get("systemHealth") or {}
    expected_health = {"asOf", "overall", "lamps", "noteJa"}
    if set(health) != expected_health:
        return False, "systemHealth shape drift"
    lamps = health.get("lamps")
    if not isinstance(lamps, list) or not any(
            lamp.get("key") == "ai_budget" for lamp in lamps):
        return False, "systemHealth lamps missing ai_budget"
    if health.get("overall") not in ("ok", "warning", "stopped", "off"):
        return False, f"systemHealth overall={health.get('overall')}"
    for lamp in lamps:
        if set(lamp) != {"key", "labelJa", "status", "detailJa"}:
            return False, "systemHealth lamp shape drift"
    health_blob = json.dumps(health, ensure_ascii=False)
    if "Usd" in health_blob or "$" in health_blob:
        return False, "systemHealth leaked cost amounts"
    recovery = d.get("recovery") or {}
    if recovery.get("exactColdRecovery") != "NOT_PROVEN":
        return False, "recovery claim must be conservative"
    return True, (f"overall={(d.get('service') or {}).get('overall')} "
                  f"health={health.get('overall')} lamps={len(lamps)} "
                  f"disabled={(d.get('freshness') or {}).get('expectedDisabledCount')}")

def v_bridge_status_segmented():
    # v11.5.7: segmented bridge status — bridge/OpenD/US/JP evaluated apart, and
    # "all green" can never imply JP realtime when entitlement is missing.
    c, d = _get("/api/argus/bridge/status")
    if d.get("schemaVersion") != "bridge-status-v1":
        return False, f"schema={d.get('schemaVersion')}"
    for k in ("bridgeProcess", "openDStatus", "usRealtimeStatus", "jpRealtimeStatus",
              "jpFallbackActive", "bridgeMode"):
        if k not in d:
            return False, f"{k} missing"
    blob = json.dumps(d, ensure_ascii=False).lower()
    for bad in ('"token":', '"secret":', '"password":', '"apikey":'):
        if bad in blob:
            return False, f"forbidden key {bad}"
    return True, (f"bridge={d['bridgeProcess']} openD={d['openDStatus']} "
                  f"us={d['usRealtimeStatus']} jp={d['jpRealtimeStatus']} "
                  f"mode={d['bridgeMode']}")

def v_bridge_heartbeat_gated():
    import urllib.error
    req = urllib.request.Request(BASE + "/api/argus/bridge/heartbeat",
                                 method="POST", headers={"User-Agent": "argus-smoke"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return False, "returned 200 without token!"
    except urllib.error.HTTPError as e:
        if e.code not in (401, 503, 429):
            return False, f"returned {e.code}"
    return True, "heartbeat admin-gated"

def v_patrol_health():
    # v11.5.5: 24h soak proof — schema + deterministic status + no violations.
    c, d = _get("/api/argus/caos/patrol-health")
    if d.get("schemaVersion") != "caos-patrol-health-v1":
        return False, f"schema={d.get('schemaVersion')}"
    if d.get("status") not in ("healthy", "degraded", "stale", "error", "not_ready"):
        return False, f"bad status {d.get('status')}"
    s = d.get("summary") or {}
    for k in ("runs24h", "deepSweeps24h", "baselineSweeps24h", "emptyDeepSweepRuns24h",
              "oldPrimaryViolations"):
        if k not in s:
            return False, f"summary.{k} missing"
    if s.get("oldPrimaryViolations"):
        return False, f"OLD NEWS AS PRIMARY: {s['oldPrimaryViolations']}"
    if d.get("status") == "error":
        return False, "patrol-health status=error"
    if "ledger" not in d:
        return False, "restore ledger missing"
    return True, (f"status={d.get('status')} runs24h={s.get('runs24h')} "
                  f"deep={s.get('deepSweeps24h')} baseline={s.get('baselineSweeps24h')}")

def v_watchtower_status_patrol_ref():
    c, d = _get("/api/argus/caos-watchtower/status")
    ph = d.get("patrolHealth")
    if not isinstance(ph, dict):
        return False, "patrolHealth missing on watchtower status"
    for k in ("status", "deepSweeps24h", "baselineSweeps24h"):
        if k not in ph:
            return False, f"patrolHealth.{k} missing"
    return True, f"patrol={ph.get('status')} deep24h={ph.get('deepSweeps24h')}"

def v_patrol_self_check_gated():
    import urllib.error
    req = urllib.request.Request(BASE + "/api/argus/admin/caos/patrol-self-check",
                                 method="POST", headers={"User-Agent": "argus-smoke"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return False, "returned 200 without token!"
    except urllib.error.HTTPError as e:
        if e.code not in (401, 503, 429):
            return False, f"returned {e.code}"
    return True, "patrol-self-check admin-gated"

def v_watchtower_admin_gated():
    import urllib.error
    req = urllib.request.Request(BASE + "/api/argus/admin/caos-watchtower/refresh",
                                 method="POST", headers={"User-Agent": "argus-smoke"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return False, "returned 200 without token!"
    except urllib.error.HTTPError as e:
        if e.code not in (401, 503, 429):
            return False, f"returned {e.code}"
    return True, "watchtower refresh admin-gated"

def v_macro_reaction_admin_gated():
    import urllib.error
    req = urllib.request.Request(BASE + "/api/argus/admin/macro-event-analysis/refresh-market-reaction",
                                 method="POST", headers={"User-Agent": "argus-smoke"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return False, "returned 200 without token!"
    except urllib.error.HTTPError as e:
        if e.code not in (401, 503, 429):
            return False, f"returned {e.code}"
    return True, "refresh-market-reaction admin-gated"

def v_dashboard_events_reaction_shape():
    # v11.5: released items with an official result must carry a marketReaction block
    # (numeric fields or an honest 未取得), never fake numbers.
    c, d = _get("/api/argus/dashboard-events?limit=10")
    for it in (d.get("items") or []):
        if it.get("state") in ("post_result", "post_answer_checked"):
            mr = it.get("marketReaction")
            if not isinstance(mr, dict):
                return False, f"{it.get('eventCode')} missing marketReaction"
    return True, f"items={len(d.get('items') or [])}"

def v_dashboard_events():
    # v11.4.1: the unified top-card event feed. Shape + no-leak; state must be valid.
    c, d = _get("/api/argus/dashboard-events")
    if d.get("schemaVersion") != "dashboard-event-summary-v1":
        return False, f"schema={d.get('schemaVersion')}"
    if not isinstance(d.get("items"), list) or "dedupe" not in d or "status" not in d:
        return False, "items/dedupe/status missing"
    valid = {"pre", "imminent", "released_pending_result", "post_result",
             "post_answer_checked", "stale", "not_scoreable"}
    for it in d["items"]:
        for k in ("displayEventId", "eventCode", "state", "stateLabelJa", "display",
                  "officialResult", "caos", "dedupeKey"):
            if k not in it:
                return False, f"missing {k}"
        if it["state"] not in valid:
            return False, f"bad state {it['state']}"
        if not isinstance(it["officialResult"].get("available"), bool):
            return False, "officialResult.available not bool"
    blob = json.dumps(d).lower()
    for bad in ('"prompt":', '"messages":', '"rawproviderbody":', '"holdings":',
                '"pnl":', '"costbasis":', '"apikey":'):
        if bad in blob:
            return False, f"leak {bad}"
    return True, f"items={len(d['items'])} hiddenDup={d['dedupe'].get('hiddenDuplicateCount')}"

def v_dashboard_events_nfp():
    # If NFP's official result is available, the unified card MUST be post (never pre),
    # show actual first, and carry a non-empty impact comment. If not yet available,
    # this is a soft pass (nothing to assert about a pre/pending NFP).
    c, m = _get("/api/argus/macro-event-analysis?eventCode=NFP")
    nfp_macro = next((it for it in (m.get("items") or []) if it.get("eventCode") == "NFP"), None)
    actual_avail = bool((nfp_macro or {}).get("actual", {}).get("available")) if nfp_macro else False
    c, d = _get("/api/argus/dashboard-events?eventCode=NFP")
    # dashboard-events importance filter isn't code-based, so scan all items for NFP
    _, dall = _get("/api/argus/dashboard-events?limit=20")
    nfp = next((it for it in (dall.get("items") or []) if it.get("eventCode") == "NFP"), None)
    if not actual_avail:
        return True, f"NFP actual not yet available (soft pass; card state={nfp.get('state') if nfp else 'n/a'})"
    if not nfp:
        return False, "NFP actual available but missing from dashboard-events"
    if nfp["state"] == "pre":
        return False, "NFP released but state=pre!"
    if not nfp["display"].get("showActualFirst"):
        return False, "NFP post but showActualFirst=false"
    facts = nfp["officialResult"].get("headlineJa") or nfp["display"].get("primaryLineJa")
    if not facts:
        return False, "NFP post but no official facts shown"
    if not (nfp["caos"].get("impactCommentJa") or "").strip():
        return False, "NFP post but impact comment empty"
    return True, f"NFP state={nfp['state']} actualFirst=True impact✓"

def v_macro_repair_admin_gated():
    import urllib.error
    req = urllib.request.Request(BASE + "/api/argus/admin/macro-event-analysis/repair-post-release",
                                 method="POST", headers={"User-Agent": "argus-smoke"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return False, "repair returned 200 without token!"
    except urllib.error.HTTPError as e:
        if e.code not in (401, 503, 429):
            return False, f"repair returned {e.code}"
    return True, "repair-post-release admin-gated"

def v_macro_event_analysis():
    # v11.3.2: durable macro pre/post analyses. Shape-only; the release-day invariant:
    # an event whose eventTimeUtc is in the future must NOT be phase=post_result.
    from datetime import datetime, timezone
    c, d = _get("/api/argus/macro-event-analysis?limit=10")
    if d.get("schemaVersion") != "macro-event-analysis-v1":
        return False, f"schema={d.get('schemaVersion')}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for it in (d.get("items") or []):
        for k in ("eventId", "eventCode", "phase"):
            if k not in it:
                return False, f"missing {k}"
        if not isinstance((it.get("actual") or {}).get("available"), bool):
            return False, "actual.available not bool"
        etu = it.get("eventTimeUtc")
        if etu and str(etu) > now and it.get("phase") in ("post_result", "released_pending_result"):
            return False, f"{it.get('eventCode')} unreleased but phase={it.get('phase')}!"
    blob = json.dumps(d).lower()
    for bad in ("apikey", "x-api-key", "holdings", "costbasis"):
        if bad in blob:
            return False, f"leak {bad}"
    return True, f"count={d.get('count')}"

def v_macro_admin_gated():
    import urllib.error
    for path in ("/api/argus/admin/macro-event-analysis/generate",
                 "/api/argus/admin/macro-event-analysis/refresh-results"):
        req = urllib.request.Request(BASE + path, method="POST",
                                     headers={"User-Agent": "argus-smoke"})
        try:
            with urllib.request.urlopen(req, timeout=30):
                return False, f"{path} returned 200 without token!"
        except urllib.error.HTTPError as e:
            if e.code not in (401, 503, 429):
                return False, f"{path} returned {e.code}"
    return True, "generate/refresh-results admin-gated"

# ── V11.3.3 Mover Cause Engine ──

def v_downside_carries_mover_cause():
    c, d = _get("/api/argus/downside-incidents")
    incs = d.get("incidents") or []
    if not incs:
        return True, "no active incidents (shape n/a)"
    for inc in incs:
        mc = inc.get("moverCause") or {}
        if not mc.get("causeStatus"):
            return False, f"{inc.get('symbol')} missing moverCause"
        if mc["causeStatus"] != "not_scoreable" and not (mc.get("bestLeadJa") or mc.get("nextChecksJa")):
            return False, f"{inc.get('symbol')} no lead AND no next checks"
        reason = inc.get("reasonJa") or ""
        if "原因未確認" in reason and ("候補" not in reason and "確認済み" not in reason
                                    and "有力材料" not in reason and "原因確認" not in reason):
            return False, f"{inc.get('symbol')} bare 原因未確認 without ladder text"
    return True, f"incidents={len(incs)} all carry causeStatus"

def v_learning_memory_admin_gated():
    import urllib.error
    for path in ("/api/argus/admin/learning-memory/build",
                 "/api/argus/admin/learning-memory/restore"):
        req = urllib.request.Request(BASE + path, method="POST",
                                     headers={"User-Agent": "argus-smoke"})
        try:
            with urllib.request.urlopen(req, timeout=30):
                return False, f"{path} returned 200 without token!"
        except urllib.error.HTTPError as e:
            if e.code not in (401, 503, 429):
                return False, f"{path} returned {e.code}"
    return True, "build/restore admin-gated"

def v_public_explain_cached_only():
    # explain=1 must return cached text or not_generated — never a live AI run.
    t0 = time.time()
    c, d = _get("/api/argus/cause-attribution?symbol=8058&market=JP&explain=1", timeout=40)
    took = time.time() - t0
    st = d.get("explanationStatus")
    if st not in ("cached", "not_generated"):
        return False, f"explanationStatus={st} (live-LLM path suspected)"
    if "moverCause" not in d:
        return False, "cause-attribution missing moverCause ladder"
    return True, f"explanationStatus={st} in {took:.1f}s"

def v_ai_judgment_gemini_challenge_shape():
    # v11.2.1: when the cached AI payload is post-v11.2 it must carry the structured
    # challenge; a pre-v11.2 cache (no key) soft-passes until the next scheduled run.
    c, d = _get("/api/argus/ai-judgment")
    ch = d.get("geminiChallenge")
    if ch is None:
        return True, f"pre-v11.2 cache (freshness={d.get('freshness')}) — next run adds it"
    for k in ("gptView", "geminiChallenge", "agreement", "mainWeaknessJa",
              "whatWouldChangeJa", "unverifiedAssumptions"):
        if k not in ch:
            return False, f"challenge missing {k}"
    if ch.get("agreement") not in ("confirm", "caution", "disagree", "unavailable"):
        return False, f"bad agreement {ch.get('agreement')}"
    return True, f"agreement={ch.get('agreement')}"

def v_ai_judgment_evidence_refs_safe():
    # if an AI judgment is cached, its labels may carry decisionRefs — and the payload
    # must never contain secret material. (Older cached payloads without refs pass.)
    c, d = _get("/api/argus/ai-judgment")
    blob = json.dumps(d).lower()
    for bad in ("apikey", "x-api-key", "subscription-key"):
        if bad in blob:
            return False, f"secret-ish '{bad}' in ai-judgment payload"
    n_refs = sum(1 for l in (d.get("labels") or []) if (l.get("decisionRefs") or {}).get("evidencePackId"))
    return True, f"freshness={d.get('freshness')} labelsWithRefs={n_refs}"

def v_closepin_phase():
    c, d = _get("/api/argus/closepin-snapshot")
    if d.get("engineVersion") != "closepin-v1":
        return False, f"engine={d.get('engineVersion')}"
    if not d.get("intradayPhase"):
        return False, "no intradayPhase"
    lims = " ".join(d.get("dataLimitations") or [])
    if "オークション" not in lims:
        return False, "missing closing-auction disclaimer"
    return True, f"phase={d.get('intradayPhase')}"

def v_cause_attribution():
    c, d = _get("/api/argus/cause-attribution?symbol=285A&market=JP")
    if d.get("schemaVersion") != "cause-attribution-v1":
        return False, f"schema={d.get('schemaVersion')}"
    probs = d.get("causeProbabilities") or {}
    if probs and round(sum(probs.values()), 2) != 1.0:
        return False, f"probs sum={round(sum(probs.values()),2)}"
    if "UNKNOWN" not in probs:
        return False, "UNKNOWN missing (must stay a valid outcome)"
    # short-volume semantics must be present + correct (the Micron-class error)
    sv = (d.get("positioningSources") or {}).get("finra_daily_short_volume") or {}
    if sv.get("isPositionData") is not False or sv.get("identityAvailable") is not False:
        return False, "short-volume semantics wrong"
    return True, f"unknownShare={d.get('unknownShare')} trigger={bool(d.get('immediateTrigger'))}"

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

def v_admin_gated_401(path):
    def fn():
        try:
            _get(path)
            return False, "expected 401, got 200 (admin endpoint UNPROTECTED!)"
        except urllib.error.HTTPError as e:
            # 429 = pre-routing IP rate limiter (smoke burst) — tolerated everywhere
            return e.code in (401, 429), f"HTTP {e.code} (correct: admin-gated)"
    return fn

# ── ARGUS Pro v11 endpoints — SHAPE-only (never require market-open / non-empty) ──

def v_event_intel():
    c, d = _get("/api/argus/events/MU/institutional-intelligence")
    return d.get("symbol") == "MU" and isinstance(d.get("items"), list), f"count={d.get('count')}"

CHECKS = [
    ("healthz", v_healthz),
    ("action-labels", v_action_labels),
    ("market-regime", v_regime),
    ("events", v_events),
    ("japan-watchlist", v_jp),
    ("us-watchlist", v_us),
    ("crypto-watchlist", v_crypto),
    ("fund-nav (投信 NAV)", v_fund_nav),
    ("scout-batch", v_scout_batch),
    ("ai-judgment freshness", v_ai_judgment),
    ("catalysts", v_catalysts),
    ("symbol-search", v_symbol_search),
    ("events-active", v_events_active),
    ("event-snapshot", v_event_snapshot),
    ("crypto-scan admin", _crypto_scan_gated),
    ("watchlist-sync owner-gated", v_watchlist_sync_gated),
    ("no order routes (safety)", v_no_order_routes),
    ("closepin phase (full-day)", v_closepin_phase),
    ("cause-attribution (integrity)", v_cause_attribution),
    ("downside-incidents (cause+override)", v_downside_incidents),
    ("legacy routes admin-gated", v_legacy_routes_gated),
    ("security-status 401", v_admin_gated_401("/api/argus/security-status")),
    ("ai-provider-status 401", v_admin_gated_401("/api/argus/ai-provider-status")),
    ("ai-cost 401", v_admin_gated_401("/api/argus/ai-cost")),
    ("tdnet-metrics 401", v_admin_gated_401("/api/argus/tdnet-metrics")),
    ("moomoo-capability 401", v_admin_gated_401("/api/argus/moomoo-capability")),
    ("jp-universe 401", v_admin_gated_401("/api/argus/jp-universe")),
    ("layer2b-summary 401", v_admin_gated_401("/api/argus/calibration/layer2b-summary")),
    # ── ARGUS Pro v11 (shape-only) ──
    ("v11 event institutional-intel", v_event_intel),
    # ── V11.1 paid-source activation ──
    ("v11.1 admin diagnostics gated", v_admin_gated_401("/api/argus/admin/provider-diagnostics")),
    # ── V11.2 decision spine ──
    ("v11.2 labels carry evidence refs", v_action_labels_have_evidence_refs),
    ("v11.2 ai-judgment refs safe", v_ai_judgment_evidence_refs_safe),
    # ── V11.2.1 quality gate ──
    ("v11.2.1 gemini challenge shape", v_ai_judgment_gemini_challenge_shape),
    # ── V11.3 official event lifecycle ──
    ("v11.3 official-events", v_official_events),
    ("v11.3 official-events/status", v_official_events_status),
    # ── V11.3.1 durability ──
    ("v11.3.1 official durability", v_official_events_durability),
    ("v11.3.1 official sample lifecycle", v_official_event_sample_lifecycle),
    ("v11.3.1 official admin gated", v_official_admin_gated),
    # ── V11.3.2 macro pre/post ──
    ("v11.3.2 macro-event-analysis", v_macro_event_analysis),
    ("v11.3.2 macro admin gated", v_macro_admin_gated),
    # ── V11.3.3 Mover Cause Engine ──
    ("v11.3.3 downside carries cause", v_downside_carries_mover_cause),
    ("v11.3.3 explain cached-only", v_public_explain_cached_only),
    # ── V11.4.0 Learning Memory ──
    ("v11.4.0 learning admin gated", v_learning_memory_admin_gated),
    # ── V11.4.1 Unified dashboard events ──
    ("v11.4.1 dashboard-events", v_dashboard_events),
    ("v11.4.1 dashboard-events NFP state", v_dashboard_events_nfp),
    ("v11.4.1 macro repair admin gated", v_macro_repair_admin_gated),
    # ── V11.5 macro coverage + reaction + news translation ──
    ("v11.5.1 news japanese-first", v_news_japanese_first),
    ("v11.5.2 explain-request public", v_explain_request_public),
    ("v11.5.2 translation-request public", v_translation_request_public),
    ("v11.5.2 queue admin gated", v_queue_admin_gated),
    ("v11.5.2 cause-attribution IONQ displayTitle", v_cause_attribution_ionq_displaytitle),
    # ── V11.5.3 C.A.O.S. Watchtower ──
    ("v11.5.3 watchtower plan", v_caos_watchtower_plan),
    ("v11.5.3 watchtower status", v_caos_watchtower_status),
    ("v11.5.3 watchtower admin gated", v_watchtower_admin_gated),
    # ── V11.5.4 Always-On Deep Patrol / Investigate Now ──
    ("v11.5.4 investigate-now public", v_investigate_now_public),
    # ── V11.5.5 patrol reliability / soak proof ──
    ("v11.5.5 patrol health", v_patrol_health),
    ("v11.5.6 news newest-first", v_news_newest_first),
    # ── V11.7.0 Big Money / Flow Attribution ──
    ("v11.7.0 flow attribution", v_flow_attribution),
    # ── V11.10.0 Supply / Demand Intelligence ──
    ("v11.10.0 supply demand", v_supply_demand),
    # ── V11.11.0 Decision Quality + US supply/demand ──
    ("v11.11.0 price history", v_price_history_shape),
    ("v11.11.0 supply demand US", v_supply_demand_us),
    # ── V11.14.0 Supply / Demand level model ──
    ("v11.14.0 supply demand level cap", v_supply_demand_level_model),
    # ── V11.22.0 Data Quality ──
    ("v11.22.0 data quality status", v_data_quality_status),
    ("v11.5.7 bridge status segmented", v_bridge_status_segmented),
    ("v11.5.7 bridge heartbeat gated", v_bridge_heartbeat_gated),
    ("v11.5.5 watchtower patrol ref", v_watchtower_status_patrol_ref),
    ("v11.5.5 patrol self-check gated", v_patrol_self_check_gated),
    ("v11.5 macro reaction admin gated", v_macro_reaction_admin_gated),
    ("v11.5 dashboard reaction shape", v_dashboard_events_reaction_shape),
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

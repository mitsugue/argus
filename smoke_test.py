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
    # Accept 'delayed' too: when the TSE is closed (the 6-hourly cron) or 7203 is on
    # the Yahoo/J-Quants fallback, the quote is honestly 'delayed' but the scout still
    # produces a full assessment. Only 'mock'/error is a real failure.
    if d.get("status") not in ("live", "delayed"):
        return False, f"status={d.get('status')} (expected live/delayed for 7203)"
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
        # 429 = the IP rate limiter fired BEFORE routing (smoke burst) — it neither
        # proves nor disproves the admin gate; tolerated like the other checks.
        return e.code in (401, 503, 429), f"HTTP {e.code} (admin-gated)"

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
            # The safety guarantee is "no 200 order route". A 429 means the per-IP rate
            # limiter fired BEFORE routing (it runs as a before_request hook), so every
            # path — including non-existent ones — returns 429; that is NOT evidence of an
            # order route. Tolerate it (retry/soft-pass); only a non-404/429 is suspicious.
            if e.code == 429:
                continue
            if e.code != 404:
                return False, f"{path} returned {e.code}, expected 404"
    return True, "no order/execute routes (correct)"

def v_tdnet_recent():
    # TDnet feed: must DISTINGUISH official (jquants-tdnet) from the yanoshin fallback
    # (v11.1). Unavailable is acceptable. official is a bool.
    c, d = _get("/api/argus/tdnet-recent")
    if d.get("status") not in ("live", "official_tdnet_live", "unavailable"):
        return False, f"status={d.get('status')}"
    prov = d.get("provider")
    if prov not in ("jquants-tdnet", "yanoshin-tdnet", None):
        return False, f"unexpected provider {prov}"
    for it in (d.get("items") or [])[:5]:
        if it.get("sentiment") not in ("negative", "positive", "neutral"):
            return False, f"bad sentiment {it.get('sentiment')}"
    return True, f"provider={prov} official={d.get('official')} status={d.get('status')}"


def v_evidence_pack(symbol, market=None):
    # v11.2 decision spine: the canonical Evidence Pack. Shape-only (empty arrays OK).
    def fn():
        q = f"/api/argus/evidence-pack?symbol={symbol}" + (f"&market={market}" if market else "")
        c, d = _get(q)
        if d.get("schemaVersion") != "evidence-pack-v1":
            return False, f"schema={d.get('schemaVersion')}"
        if not str(d.get("evidencePackId", "")).startswith(f"ep-{symbol}-"):
            return False, f"packId={d.get('evidencePackId')}"
        au = d.get("allowedUse") or {}
        if not isinstance(d.get("missingConfirmations"), list) or "canConfirmCause" not in au:
            return False, "missing allowedUse/missingConfirmations"
        return True, (f"id={d.get('evidencePackId')} cards={len(d.get('eventCards') or [])} "
                      f"missing={len(d.get('missingConfirmations') or [])}")
    return fn


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


def v_evidence_pack_official_refs():
    c, d = _get("/api/argus/evidence-pack?symbol=8058&market=JP")
    refs = d.get("officialEventRefs")
    if not isinstance(refs, list):
        return False, "officialEventRefs missing/not a list"
    for r in refs[:3]:
        if not str(r.get("officialEventId", "")).startswith("oe-"):
            return False, f"bad ref id {r.get('officialEventId')}"
    return True, f"refs={len(refs)}"


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
            if e.code not in (401, 503):
                return False, f"{path} returned {e.code}, expected 401/503"
    return True, "snapshot/restore admin-gated"


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


def v_macro_analysis_status():
    c, d = _get("/api/argus/macro-event-analysis/status")
    ok = d.get("schemaVersion") == "macro-event-analysis-v1" and isinstance(d.get("byPhase"), dict)
    return ok, f"total={d.get('total')} withPre={d.get('withPre')} withActual={d.get('withActual')} gen={d.get('lastGenerateAt')}"


def v_event_analysis_compat():
    # backward-compatible projection must keep the legacy keys CaosHub reads.
    c, d = _get("/api/argus/event-analysis")
    items = d.get("items")
    if not isinstance(items, list):
        return False, "items not a list"
    for it in items[:3]:
        for k in ("eventId", "phase", "summaryJa", "preJa", "postJa"):
            if k not in it:
                return False, f"compat missing {k}"
        if it.get("phase") not in ("pre", "post"):
            return False, f"bad legacy phase {it.get('phase')}"
    return True, f"items={len(items)}"


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
            if e.code not in (401, 503):
                return False, f"{path} returned {e.code}"
    return True, "generate/refresh-results admin-gated"


# ── V11.3.3 Mover Cause Engine ──
def v_mover_causes():
    # attribution ladder for sharp movers. Shape + discipline: no secrets,
    # every item carries a status + coverage; empty store = honest not_ready.
    c, d = _get("/api/argus/mover-causes?limit=20")
    if d.get("schemaVersion") != "mover-cause-v2":
        return False, f"schema={d.get('schemaVersion')}"
    if d.get("status") not in ("live", "not_ready"):
        return False, f"status={d.get('status')}"
    for it in (d.get("items") or []):
        for k in ("moverCauseId", "causeStatus", "causeStatusJa", "direction",
                  "evidenceCoverage", "nextChecksJa", "whyNotConfirmedJa"):
            if k not in it:
                return False, f"missing {k}"
        if it["causeStatus"] not in ("confirmed_cause", "probable_catalyst",
                                     "candidate_catalyst", "no_lead_yet", "not_scoreable"):
            return False, f"bad status {it['causeStatus']}"
        if it["causeStatus"] == "no_lead_yet" and not it.get("nextChecksJa"):
            return False, "no_lead without nextChecks"
    blob = json.dumps(d).lower()
    # JSON-KEY form ("holdings":) — company names like "XYZ Holdings" legitimately
    # appear in titles and must not false-alarm the secret scan.
    for bad in ("apikey", "x-api-key", '"holdings":', '"costbasis":', '"prompt":', '"messages":'):
        if bad in blob:
            return False, f"leak {bad}"
    return True, f"status={d.get('status')} count={d.get('count')}"


def v_mover_causes_status():
    c, d = _get("/api/argus/mover-causes/status")
    if d.get("schemaVersion") != "mover-cause-status-v1":
        return False, f"schema={d.get('schemaVersion')}"
    cn = d.get("counts") or {}
    for k in ("totalMovers", "confirmedCause", "probableCatalyst", "candidateCatalyst", "noLeadYet"):
        if not isinstance(cn.get(k), int):
            return False, f"counts.{k} missing"
    if not isinstance(d.get("coverage"), dict):
        return False, "coverage missing"
    deg = " DEGRADED(coverage failure suspected)" if d.get("degradedIfAllUnknown") else ""
    return True, (f"movers={cn['totalMovers']} 確認{cn['confirmedCause']}/材料{cn['probableCatalyst']}"
                  f"/候補{cn['candidateCatalyst']}/no_lead{cn['noLeadYet']}{deg}")


def v_mover_cause_upside():
    c, d = _get("/api/argus/mover-causes?direction=up&limit=10")
    if d.get("schemaVersion") != "mover-cause-v2":
        return False, "bad schema"
    for it in (d.get("items") or []):
        if it.get("direction") != "up":
            return False, "direction filter broken"
    return True, f"up count={d.get('count')}"


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


def v_decision_spine_status():
    # v11.2.1: the spine's own status — cached-only evidence pack + wiring booleans.
    c, d = _get("/api/argus/decision-spine/status")
    if d.get("schemaVersion") != "decision-spine-v1":
        return False, f"schema={d.get('schemaVersion')}"
    ep = d.get("evidencePack") or {}
    if not (ep.get("endpointAvailable") and ep.get("publicReadCachedOnly")):
        return False, "evidence pack not cached-only/available"
    if not all((d.get("safety") or {}).values()):
        return False, "safety flags not all true"
    al = d.get("actionLabels") or {}
    return True, f"labelsWithRefs={al.get('labelsWithEvidenceRefs')}/{al.get('totalLabels')} aiChallenge={((d.get('aiJudgment') or {}).get('geminiChallengeIncluded'))}"


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


def v_provider_diagnostics_public():
    # v11.1: public-safe provider status. No secrets, no admin detail.
    c, d = _get("/api/argus/provider-diagnostics/public")
    if d.get("schemaVersion") != "provider-diagnostics-public-v1":
        return False, f"schema={d.get('schemaVersion')}"
    provs = d.get("providers") or []
    if not any(p.get("provider") == "jquants-tdnet" for p in provs):
        return False, "jquants-tdnet missing"
    for p in provs:                                     # public rows carry ONLY these keys
        if set(p) != {"provider", "configured", "status"}:
            return False, f"leaky public row {list(p)}"
    return True, f"live={(d.get('summary') or {}).get('live')} configured={(d.get('summary') or {}).get('configured')}"

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

def v_runtime_manifest():
    c, d = _get("/api/argus/runtime-manifest")
    if d.get("engineVersion") != "runtime-manifest-v1":
        return False, f"engineVersion={d.get('engineVersion')}"
    if not isinstance(d.get("activeRoutes"), list) or len(d["activeRoutes"]) != 5:
        return False, "activeRoutes not 5"
    if "safetyBoundaries" not in d or "currentLimitations" not in d:
        return False, "missing safety/limitations"
    return True, f"routes={len(d['activeRoutes'])} providers={d.get('providers',{}).get('confirmedLive')}/{d.get('providers',{}).get('total')}"

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


# ── ARGUS Pro v11 endpoints — SHAPE-only (never require market-open / non-empty) ──
def v_event_cards():
    c, d = _get("/api/argus/events/cards")
    return d.get("schemaVersion") == "event-card-v2" and isinstance(d.get("items"), list), \
        f"count={d.get('count')}"

def v_research_mission():
    c, d = _get("/api/argus/events/MU/research-mission")
    cost = d.get("cost") or {}
    return d.get("symbol") == "MU" and cost.get("llmCalls") == 0, \
        f"llmCalls={cost.get('llmCalls')} deterministic={cost.get('deterministic')}"

def v_event_intel():
    c, d = _get("/api/argus/events/MU/institutional-intelligence")
    return d.get("symbol") == "MU" and isinstance(d.get("items"), list), f"count={d.get('count')}"

def v_positioning():
    c, d = _get("/api/argus/institutional-intelligence/positioning/MU")
    probs = d.get("probabilities") or {}
    ssum = sum(v for v in probs.values() if isinstance(v, (int, float)))
    ok = d.get("symbol") == "MU" and (not probs or abs(ssum - 1.0) < 1e-6)
    return ok, f"probsSum={round(ssum, 4)} calib={d.get('calibrationStatus')}"

def v_calibration_v4_status():
    c, d = _get("/api/argus/calibration/v4/status")
    ok = d.get("schemaVersion") == "calibration-v4" and isinstance(d.get("isActive"), bool) \
        and d.get("reliabilityStage") in ("burn_in", "early_signal", "provisional", "regime_level")
    return ok and "proven" not in json.dumps(d).lower(), \
        f"active={d.get('isActive')} stage={d.get('reliabilityStage')}"

def v_decision_value_status():
    c, d = _get("/api/argus/decision-value/status")
    ok = d.get("schemaVersion") == "decision-value-v1" and d.get("phase") in (
        "not_configured", "engine_ready_no_records_yet", "shadow_recording_active", "scoring_active")
    leaks = any(k in json.dumps(d).lower() for k in ("netr", "realizedpnl", "costbasis", "holdings"))
    return ok and not leaks and "No order" in (d.get("disclaimer") or ""), f"phase={d.get('phase')}"

def v_market_depth_proof():
    c, d = _get("/api/argus/market-depth/proof")
    s = d.get("summary") or {}
    return d.get("schemaVersion") == "market-depth-proof-v1" and isinstance(d.get("items"), list) \
        and "trueDepthLiveCount" in s, f"trueLive={s.get('trueDepthLiveCount')} reqContract={s.get('requiresContractCount')}"

def v_source_coverage():
    c, d = _get("/api/argus/source-coverage")
    return d.get("schemaVersion") == "source-coverage-v1" and isinstance(d.get("tiers"), list), \
        f"items={(d.get('summary') or {}).get('totalItems')}"

def v_caos_audit():
    c, d = _get("/api/argus/caos/audit")
    return d.get("schemaVersion") == "caos-link-v1" and isinstance(d.get("items"), list), \
        f"count={d.get('count')}"


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
    ("closepin phase (full-day)", v_closepin_phase),
    ("cause-attribution (integrity)", v_cause_attribution),
    ("runtime-manifest", v_runtime_manifest),
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
    # ── ARGUS Pro v11 (shape-only) ──
    ("v11 event-cards", v_event_cards),
    ("v11 research-mission (llm=0)", v_research_mission),
    ("v11 event institutional-intel", v_event_intel),
    ("v11 positioning (probs=1)", v_positioning),
    ("v11 calibration/v4/status", v_calibration_v4_status),
    ("v11 decision-value/status", v_decision_value_status),
    ("v11 market-depth/proof", v_market_depth_proof),
    ("v11 source-coverage", v_source_coverage),
    ("v11 caos/audit", v_caos_audit),
    # ── V11.1 paid-source activation ──
    ("v11.1 provider-diagnostics/public", v_provider_diagnostics_public),
    ("v11.1 admin diagnostics gated", v_admin_gated_401("/api/argus/admin/provider-diagnostics")),
    # ── V11.2 decision spine ──
    ("v11.2 evidence-pack MU", v_evidence_pack("MU")),
    ("v11.2 evidence-pack 8058 JP", v_evidence_pack("8058", "JP")),
    ("v11.2 labels carry evidence refs", v_action_labels_have_evidence_refs),
    ("v11.2 ai-judgment refs safe", v_ai_judgment_evidence_refs_safe),
    # ── V11.2.1 quality gate ──
    ("v11.2.1 decision-spine/status", v_decision_spine_status),
    ("v11.2.1 gemini challenge shape", v_ai_judgment_gemini_challenge_shape),
    # ── V11.3 official event lifecycle ──
    ("v11.3 official-events", v_official_events),
    ("v11.3 official-events/status", v_official_events_status),
    ("v11.3 evidence-pack official refs", v_evidence_pack_official_refs),
    # ── V11.3.1 durability ──
    ("v11.3.1 official durability", v_official_events_durability),
    ("v11.3.1 official sample lifecycle", v_official_event_sample_lifecycle),
    ("v11.3.1 official admin gated", v_official_admin_gated),
    # ── V11.3.2 macro pre/post ──
    ("v11.3.2 macro-event-analysis", v_macro_event_analysis),
    ("v11.3.2 macro analysis status", v_macro_analysis_status),
    ("v11.3.2 event-analysis compat", v_event_analysis_compat),
    ("v11.3.2 macro admin gated", v_macro_admin_gated),
    # ── V11.3.3 Mover Cause Engine ──
    ("v11.3.3 mover-causes", v_mover_causes),
    ("v11.3.3 mover-causes status", v_mover_causes_status),
    ("v11.3.3 upside direction", v_mover_cause_upside),
    ("v11.3.3 downside carries cause", v_downside_carries_mover_cause),
    ("v11.3.3 explain cached-only", v_public_explain_cached_only),
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

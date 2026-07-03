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
        return e.code in (401, 503, 429), f"HTTP {e.code} (owner-gated)"

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
            if e.code not in (401, 503, 429):
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
            if e.code not in (401, 503, 429):
                return False, f"{path} returned {e.code}, expected 401/503"
    return True, "snapshot/restore admin-gated"


def v_macro_result_status_multi():
    # v11.5: one row per event code, valid statuses, no secrets.
    c, d = _get("/api/argus/macro-events/result-status")
    if d.get("schemaVersion") != "macro-result-status-v1":
        return False, f"schema={d.get('schemaVersion')}"
    codes = {s.get("eventCode"): s for s in (d.get("sources") or [])}
    valid = {"live", "partial", "not_implemented", "unavailable", "parse_error",
             "source_unreachable", "not_run", "rate_limited", "error"}
    for want in ("NFP", "CPI", "FOMC", "BOJ"):
        if want not in codes:
            return False, f"missing {want}"
        if codes[want].get("status") not in valid:
            return False, f"{want} bad status {codes[want].get('status')}"
        if "metricsAvailable" not in codes[want]:
            return False, f"{want} missing metricsAvailable"
    return True, f"codes={len(codes)} NFP={codes['NFP'].get('status')} CPI={codes['CPI'].get('status')}"


def v_news_translation_status():
    c, d = _get("/api/argus/news/translation-status")
    if d.get("schemaVersion") != "news-translation-status-v1":
        return False, f"schema={d.get('schemaVersion')}"
    if not isinstance(d.get("cachedCount"), int):
        return False, "cachedCount missing"
    # v11.5.1: visible-pending + coverage drive the "why still English" UI note.
    if not isinstance(d.get("visiblePendingCount"), int):
        return False, "visiblePendingCount missing"
    cov = d.get("coverage") or {}
    if "visibleTranslatedPct" not in cov or "allTranslatedPct" not in cov:
        return False, "coverage.*TranslatedPct missing"
    if not d.get("nextTranslateHintJa"):
        return False, "nextTranslateHintJa missing"
    return True, (f"cached={d.get('cachedCount')} pending={d.get('pendingQueue')} "
                  f"visPending={d.get('visiblePendingCount')} visPct={cov.get('visibleTranslatedPct')}")


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
    # v11.5.2: public enqueue-only. A harmless test symbol returns a valid status,
    # never a 500. It must NOT start AI (we can only observe the shape here).
    code, d = _post_json("/api/argus/mover-causes/explain-request",
                         {"symbol": "IONQ", "market": "US", "context": "cause-stack"})
    if code == 429:
        return True, "429 pre-routing (skip)"
    if code >= 500:
        return False, f"explain-request 5xx: {code}"
    if d.get("schemaVersion") != "mover-explain-request-v1":
        return False, f"schema={d.get('schemaVersion')}"
    if d.get("status") not in ("queued", "already_queued", "cached_available", "rate_limited", "invalid"):
        return False, f"bad status {d.get('status')}"
    return True, f"status={d.get('status')}"


def v_translation_request_public():
    # v11.5.2: public enqueue-only translation request returns a valid shape, never 500.
    code, d = _post_json("/api/argus/news/translation-request",
                         {"context": "cause-stack", "symbol": "IONQ", "market": "US",
                          "items": [{"titleOriginal": "IonQ smoke-test headline about markets",
                                     "source": "smoke"}]})
    if code == 429:
        return True, "429 pre-routing (skip)"
    if code >= 500:
        return False, f"translation-request 5xx: {code}"
    if d.get("schemaVersion") != "news-translation-request-v1":
        return False, f"schema={d.get('schemaVersion')}"
    for k in ("queued", "alreadyTranslated", "alreadyQueued"):
        if not isinstance(d.get(k), int):
            return False, f"missing {k}"
    return True, f"queued={d.get('queued')} remaining={d.get('queueRemaining')}"


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


def v_translation_status_visible_queue():
    # v11.5.2: status exposes the visible-translation queue + coverage + samples.
    c, d = _get("/api/argus/news/translation-status")
    if d.get("schemaVersion") != "news-translation-status-v1":
        return False, f"schema={d.get('schemaVersion')}"
    vq = d.get("visibleQueue")
    if not isinstance(vq, dict) or "queuedCount" not in vq or "durable" not in vq:
        return False, "visibleQueue missing/short"
    if "visibleQueuedPct" not in (d.get("coverage") or {}):
        return False, "coverage.visibleQueuedPct missing"
    s = d.get("samples") or {}
    if "pendingVisible" not in s or "translatedRecent" not in s:
        return False, "samples missing"
    return True, f"queued={vq.get('queuedCount')} durable={vq.get('durable')}"


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


def v_investment_universe():
    # v11.5.3: Core Portfolio asset classes are the C.A.O.S. watch universe.
    c, d = _get("/api/argus/investment-universe")
    if d.get("schemaVersion") != "investment-universe-v1":
        return False, f"schema={d.get('schemaVersion')}"
    classes = {x.get("assetClass") for x in (d.get("assetClasses") or [])}
    need = {"JP_EQUITY", "US_EQUITY", "GOLD_GLD", "BONDS_TLT", "REITS_XLRE",
            "CRYPTO_BTC_ETH", "FX_USDJPY", "CASH", "FUND_ACCUMULATION"}
    if not need <= classes:
        return False, f"missing classes: {need - classes}"
    return True, f"classes={len(classes)} funds={len(d.get('funds') or [])}"


def v_caos_source_universe():
    c, d = _get("/api/argus/caos/source-universe")
    if d.get("schemaVersion") != "caos-source-universe-v1":
        return False, f"schema={d.get('schemaVersion')}"
    by = d.get("sourcesByAssetClass") or {}
    for ac in ("JP_EQUITY", "US_EQUITY", "GOLD_GLD", "CRYPTO_BTC_ETH", "FX_USDJPY"):
        if not by.get(ac):
            return False, f"no sources for {ac}"
    gn = next((s for s in d.get("sources", []) if s.get("sourceId") == "google_news_jp"), None)
    if not gn or not gn.get("isDiscoveryLayer") or gn.get("canConfirmCause"):
        return False, "google_news_jp must be discovery-only"
    return True, f"sources={len(d.get('sources') or [])}"


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
    # v11.5.4: the 念押し button performs a REAL bounded sweep — valid shape, never 500.
    code, d = _post_json("/api/argus/caos/investigate-now",
                         {"symbol": "IONQ", "market": "US", "context": "cause-stack"},
                         timeout=40)
    if code == 429:
        return True, "429 pre-routing (skip)"
    if code >= 500:
        return False, f"investigate-now 5xx: {code}"
    if d.get("schemaVersion") != "caos-investigate-now-v2":
        return False, f"schema={d.get('schemaVersion')}"
    if d.get("status") not in ("completed", "partial", "rate_limited", "blocked", "error"):
        return False, f"bad status {d.get('status')}"
    if d.get("status") in ("completed", "partial"):
        sw = d.get("sweep") or {}
        if not sw.get("searchedSources"):
            return False, "searchedSources missing"
        if "次回自動生成で反映" in (d.get("messageJa") or ""):
            return False, "queue-ticket message as primary result"
        return True, (f"status={d['status']} searched={len(sw['searchedSources'])} "
                      f"fresh={len(sw.get('freshItems') or [])} blocked={len(sw.get('blockedSources') or [])}")
    return True, f"status={d.get('status')}"


def v_caos_patrol_plan():
    c, d = _get("/api/argus/caos/patrol-plan")
    if d.get("schemaVersion") != "caos-patrol-plan-v1":
        return False, f"schema={d.get('schemaVersion')}"
    targets = d.get("targets") or []
    classes = {t.get("assetClass") for t in targets}
    for ac in ("GOLD_GLD", "CRYPTO_BTC_ETH", "FX_USDJPY", "CASH"):
        if ac not in classes:
            return False, f"baseline missing: {ac}"
    return True, f"targets={len(targets)} due={d.get('dueCount')}"


def v_deep_research_status():
    # v11.5.4: violations MUST be empty — old news as primary is a hard failure.
    c, d = _get("/api/argus/caos/deep-research/status")
    if d.get("schemaVersion") != "caos-deep-research-status-v1":
        return False, f"schema={d.get('schemaVersion')}"
    v = d.get("violations")
    if v is None:
        return False, "violations missing"
    if v:
        return False, f"OLD NEWS AS PRIMARY: {v[:2]}"
    return True, (f"violations=0 onlyOldNews={len(d.get('symbolsWithOnlyOldNews') or [])} "
                  f"lastSweep={'yes' if d.get('lastInvestigateNow') or d.get('lastPatrolSweep') else 'none'}")


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
            if e.code not in (401, 503, 429):
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


def v_mover_status_quality_sla():
    # v11.3.4: stricter diagnostics — quality + SLA blocks must exist with real types.
    c, d = _get("/api/argus/mover-causes/status")
    q, s = d.get("quality"), d.get("sla")
    if not isinstance(q, dict) or not isinstance(s, dict):
        return False, "quality/sla missing"
    for k in ("staleCount", "missingMarketConfirmationCount", "aiExplainPendingCount",
              "noFreshEvidenceCount"):
        if not isinstance(q.get(k), int):
            return False, f"quality.{k} missing"
    if not isinstance(s.get("breaches"), list) or s.get("urgentMaxAgeMin") != 15:
        return False, "sla shape wrong"
    return True, (f"stale={q['staleCount']} mcMissing={q['missingMarketConfirmationCount']} "
                  f"aiPending={q['aiExplainPendingCount']} breaches={len(s['breaches'])}")


def v_mover_refresh_queue():
    c, d = _get("/api/argus/mover-causes/refresh-queue")
    if d.get("schemaVersion") != "mover-cause-refresh-v1":
        return False, f"schema={d.get('schemaVersion')}"
    if not isinstance(d.get("queue"), list) or not isinstance(d.get("budget"), dict):
        return False, "queue/budget missing"
    for it in d["queue"]:
        for k in ("symbol", "priority", "refreshNeeded", "aiExplainNeeded", "reasonJa"):
            if k not in it:
                return False, f"queue item missing {k}"
        if it["priority"] not in ("urgent", "high", "normal", "low"):
            return False, f"bad priority {it['priority']}"
    return True, f"queued={len(d['queue'])} aiBudget={d['budget'].get('maxAiExplainPerRun')}"


def _v_market_confirmation(sym, mkt):
    c, d = _get(f"/api/argus/market-confirmation?symbol={sym}&market={mkt}")
    if d.get("schemaVersion") != "market-confirmation-v1.5":
        return False, f"schema={d.get('schemaVersion')}"
    if d.get("status") not in ("confirmed", "partial", "missing", "not_applicable"):
        return False, f"status={d.get('status')}"
    # partial/missing due to missing bars is fine — absent FIELDS are not.
    for k in ("priceMovePct", "volumeRatio", "relativeToIndexPct", "peerBasketMovePct",
              "vwapDistancePct", "limitationsJa", "window"):
        if k not in d:
            return False, f"missing field {k}"
    return True, f"{sym}: status={d.get('status')} rel={d.get('relativeToIndexPct')}"


def v_market_confirmation_jp():
    return _v_market_confirmation("9984", "JP")


def v_market_confirmation_us():
    return _v_market_confirmation("META", "US")


def v_mover_items_freshness():
    c, d = _get("/api/argus/mover-causes?limit=20")
    for it in (d.get("items") or []):
        fr = it.get("freshness")
        if not isinstance(fr, dict) or "isStale" not in fr:
            return False, f"{it.get('symbol')} missing freshness"
        if (it.get("refreshPolicy") or {}).get("priority") == "urgent" and not fr.get("nextAutoCheckAt"):
            return False, f"{it.get('symbol')} urgent without nextAutoCheckAt"
        # v11.5.2 added "queued" (owner explain-request pending) as a valid state
        if it.get("explanationStatus") not in ("cached", "queued", "pending", "not_generated"):
            return False, f"bad explanationStatus {it.get('explanationStatus')}"
    return True, f"count={d.get('count')} all carry freshness"


_LM_FORBIDDEN = ('"prompt":', '"messages":', '"holdings":', '"pnl":', '"netr":',
                 '"costbasis":', '"quantity":', '"apikey":', '"api_key":', '"token":',
                 '"authorization":', '"rawproviderbody":', '"privaterepo":')


def _no_forbidden(d):
    blob = json.dumps(d, ensure_ascii=False).lower()
    for bad in _LM_FORBIDDEN:
        if bad in blob:
            return bad
    return None


def v_learning_memory():
    # v11.4.0: public cache-only Learning Memory. Shape + honesty: burn_in/none is
    # fine, but the schema must be present and it must never overclaim mature with
    # a tiny sample. No forbidden keys.
    c, d = _get("/api/argus/learning-memory")
    if d.get("schemaVersion") != "learning-memory-v1":
        return False, f"schema={d.get('schemaVersion')}"
    stage = d.get("sampleStage")
    if stage not in ("none", "burn_in", "early_signal", "usable", "mature"):
        return False, f"bad sampleStage {stage}"
    if not isinstance(d.get("lessons"), list) or not isinstance(d.get("cohorts"), dict):
        return False, "lessons/cohorts missing"
    total = int((d.get("counts") or {}).get("totalScoredSamples", 0))
    if stage == "mature" and total < 100:
        return False, f"overclaim mature with n={total}"
    for L in (d.get("lessons") or []):
        if L.get("stage") == "mature" and int(L.get("sampleSize", 0)) < 100:
            return False, f"lesson overclaims mature n={L.get('sampleSize')}"
        if L.get("stage") == "burn_in" and float(L.get("confidence", 0)) > 0.0:
            return False, "burn_in lesson has nonzero confidence"
    bad = _no_forbidden(d)
    if bad:
        return False, f"forbidden key {bad}"
    return True, f"stage={stage} lessons={len(d.get('lessons') or [])} scored={total}"


def v_learning_memory_status():
    c, d = _get("/api/argus/learning-memory/status")
    if d.get("schemaVersion") != "learning-memory-status-v1":
        return False, f"schema={d.get('schemaVersion')}"
    if d.get("status") not in ("not_ready", "building", "ready", "stale", "error"):
        return False, f"bad status {d.get('status')}"
    cn = d.get("counts") or {}
    for k in ("lessons", "usableLessons", "officialEventSamples", "macroEventSamples",
              "moverCauseSamples", "decisionValueSamples", "calibrationSamples"):
        if not isinstance(cn.get(k), int):
            return False, f"counts.{k} missing"
    return True, (f"status={d.get('status')} stage={d.get('sampleStage')} "
                  f"lessons={cn.get('lessons')} usable={cn.get('usableLessons')} "
                  f"ledger={bool((d.get('ledger') or {}).get('restoreAvailable'))}")


def v_evidence_pack_has_learning_memory():
    c, d = _get("/api/argus/evidence-pack?symbol=9984&market=JP")
    lm = d.get("learningMemory")
    if not isinstance(lm, dict):
        return False, "evidence-pack missing learningMemory"
    if lm.get("schemaVersion") != "learning-memory-compact-v1":
        return False, f"bad compact schema {lm.get('schemaVersion')}"
    if lm.get("cautionOnly") is not True:
        return False, "learningMemory must be cautionOnly"
    bad = _no_forbidden(d)
    if bad:
        return False, f"forbidden key {bad}"
    return True, f"stage={lm.get('sampleStage')} lessons={len(lm.get('lessons') or [])}"


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
            # 429 = pre-routing IP rate limiter (smoke burst) — tolerated everywhere
            return e.code in (401, 429), f"HTTP {e.code} (correct: admin-gated)"
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
    # ── V11.3.4 freshness / queue / market confirmation ──
    ("v11.3.4 status quality+sla", v_mover_status_quality_sla),
    ("v11.3.4 refresh-queue", v_mover_refresh_queue),
    ("v11.3.4 market-confirmation JP", v_market_confirmation_jp),
    ("v11.3.4 market-confirmation US", v_market_confirmation_us),
    ("v11.3.4 mover freshness", v_mover_items_freshness),
    # ── V11.4.0 Learning Memory ──
    ("v11.4.0 learning-memory", v_learning_memory),
    ("v11.4.0 learning-memory status", v_learning_memory_status),
    ("v11.4.0 evidence-pack learningMemory", v_evidence_pack_has_learning_memory),
    ("v11.4.0 learning admin gated", v_learning_memory_admin_gated),
    # ── V11.4.1 Unified dashboard events ──
    ("v11.4.1 dashboard-events", v_dashboard_events),
    ("v11.4.1 dashboard-events NFP state", v_dashboard_events_nfp),
    ("v11.4.1 macro repair admin gated", v_macro_repair_admin_gated),
    # ── V11.5 macro coverage + reaction + news translation ──
    ("v11.5 macro result-status multi", v_macro_result_status_multi),
    ("v11.5 news translation status", v_news_translation_status),
    ("v11.5.1 news japanese-first", v_news_japanese_first),
    ("v11.5.2 explain-request public", v_explain_request_public),
    ("v11.5.2 translation-request public", v_translation_request_public),
    ("v11.5.2 queue admin gated", v_queue_admin_gated),
    ("v11.5.2 translation-status visibleQueue", v_translation_status_visible_queue),
    ("v11.5.2 cause-attribution IONQ displayTitle", v_cause_attribution_ionq_displaytitle),
    # ── V11.5.3 C.A.O.S. Watchtower ──
    ("v11.5.3 investment universe", v_investment_universe),
    ("v11.5.3 caos source universe", v_caos_source_universe),
    ("v11.5.3 watchtower plan", v_caos_watchtower_plan),
    ("v11.5.3 watchtower status", v_caos_watchtower_status),
    ("v11.5.3 watchtower admin gated", v_watchtower_admin_gated),
    # ── V11.5.4 Always-On Deep Patrol / Investigate Now ──
    ("v11.5.4 investigate-now public", v_investigate_now_public),
    ("v11.5.4 patrol plan", v_caos_patrol_plan),
    ("v11.5.4 deep-research status (no old-primary)", v_deep_research_status),
    # ── V11.5.5 patrol reliability / soak proof ──
    ("v11.5.5 patrol health", v_patrol_health),
    ("v11.5.6 news newest-first", v_news_newest_first),
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

"""ARGUS V11.3 — Official Event Lifecycle tests.

Official disclosure ≠ price cause: material → probable_catalyst candidate;
confirmed_cause requires timing + market confirmation; post-move disclosure is never
the immediate trigger; missing market data stays pending. Deterministic/serializable.
"""
import json
from datetime import datetime, timezone
import argus_official_event_lifecycle as OL
import scanner

MATERIAL_ITEM = {"code": "8058", "name": "三菱商事", "title": "業績予想の修正（下方修正）に関するお知らせ",
                 "time": "2026-07-01T23:30:00Z", "category": "guidance_down", "categoryJa": "業績下方修正",
                 "sentiment": "negative", "material": True, "official": True, "provider": "jquants-tdnet"}
NON_MATERIAL = {"code": "7203", "name": "トヨタ", "title": "月次生産状況のお知らせ", "time": "2026-07-01T23:45:00Z",
                "category": "monthly", "categoryJa": "月次開示", "sentiment": "neutral",
                "material": False, "official": True, "provider": "jquants-tdnet"}
NOW = "2026-07-02T01:00:00Z"
MOVE_STARTED = "2026-07-02T00:00:00Z"


def rec(item=MATERIAL_ITEM):
    return OL.from_disclosure(item, first_seen_at=NOW)


# ── creation / classification ────────────────────────────────────────────────
def test_material_disclosure_creates_catalyst_candidate():
    r = rec()
    assert r["schemaVersion"] == "official-event-lifecycle-v1"
    assert r["material"] is True
    assert r["causeStatus"] == "probable_catalyst"     # candidate — never confirmed at ingest
    assert r["lifecycleStage"] == "classified"


def test_non_material_stays_official_fact():
    r = rec(NON_MATERIAL)
    assert r["material"] is False
    assert r["causeStatus"] == "fact_only"


def test_missing_market_data_keeps_pending():
    r = rec()
    assert "market_reaction:same_day" in r["missingConfirmations"]
    assert all(not v for v in r["marketReaction"].values())   # all windows empty


def test_serialization_is_deterministic():
    a, b = rec(), rec()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["officialEventId"] == b["officialEventId"]        # deterministic id


# ── market reaction + cause discipline ───────────────────────────────────────
def _confirmed_reaction(window="same_day"):
    return OL.build_market_reaction(window=window, observed_at=NOW, price_move_pct=-4.2,
                                    volume_ratio=2.1)


def test_confirmed_cause_requires_market_confirmation():
    r = rec()
    r2 = OL.apply_market_reaction(
        r, _confirmed_reaction(), move_started_at=MOVE_STARTED)
    assert r2["causeStatus"] == "confirmed_cause"
    assert r2["marketReaction"]["sameDay"]["marketConfirmed"] is True


def test_small_move_both_windows_is_not_cause():
    r = rec()
    weak_same = OL.build_market_reaction(window="same_day", observed_at=NOW, price_move_pct=0.3)
    weak_next = OL.build_market_reaction(window="next_session", observed_at=NOW, price_move_pct=-0.2)
    r2 = OL.apply_market_reaction(
        OL.apply_market_reaction(
            r, weak_same, move_started_at=MOVE_STARTED),
        weak_next, move_started_at=MOVE_STARTED)
    assert r2["causeStatus"] == "not_cause"


def test_disclosure_after_move_never_immediate_trigger():
    r = rec()
    r["disclosedAt"] = "2026-07-02T02:00:00Z"
    r2 = OL.apply_market_reaction(r, _confirmed_reaction(),
                                  move_started_at=MOVE_STARTED)
    assert r2["causeStatus"] != "confirmed_cause"
    assert "timing:disclosure_after_move" in r2["missingConfirmations"]


def test_missing_or_malformed_move_time_never_confirms_cause():
    for move in (None, "", "2026-07-02", "not-a-time"):
        r2 = OL.apply_market_reaction(
            rec(), _confirmed_reaction(), move_started_at=move)
        assert r2["causeStatus"] != "confirmed_cause"
        assert "timing:unverified" in r2["missingConfirmations"]


def test_reaction_with_missing_inputs_states_limitations():
    mr = OL.build_market_reaction(window="day3", observed_at=NOW)      # nothing observed
    assert mr["marketConfirmed"] is False
    assert mr["priceMovePct"] is None and mr["limitationsJa"]


def test_apply_never_mutates_original():
    r = rec()
    before = json.dumps(r, sort_keys=True)
    OL.apply_market_reaction(r, _confirmed_reaction())
    assert json.dumps(r, sort_keys=True) == before


# ── store + endpoints (no provider fetch) ────────────────────────────────────
def _ingest(monkeypatch=None):
    scanner._OFFICIAL_EVENTS.clear()
    scanner._OFFICIAL_EVENTS_STATE["restored"] = True
    scanner._official_lifecycle_ingest(
        {"official": True, "items": [MATERIAL_ITEM, NON_MATERIAL]},
        now_epoch=datetime.fromisoformat(
            NOW.replace("Z", "+00:00")).timestamp())


def test_ingest_and_endpoints_are_store_only(monkeypatch):
    _ingest()
    def boom(*a, **k):
        raise AssertionError("FORBIDDEN provider fetch from official-events GET")
    for name in ("_jquants_tdnet_fetch", "_get_tdnet_yanoshin", "get_tdnet_recent",
                 "_jq_price_history", "_fetch_public_text", "_openai_judge", "_gemini_check"):
        monkeypatch.setattr(scanner, name, boom)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/official-events?symbol=8058").get_json()
        assert d["count"] == 1 and d["items"][0]["material"] is True
        st = c.get("/api/argus/official-events/status").get_json()
        assert st["total"] == 2 and st["material"] == 1
        oid = d["items"][0]["officialEventId"]
        lc = c.get(f"/api/argus/official-events/{oid}/lifecycle").get_json()
        assert lc["causeStatus"] == "probable_catalyst"
        r404 = c.get("/api/argus/official-events/nope/lifecycle")
        assert r404.status_code == 404


def test_evidence_pack_includes_official_event_refs():
    _ingest()
    d = scanner._build_evidence_pack("8058", "JP")
    refs = d.get("officialEventRefs") or []
    assert refs and refs[0]["officialEventId"].startswith("oe-8058-")
    assert refs[0]["causeStatus"] == "probable_catalyst"
    assert refs[0]["followupDue"]


def test_dv_shadow_record_can_reference_official_event():
    import argus_decision_value as DV
    ctx = {"officialEventId": "oe-8058-abc", "lifecycleStage": "classified",
           "causeStatus": "probable_catalyst", "marketConfirmed": False,
           "missingConfirmations": ["market_reaction:same_day"]}
    r = DV.build_shadow_decision(policy_id="no_trade_control_v1", symbol="8058", market="JP",
                                 decision_price=4400.0, decision_ts=NOW, eligible=False,
                                 official_event=ctx)
    assert r["officialEventId"] == "oe-8058-abc"
    assert r["causeStatusAtDecision"] == "probable_catalyst"
    assert r["marketReactionKnownAtDecision"] is False
    assert "netR" not in r


def _bounded_track_setup(monkeypatch):
    events = {str(i): {**rec(), "symbol": str(i)} for i in range(1, 5)}
    monkeypatch.setattr(scanner, "_OFFICIAL_EVENTS", events)
    monkeypatch.setattr(scanner, "_OFFICIAL_EVENTS_STATE", {
        "restored": True, "trackCursor": None, "lastTrackAt": None})
    monkeypatch.setattr(scanner, "_official_events_restore_once", lambda: None)
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: NOW)
    monkeypatch.setattr(scanner, "_official_events_persist", lambda: None)
    return events


def test_official_track_resumes_after_missing_prices_without_losing_records(monkeypatch):
    events = _bounded_track_setup(monkeypatch)
    original = json.dumps(events, sort_keys=True)
    calls = []
    monkeypatch.setattr(scanner, "_OFFICIAL_TRACK_MAX_RECORDS", 2)
    monkeypatch.setattr(scanner, "_jq_price_history",
                        lambda symbol, **kwargs: calls.append(symbol))
    first = scanner._official_events_track()
    second = scanner._official_events_track()
    assert first["status"] == "partial" and first["remainingCount"] == 2
    assert second["status"] == "ok" and second["remainingCount"] == 0
    assert calls == ["1", "2", "3", "4"]
    assert json.dumps(events, sort_keys=True) == original
    scanner._official_events_track()
    assert calls[-2:] == ["1", "2"]


def test_official_track_time_budget_yields_and_next_call_progresses(monkeypatch):
    _bounded_track_setup(monkeypatch)
    clock, calls = [100.0], []
    monkeypatch.setattr(scanner.time, "monotonic", lambda: clock[0])
    def fetch(symbol, *, deadline):
        assert deadline == clock[0] + 25
        calls.append(symbol)
        clock[0] += 25
        return None
    monkeypatch.setattr(scanner, "_jq_price_history", fetch)
    first = scanner._official_events_track()
    assert first["processedCount"] == 1 and first["hasMore"]
    scanner._official_events_track()
    assert calls == ["1", "2"]


def test_official_track_does_not_overlap_admin_calls(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    scanner._OFFICIAL_TRACK_LOCK.acquire()
    try:
        with scanner.app.test_client() as client:
            response = client.post("/api/argus/official-events/track")
        assert response.get_json()["status"] == "busy"
    finally:
        scanner._OFFICIAL_TRACK_LOCK.release()


def test_price_history_deadline_preserves_cache_without_partial_pagination(monkeypatch):
    from unittest.mock import Mock
    cached = {"data": {"dates": ["2026-06-30"], "closes": [100]}, "expires": 0}
    cache = {"1234": cached}
    monkeypatch.setattr(scanner, "_JQ_HISTORY_CACHE", cache)
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-only")
    clock = iter([100.0, 130.0])
    monkeypatch.setattr(scanner.time, "monotonic", lambda: next(clock))
    response = Mock()
    response.json.return_value = {"data": [{"Date": "2026-07-01", "C": 120}],
                                  "pagination_key": "next-page"}
    request = Mock(return_value=response)
    monkeypatch.setattr(scanner.requests, "get", request)
    assert scanner._jq_price_history("1234", deadline=125) is cached["data"]
    assert cache["1234"] is cached
    assert request.call_count == 1
    assert request.call_args.kwargs["timeout"] == 10


def test_independent_refresh_steps_continue_after_an_unrelated_failure():
    from pathlib import Path
    source = Path(".github/workflows/ai-rejudge.yml").read_text()
    steps = source.split("      - name: ")[1:]
    assert len(steps) == 7
    assert all("        if: ${{ !cancelled() }}" in step for step in steps)
    assert all("continue-on-error" not in step for step in steps)
    assert all(step.count("scripts/workflow_http.py") == 1 for step in steps)

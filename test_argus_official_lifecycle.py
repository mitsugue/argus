"""ARGUS V11.3 — Official Event Lifecycle tests.

Official disclosure ≠ price cause: material → probable_catalyst candidate;
confirmed_cause requires timing + market confirmation; post-move disclosure is never
the immediate trigger; missing market data stays pending. Deterministic/serializable.
"""
import json
import argus_official_event_lifecycle as OL
import scanner

MATERIAL_ITEM = {"code": "8058", "name": "三菱商事", "title": "業績予想の修正（下方修正）に関するお知らせ",
                 "time": "2026-07-02T08:00", "category": "guidance_down", "categoryJa": "業績下方修正",
                 "sentiment": "negative", "material": True, "official": True, "provider": "jquants-tdnet"}
NON_MATERIAL = {"code": "7203", "name": "トヨタ", "title": "月次生産状況のお知らせ", "time": "2026-07-02T09:00",
                "category": "monthly", "categoryJa": "月次開示", "sentiment": "neutral",
                "material": False, "official": True, "provider": "jquants-tdnet"}
NOW = "2026-07-02T10:00:00Z"


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
    r2 = OL.apply_market_reaction(r, _confirmed_reaction())
    assert r2["causeStatus"] == "confirmed_cause"
    assert r2["marketReaction"]["sameDay"]["marketConfirmed"] is True


def test_small_move_both_windows_is_not_cause():
    r = rec()
    weak_same = OL.build_market_reaction(window="same_day", observed_at=NOW, price_move_pct=0.3)
    weak_next = OL.build_market_reaction(window="next_session", observed_at=NOW, price_move_pct=-0.2)
    r2 = OL.apply_market_reaction(OL.apply_market_reaction(r, weak_same), weak_next)
    assert r2["causeStatus"] == "not_cause"


def test_disclosure_after_move_never_immediate_trigger():
    r = rec()
    r2 = OL.apply_market_reaction(r, _confirmed_reaction(),
                                  move_started_at="2026-07-02T01:00")   # move BEFORE disclosure
    assert r2["causeStatus"] != "confirmed_cause"
    assert "timing:disclosure_after_move" in r2["missingConfirmations"]


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
    scanner._official_lifecycle_ingest({"items": [MATERIAL_ITEM, NON_MATERIAL]})


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
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/evidence-pack?symbol=8058&market=JP").get_json()
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

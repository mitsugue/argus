"""ARGUS Pro — EventCard v2 discipline tests (Phase 2).

The card must never promote association to cause, never let a theme-only link move
the Today call, always apply the visibility cap, and always say what's missing.
"""
import argus_event_card as EC
import scanner

ENV = {
    "eventId": "e1", "eventType": "PRICE_MOVE", "symbol": "NVDA", "market": "US",
    "source": "marketwatch_public", "reliabilityScore": 0.6, "triggerScore": 0.5,
    "reasonJa": "急落を検知", "linkedAssets": [], "evidenceIds": ["ev1"],
    "detectedAt": "2026-07-01T05:00:00Z", "lifecycleState": "DETECTED",
    "nextOpenAt": None, "recommendedPosture": "WATCH",
}


def card(**kw):
    return EC.build_card(ENV, **kw)


def test_single_source_is_never_confirmed_cause():
    c = card(independent_family_count=1, has_official=False, market_confirmed=False)
    assert c["corroborationLevel"] == "single_source"
    assert c["triggerRole"] == "candidate_catalyst"
    assert c["triggerRole"] != "confirmed_cause"


def test_market_confirmed_alone_without_official_is_not_confirmed_cause():
    c = card(independent_family_count=1, has_official=False, market_confirmed=True)
    assert c["corroborationLevel"] == "market_confirmed"
    assert c["triggerRole"] != "confirmed_cause"


def test_official_gives_official_corroboration():
    c = card(independent_family_count=1, has_official=True, market_confirmed=False)
    assert c["corroborationLevel"] == "official"
    assert c["triggerRole"] == "probable_catalyst"


def test_confirmed_cause_requires_official_and_market():
    c = card(independent_family_count=2, has_official=True, market_confirmed=True)
    assert c["corroborationLevel"] == "official_and_market_confirmed"
    assert c["triggerRole"] == "confirmed_cause"


def test_two_independent_families_are_probable_not_confirmed():
    c = card(independent_family_count=2, has_official=False, market_confirmed=False)
    assert c["corroborationLevel"] == "multi_source"
    assert c["triggerRole"] == "probable_catalyst"


def test_visibility_cap_lowers_confidence_final():
    g = {"confidenceCap": 0.3, "blockedActions": [], "reasonCodes": ["CALIBRATION_BURN_IN"],
         "visibilityLevel": "reduced"}
    c = card(independent_family_count=2, has_official=True, market_confirmed=True, guard=g)
    assert c["confidenceFinal"] <= 0.3
    assert c["confidenceFinal"] <= c["confidenceRaw"]
    assert c["visibility"]["confidenceCap"] == 0.3


def test_missing_market_depth_appears_in_missing_confirmations():
    c = card(independent_family_count=1, missing_depth=["L2", "TAPE"])
    assert "market_depth:L2" in c["missingConfirmations"]
    assert "market_depth:TAPE" in c["missingConfirmations"]


def test_every_card_states_missing_official_and_market():
    c = card(independent_family_count=1, has_official=False, market_confirmed=False)
    assert "official_confirmation" in c["missingConfirmations"]
    assert "market_confirmation" in c["missingConfirmations"]


def test_theme_only_cannot_move_today_call():
    c = card(independent_family_count=1, theme_only=True, market_confirmed=False)
    assert c["triggerRole"] == "background_theme"
    assert c["decisionImpact"]["canAffectTodayCall"] is False


def test_event_after_move_is_never_immediate_trigger():
    c = card(independent_family_count=2, has_official=True, market_confirmed=True,
             event_after_move=True)
    assert c["triggerRole"] in ("vulnerability_context", "background_theme")


def test_schema_version_and_empty_input():
    assert EC.build_card(ENV)["schemaVersion"] == "event-card-v2"
    assert EC.build_cards([]) == []


def test_blocked_entry_downgrades_posture_delta():
    g = {"confidenceCap": None, "blockedActions": ["ENTER"], "reasonCodes": ["BRIDGE_STALE"],
         "visibilityLevel": "reduced"}
    c = card(independent_family_count=2, has_official=True, market_confirmed=True, guard=g)
    assert c["decisionImpact"]["blockedActions"] == ["ENTER"]
    assert c["decisionImpact"]["postureDelta"] == "downgrade"
    assert c["decisionImpact"]["downgradeReasonJa"]


# ── endpoint shape ───────────────────────────────────────────────────────────
def test_event_cards_endpoint_shape():
    with scanner.app.test_client() as cl:
        d = cl.get("/api/argus/events/cards").get_json()
    assert d["schemaVersion"] == "event-card-v2"
    assert "items" in d and isinstance(d["items"], list)


def test_event_cards_missing_id_is_404_json():
    with scanner.app.test_client() as cl:
        r = cl.get("/api/argus/events/cards/does-not-exist")
    assert r.status_code == 404 and r.is_json

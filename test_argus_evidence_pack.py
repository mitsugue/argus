"""ARGUS V11.2 — Evidence Pack (decision spine) tests.

The pack must be pure + deterministic, state missing data explicitly, and bake in the
discipline: CAOS candidates never confirm cause; official disclosure = fact, not price
cause, until market/timing confirmation exists.
"""
import json
import argus_evidence_pack as EP

AS_OF = "2026-07-02T09:00:00Z"

CARD_CANDIDATE = {
    "cardId": "e1", "eventType": "price_move", "headline": "急落を検知",
    "corroborationLevel": "single_source", "triggerRole": "candidate_catalyst",
    "confidenceFinal": 0.4, "missingConfirmations": ["official_confirmation"],
    "marketConfirmations": ["price_move_confirmed"],
    "decisionImpact": {"canAffectTodayCall": False},
}
CARD_CONFIRMED = {
    "cardId": "e2", "eventType": "tdnet", "headline": "下方修正+市場確認",
    "corroborationLevel": "official_and_market_confirmed", "triggerRole": "confirmed_cause",
    "confidenceFinal": 0.7, "missingConfirmations": [],
    "marketConfirmations": ["price_move_confirmed"],
    "decisionImpact": {"canAffectTodayCall": True},
}
DISC_MATERIAL = {"title": "業績予想の修正（下方修正）", "category": "guidance_down",
                 "categoryJa": "業績下方修正", "sentiment": "negative", "material": True,
                 "time": "2026-07-02T08:00", "official": True, "provider": "jquants-tdnet"}
CAOS_LINK = {"linkType": "theme", "triggerRole": "candidate_catalyst",
             "corroborationLevel": "single_source", "whyJa": "AIテーマ連想",
             "nonCausalityCaveatJa": "これは連想・候補であり、原因確定ではありません。", "asOf": AS_OF}


def base_pack(**kw):
    args = dict(symbol="8058", as_of=AS_OF, market="JP")
    args.update(kw)
    return EP.build_pack(**args)


def test_pack_is_deterministic():
    a = base_pack(event_cards=[CARD_CANDIDATE], caos_links=[CAOS_LINK],
                  official_disclosures=[DISC_MATERIAL])
    b = base_pack(event_cards=[CARD_CANDIDATE], caos_links=[CAOS_LINK],
                  official_disclosures=[DISC_MATERIAL])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_pack_id_deterministic_per_day():
    assert EP.pack_id("8058", "2026-07-02T09:00:00Z") == "ep-8058-20260702"
    assert EP.pack_id("mu", "2026-07-02") == "ep-MU-20260702"


def test_includes_event_card_ids():
    p = base_pack(event_cards=[CARD_CANDIDATE, CARD_CONFIRMED])
    assert {c["cardId"] for c in p["eventCards"]} == {"e1", "e2"}


def test_caos_candidate_never_confirms_cause():
    p = base_pack(event_cards=[CARD_CANDIDATE], caos_links=[CAOS_LINK])
    assert p["allowedUse"]["canConfirmCause"] is False
    assert p["caosLinks"][0]["nonCausalityCaveatJa"]


def test_official_disclosure_is_fact_not_price_cause():
    # Material official disclosure but NO confirmed_cause card → fact confirmed, cause NOT.
    p = base_pack(official_disclosures=[DISC_MATERIAL])
    assert p["officialDisclosures"][0]["material"] is True
    assert p["allowedUse"]["canConfirmCause"] is False        # needs market/timing confirmation
    assert p["allowedUse"]["canAffectTodayCall"] is True       # material official CAN move the call


def test_confirmed_cause_requires_confirmed_card():
    p = base_pack(event_cards=[CARD_CONFIRMED])
    assert p["allowedUse"]["canConfirmCause"] is True


def test_missing_data_is_explicit():
    p = base_pack()                                            # nothing collected
    assert "official_confirmation" in p["missingConfirmations"]
    assert "market_confirmation" in p["missingConfirmations"]
    assert "market_depth:true_depth" in p["missingConfirmations"]


def test_visibility_reason_codes_flow_into_missing():
    p = base_pack(visibility_guard={"visibilityLevel": "reduced", "confidenceCap": 0.55,
                                    "blockedActions": ["ENTER"], "reasonCodes": ["BRIDGE_STALE"]})
    assert "visibility:BRIDGE_STALE" in p["missingConfirmations"]
    assert p["visibilityGuard"]["blockedActions"] == ["ENTER"]


def test_burn_in_adds_disclaimer():
    p = base_pack(calibration_status={"isActive": True, "reliabilityStage": "burn_in"})
    assert any("burn-in" in d for d in p["disclaimersJa"])


def test_discipline_lines_always_present():
    p = base_pack()
    joined = "".join(p["disclaimersJa"])
    assert "候補" in joined and "価格変動の原因確定ではない" in joined and "ENTER" in joined


def test_no_private_fields():
    p = base_pack(quote={"price": 4344.0, "changePct": -1.0, "status": "live",
                         "quantity": 100, "costPrice": 4000})    # hostile input
    blob = json.dumps(p).lower()
    for leak in ("quantity", "costprice", "netr", "pnl", "holdings"):
        assert leak not in blob, leak


def test_market_inference():
    assert EP.infer_market("8058") == "JP"
    assert EP.infer_market("285A") == "JP"
    assert EP.infer_market("MU") == "US"
    assert EP.infer_market("BTC") == "CRYPTO"
    assert EP.infer_market("8058", "US") == "US"               # explicit wins


def test_compact_for_ai_leads_with_discipline_facts():
    p = base_pack(event_cards=[CARD_CANDIDATE], official_disclosures=[DISC_MATERIAL],
                  visibility_guard={"confidenceCap": 0.55, "blockedActions": ["ENTER"],
                                    "reasonCodes": ["BRIDGE_STALE"], "visibilityLevel": "reduced"})
    s = EP.compact_for_ai(p)
    assert "cause確定可=NO" in s
    assert "不足:" in s and "可視性:" in s
    assert len(s) <= 1400

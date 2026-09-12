import copy
import json
import pytest
import argus_market_brief as mb
import scanner


def brief(text="VIX 20、上昇を観測", verified="VERIFIED", source="official_sensor"):
    return mb.compose_brief(now_iso="2026-09-12T10:00:00Z", shock_events=[
        {"severity": "HIGH", "headlineJa": text}]) | {
            "facts": [{"text": text, "verification": verified, "priority": "P0", "source": source}]}


def response(context):
    ref = context["facts"][0]["evidenceId"]
    result = {key: {"textJa": "VIX 20の動きを確認します。", "evidenceIds": [ref], "kind": "INFERENCE"}
              for key in mb.UNIFIED_SECTIONS}
    result["impact"] = {"textJa": "保有情報は未確認です。", "evidenceIds": [], "kind": "UNKNOWN"}
    if not context["changes"]["comparisonAvailable"]:
        result["changes"] = {"textJa": "前回は未確認です。", "evidenceIds": [], "kind": "UNKNOWN"}
    return result


def test_six_parts_are_linked_and_no_private_holdings_claim_is_generated():
    context = mb.unified_context(brief())
    answer = mb.validate_unified_ai(response(context), context)
    assert answer["contextId"] == context["contextId"]
    assert set(answer["sections"]) == set(mb.UNIFIED_SECTIONS)
    assert answer["actionAuthority"] is False
    assert answer["historyStatus"] == "PROCESS_MEMORY_ONLY"
    assert answer["sections"]["impact"]["kind"] == "UNKNOWN"
    assert "未確認" in answer["sections"]["impact"]["textJa"]


@pytest.mark.parametrize("patch", [
    {"textJa": "VIX 99へ上昇します。"}, {"evidenceIds": ["invented"]},
    {"kind": "FACT"}, {"textJa": "上昇確率は20%です。"}, {"evidenceIds": []},
    {"textJa": "今すぐ買うべきです。"}])
def test_unsupported_numbers_references_authority_and_probability_are_rejected(patch):
    context = mb.unified_context(brief()); raw = response(context)
    raw["view"].update(patch)
    assert mb.validate_unified_ai(raw, context) is None


def test_previous_fact_cannot_be_presented_as_current():
    context = mb.unified_context(brief(), brief("VIX 19"))
    raw = response(context); old = context["previousFacts"][0]["evidenceId"]
    raw["changes"] = {"textJa": "VIX 19から20へ変化しています。", "evidenceIds": [old, context["facts"][0]["evidenceId"]], "kind": "FACT"}
    assert mb.validate_unified_ai(raw, context) is not None
    raw["view"] = {"textJa": "VIX 19です。", "evidenceIds": [old], "kind": "INFERENCE"}
    assert mb.validate_unified_ai(raw, context) is None


def test_engine_interpretation_is_not_observed_fact():
    context = mb.unified_context(brief(source="market_view"))
    assert context["facts"][0]["verification"] == "UNCONFIRMED"
    raw = response(context); raw["reasons"]["kind"] = "FACT"
    assert mb.validate_unified_ai(raw, context) is None


def test_source_verification_changes_identity_even_with_same_text():
    a = mb.unified_context(brief())
    b = mb.unified_context(brief(verified="UNCONFIRMED"))
    assert a["contextId"] != b["contextId"]
    assert a["facts"][0]["evidenceId"] != b["facts"][0]["evidenceId"]


def test_runtime_preserves_last_success_across_public_refresh_and_failure(monkeypatch):
    state = {"data": None, "composedAt": 0.0, "aiFactsHash": None}
    monkeypatch.setattr(scanner, "_MARKET_BRIEF", state)
    current = {"value": brief()}
    monkeypatch.setattr(scanner, "_compose_market_brief", lambda: copy.deepcopy(current["value"]))
    calls = []; fail = {"value": False}
    def model(user, **kwargs):
        context = json.loads(user.split("\n", 1)[1]);calls.append(context)
        kwargs["diagnostic"].update(requestedModel="gpt-6-astra", returnedModel="gpt-6-astra",
                                     completedAt="2026-09-12T10:01:00Z", outcome="ok")
        return None if fail["value"] else response(context)
    monkeypatch.setattr(scanner, "_openai_prose", model)
    first = scanner._market_brief_refresh(allow_ai=True)
    assert first["unifiedStatus"] == "GENERATED"
    assert not first["unifiedContext"]["changes"]["comparisonAvailable"]
    same = scanner._market_brief_refresh(allow_ai=False)
    assert same["unifiedSummary"] == first["unifiedSummary"] and len(calls) == 1
    current["value"] = brief("VIX 20、価格の反応待ち")
    cold = scanner._market_brief_refresh(allow_ai=False)
    assert cold["unifiedSummary"] is None and len(calls) == 1
    assert cold["unifiedContext"]["previousFacts"] == first["unifiedContext"]["facts"]
    fail["value"] = True
    failed = scanner._market_brief_refresh(allow_ai=True)
    assert failed["unifiedStatus"] == "UNAVAILABLE"
    assert state["lastSuccessful"]["unifiedSummary"] == first["unifiedSummary"]
    fail["value"] = False
    final = scanner._market_brief_refresh(allow_ai=True)
    assert final["unifiedContext"]["previousFacts"] == first["unifiedContext"]["facts"]
    assert final["aiDiagnostics"]["returnedModel"] == "gpt-6-astra"

"""External policy prevents AI reintroduction without changing accepted content."""
import copy
import json
import sys
from types import SimpleNamespace

import pytest

import argus_product_naming as naming


POLICY = {"schemaVersion": "product-naming-policy-v1", "rules": [
    {"id": "N001", "pattern": r"(?i)\bretired_person\b"}]}


def test_runtime_policy_inspects_keys_width_and_nested_content_without_rewriting():
    rules = naming.compile_policy(POLICY)
    value = {"analysis": ["ＲＥＴＩＲＥＤ＿ＰＥＲＳＯＮ", {"retired_person": "source"}],
             "observations": [False, 0, None, 123.4], "shortSelling": "ordinary"}
    before = copy.deepcopy(value)
    result = naming.inspect_content(value, rules)
    assert result == {"status": "REJECTED", "ruleIds": ["N001"]}
    assert value == before
    assert "retired_person" not in json.dumps(result).lower()
    assert naming.inspect_content({"shortSelling": "retired_personality"}, rules)["status"] == "PASS"


def test_missing_production_policy_is_unavailable_and_local_absence_is_not_pass(monkeypatch):
    monkeypatch.delenv("PRODUCT_NAMING_POLICY", raising=False)
    assert naming.require_allowed("ordinary", required=False)["status"] == "NOT_CONFIGURED"
    with pytest.raises(naming.NamingPolicyError, match="naming_policy_unavailable"):
        naming.require_allowed("ordinary", required=True)
    monkeypatch.setenv("PRODUCT_NAMING_POLICY", "not json")
    with pytest.raises(naming.NamingPolicyError, match="naming_policy_unavailable"):
        naming.require_allowed("ordinary", required=False)


def test_runtime_policy_reloads_on_change_and_rejects_cycles(monkeypatch):
    monkeypatch.setenv("PRODUCT_NAMING_POLICY", json.dumps(POLICY))
    with pytest.raises(naming.NamingPolicyError, match="naming_content_rejected:N001"):
        naming.require_allowed({"summary": "RETIRED_PERSON"})
    monkeypatch.setenv("PRODUCT_NAMING_POLICY", json.dumps({
        **POLICY, "rules": [{"id": "N002", "pattern": "different_marker"}]}))
    assert naming.require_allowed({"summary": "retired_person"})["status"] == "PASS"
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(naming.NamingPolicyError, match="uninspectable"):
        naming.require_allowed(cyclic)


@pytest.fixture
def prose(monkeypatch):
    import scanner
    monkeypatch.setenv("PRODUCT_NAMING_POLICY", json.dumps(POLICY))
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr(scanner, "_OPENAI_PROSE_LAST", {})
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kw: object()))
    reservations, settlements, calls = [], [], []
    def reserve(*args, **kwargs):
        reservations.append(kwargs)
        return {"allowed": True}, "reservation"
    monkeypatch.setattr(scanner, "_cost_policy_reserve", reserve)
    monkeypatch.setattr(scanner, "_cost_policy_settle",
                        lambda *args, **kwargs: settlements.append(kwargs))
    monkeypatch.setattr(scanner, "_ai_record_prose_cost", lambda *args, **kwargs: None)
    def respond(payload):
        def call(*args, **kwargs):
            calls.append(True)
            return SimpleNamespace(model="synthetic", usage=SimpleNamespace(
                input_tokens=100, output_tokens=20)), json.dumps(payload)
        monkeypatch.setattr(scanner, "_openai_prose_call", call)
    return scanner, reservations, settlements, calls, respond


def test_prose_rejects_reintroduced_output_but_records_spent_call_once(prose):
    scanner, _, settlements, calls, respond = prose
    respond({"summaryJa": "ＲＥＴＩＲＥＤ＿ＰＥＲＳＯＮ"})
    diagnostic = {}
    assert scanner._openai_prose("observations", diagnostic=diagnostic) is None
    assert calls == [True]
    assert len(settlements) == 1 and settlements[0]["ok"] is True
    assert settlements[0]["actual_cost_usd"] > 0
    assert diagnostic["outcome"] == "rejected"
    assert diagnostic["reason"] == "naming_content_rejected:N001"
    assert "retired_person" not in json.dumps(diagnostic).lower()


def test_prose_rejects_unreviewed_source_before_reserving_or_calling(prose):
    scanner, reservations, settlements, calls, respond = prose
    respond({"summaryJa": "ordinary"})
    assert scanner._openai_prose("retired_person is an authority") is None
    assert not reservations and not settlements and not calls


def test_prose_preserves_accepted_content_and_budget_accounting(prose):
    scanner, _, settlements, calls, respond = prose
    content = {"summaryJa": "観測値から条件を説明する", "value": 12.3, "validated": False}
    respond(content)
    assert scanner._openai_prose("observations") == content
    assert calls == [True]
    assert len(settlements) == 1 and settlements[0]["ok"] is True


def test_research_rejects_response_without_fallback_and_keeps_usage(monkeypatch):
    import scanner
    monkeypatch.setenv("PRODUCT_NAMING_POLICY", json.dumps(POLICY))
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr(scanner, "_cost_policy_authorize", lambda *a, **k: {"allowed": True})
    monkeypatch.setattr(scanner.argus_ai_gate, "can_execute_external", lambda *a, **k: {"allowed": True})
    monkeypatch.setattr(scanner.argus_ai_gate, "reserve_budget", lambda **k: {"allowed": True})
    monkeypatch.setattr(scanner, "_ai_cost_roll", lambda *a: None)
    monkeypatch.setattr(scanner, "_ai_record_cost", lambda *a: None)
    monkeypatch.setattr(scanner, "_AI_INTEGRITY", copy.deepcopy(scanner._AI_INTEGRITY))
    calls = []
    def respond(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text='{"summary":"retired_person"}',
            model=kwargs["model"], usage=SimpleNamespace(input_tokens=120, output_tokens=30))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kw:
        SimpleNamespace(responses=SimpleNamespace(create=respond))))
    output, result = scanner._openai_research_ex("observations")
    assert output is None and result["status"] == "unavailable"
    assert result["failureReasonRedacted"] == "naming_content_rejected:N001"
    assert result["usage"]["inputTokens"] == 120
    assert result["usage"]["outputTokens"] == 30
    assert len(calls) == 1
    assert "retired_person" not in json.dumps(result).lower()
    output, result = scanner._openai_research_ex("retired_person")
    assert output is None and len(calls) == 1


@pytest.mark.parametrize("lane", ["research", "translation"])
def test_gemini_rejects_new_content_before_cache_admission_and_counts_spend(monkeypatch, lane):
    import scanner
    monkeypatch.setenv("PRODUCT_NAMING_POLICY", json.dumps(POLICY))
    monkeypatch.setattr(scanner, "GEMINI_API_KEY", "synthetic")
    monkeypatch.setattr(scanner, "_cost_policy_authorize", lambda *a, **k: {"allowed": True})
    charges, calls = [], []
    monkeypatch.setattr(scanner, "_cost_policy_record", lambda *a, **k: charges.append(k))
    text = json.dumps({"claims": [], "summary": "retired_person"} if lane == "research"
                      else {"translations": ["retired_person"]})
    def respond(**kw):
        calls.append(kw)
        return SimpleNamespace(text=text)
    fake = SimpleNamespace(Client=lambda **kw: SimpleNamespace(
        models=SimpleNamespace(generate_content=respond)),
        types=SimpleNamespace(GenerateContentConfig=lambda **kw: kw))
    monkeypatch.setattr(scanner, "google_genai", fake)
    monkeypatch.setitem(sys.modules, "google.genai", fake)
    if lane == "research":
        diagnostic = {}
        assert scanner._gemini_osint("observations", diagnostic_context=diagnostic) == (None, "rejected")
        assert diagnostic["errorClass"] == "naming_content_rejected:N001"
        assert "retired_person" not in json.dumps(diagnostic).lower()
        assert scanner._gemini_osint("retired_person")[0] is None
    else:
        assert scanner._translate_headlines_ja(["observations"]) == {}
        assert scanner._translate_headlines_ja(["retired_person"]) == {}
    assert len(calls) == 1 and len(charges) == 1
    assert charges[0]["estimated_cost_usd"] > 0


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_rejected_judge_content_cannot_influence_labels_but_retains_billed_tokens(monkeypatch, provider):
    import scanner
    monkeypatch.setenv("PRODUCT_NAMING_POLICY", json.dumps(POLICY))
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr(scanner, "GEMINI_API_KEY", "synthetic")
    monkeypatch.setattr(scanner, "_cost_policy_authorize", lambda *a, **k: {"allowed": True})
    monkeypatch.setattr(scanner, "_AI_LAST_RUN", copy.deepcopy(scanner._AI_LAST_RUN))
    monkeypatch.setattr(scanner, "_AI_COST_STATE", copy.deepcopy(scanner._AI_COST_STATE))
    monkeypatch.setattr(scanner, "_ai_cost_roll", lambda *a: None)
    monkeypatch.setattr(scanner, "add_log", lambda *a: None)
    scanner._AI_LAST_RUN.update({"oaiUsage": None, "gemUsage": None})
    output = json.dumps({"labels": [], "disagreements": [], "summaryJa": "retired_person"})
    calls = []
    def respond(**kw):
        calls.append(kw)
        return SimpleNamespace(output_text=output, text=output,
            usage=SimpleNamespace(input_tokens=120, output_tokens=30),
            usage_metadata=SimpleNamespace(prompt_token_count=120, candidates_token_count=30))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kw:
        SimpleNamespace(responses=SimpleNamespace(create=respond))))
    monkeypatch.setattr(scanner, "google_genai", SimpleNamespace(Client=lambda **kw:
        SimpleNamespace(models=SimpleNamespace(generate_content=respond))))
    if provider == "openai":
        value, status = scanner._openai_judge({"labels": []})
        statuses = (status, "unavailable")
    else:
        value, status, _ = scanner._gemini_check({"labels": []}, None)
        statuses = ("unavailable", status)
    assert value is None and status == "content_rejected" and len(calls) == 1
    cost = scanner._ai_record_cost("test", *statuses, False)
    assert len(cost["rows"]) == 1
    assert cost["rows"][0]["inputTokens"] == 120
    assert cost["rows"][0]["outputTokens"] == 30
    assert cost["totalUsd"] > 0

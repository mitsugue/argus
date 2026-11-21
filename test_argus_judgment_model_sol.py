"""2026-11-21 owner 【切り替える】: the three judgment-heavy lanes use gpt-6.2-sol.

market_brief, market_position_check and ai_judgment name the newer model
explicitly. Every other lane stays on gpt-5.6-terra, a failed Terra call is
never repeated on the newer model, and the newer model goes Standard from the
first request (no Flex on new models). Offline only: no provider request.
"""
import json
import sys
from types import SimpleNamespace

import pytest

import argus_openai_tier as tier
import scanner

SOL = "gpt-6.2-sol"
TERRA = "gpt-5.6-terra"


def test_three_lanes_name_the_judgment_model_and_the_rest_stay_on_terra():
    assert scanner._OPENAI_JUDGMENT_MODEL == SOL
    assert scanner._OPENAI_JUDGMENT_PURPOSES == frozenset(
        ("market_brief", "market_position_check", "ai_judgment"))
    assert scanner._OPENAI_MODEL == TERRA
    # The news escalation model is not the judgment model: no hidden upgrade.
    assert scanner._OPENAI_SOL_MODEL == TERRA
    assert scanner._OPENAI_EVENT_MODEL == TERRA
    for purpose in scanner._OPENAI_JUDGMENT_PURPOSES:
        assert scanner._openai_model_allowed(SOL, purpose)
        assert scanner._openai_model_allowed(TERRA, purpose)
    for purpose in ("news_intel", "event_analysis", "headline_translation", "owner_dialogue",
                    "osint_research", "manual_api", "entity_profiles", "prose", "research_benchmark"):
        assert not scanner._openai_model_allowed(SOL, purpose)
        assert scanner._openai_model_allowed(TERRA, purpose)
    # Environment role settings cannot route any lane to the judgment model.
    assert scanner._routine_openai_model(SOL) == TERRA
    assert all(model == TERRA for model in scanner._OPENAI_MODEL_ROLES.values())
    assert scanner._AI_PRICING[SOL] == {"in": 2.0, "out": 10.0, "cachedIn": 0.10}


def test_judgment_model_goes_standard_from_the_first_request():
    state = tier.TierState()
    assert SOL in tier.STANDARD_ONLY_MODELS
    for purpose in ("market_brief", "market_position_check", "ai_judgment"):
        assert not state.wants_flex(purpose, SOL)
        assert not state.wants_flex(purpose, SOL, "web_search")
        assert state.wants_flex(purpose, TERRA)          # Terra lanes keep Flex
    sent = []
    def call(kwargs, name):
        sent.append((name, kwargs))
        return SimpleNamespace(service_tier="default")
    tier.create(state, purpose="market_brief", model=SOL, kwargs={"model": SOL, "timeout": 60}, call=call)
    assert sent == [("standard", {"model": SOL, "timeout": 60})]
    assert state.view()["counts"] == {}                   # no Flex was asked or refused
    assert state.view()["standardOnlyModels"] == [SOL]


class _Recorder:
    def __init__(self, model_suffix="-2026-11-01", fail=None):
        self.sent, self.fail, self.suffix = [], fail, model_suffix

    def module(self):
        recorder = self

        class Responses:
            def create(self, **kw):
                recorder.sent.append(kw)
                if recorder.fail is not None:
                    raise recorder.fail
                return SimpleNamespace(model=kw["model"] + recorder.suffix, id="r",
                    service_tier="default", output_text='{"labels": [], "summaryJa": "x"}',
                    usage=SimpleNamespace(input_tokens=1000, output_tokens=100))

        class Client:
            def __init__(self, **kw):
                self.responses = Responses()

            def with_options(self, **kw):
                return self

        return SimpleNamespace(OpenAI=Client)


@pytest.fixture
def offline(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setitem(sys.modules, "openai", recorder.module())
    monkeypatch.setattr(scanner, "_OPENAI_API_KEY", "synthetic")
    monkeypatch.setattr(scanner, "_OPENAI_TIER", tier.TierState())
    reserved = []
    monkeypatch.setattr(scanner, "_cost_policy_reserve", lambda provider, purpose, **kw: (
        reserved.append((purpose, kw)), ({"allowed": True}, "rsv"))[1])
    monkeypatch.setattr(scanner, "_cost_policy_settle", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_ai_record_prose_cost", lambda *a, **k: None)
    monkeypatch.setattr(scanner, "_ai_usage_provider_call",
                        lambda provider, feature, model, invoke, **kw: invoke())
    return recorder, reserved


def test_brief_prose_sends_the_judgment_model_on_standard_without_explicit_cache(offline):
    recorder, _ = offline
    diag = {}
    out = scanner._openai_prose("facts", max_out=5200, system="voice", purpose="market_brief",
                                model=SOL, diagnostic=diag,
                                cache_prefix_chars=scanner._brief_cache_prefix(SOL, "facts"))
    assert out == {"labels": [], "summaryJa": "x"}
    assert [kw["model"] for kw in recorder.sent] == [SOL]
    body = recorder.sent[0]
    assert "service_tier" not in body and body["timeout"] == 60
    # The reviewed explicit cache is a Terra/Luna request shape; the newer
    # model gets the exact shape the owner's comparison sent (plain input).
    assert "prompt_cache_options" not in body and body["input"] == "facts"
    assert diag["requestedModel"] == SOL and diag["outcome"] == "ok"
    assert scanner._brief_cache_prefix(TERRA, "facts") == len("facts")
    with pytest.raises(ValueError, match="brief_cache_boundary_invalid"):
        scanner._openai_prose_call(SimpleNamespace(), SOL, "p", "facts",
                                   purpose="market_brief", cache_prefix_chars=2)


@pytest.mark.parametrize("purpose", ["news_intel", "event_analysis", "owner_dialogue",
                                     "headline_translation", "osint_research", "prose"])
def test_other_lanes_cannot_reach_the_judgment_model(offline, purpose):
    recorder, reserved = offline
    diag = {}
    assert scanner._openai_prose("x", purpose=purpose, model=SOL, diagnostic=diag) is None
    assert diag["reason"] == "production_model_not_allowed"
    assert recorder.sent == [] and reserved == []
    text, result = scanner._openai_research_ex("x", purpose=purpose, model=SOL)
    assert text is None and result["failureReasonRedacted"] == "production_model_not_allowed"
    assert recorder.sent == [] and reserved == []


def test_a_failed_terra_call_is_not_repeated_on_the_judgment_model(offline):
    recorder, _ = offline
    recorder.fail = type("APIConnectionError", (Exception,), {})("down")
    diag = {}
    assert scanner._openai_prose("x", purpose="news_intel", diagnostic=diag) is None
    assert diag["outcome"] == "error"
    text, result = scanner._openai_research_ex("x", purpose="osint_research")
    assert text is None
    assert [kw["model"] for kw in recorder.sent] == [TERRA, TERRA]
    # The judgment lanes themselves are not repeated on any other model either.
    recorder.sent.clear()
    assert scanner._openai_prose("x", purpose="market_brief", model=SOL, diagnostic={}) is None
    scanner._openai_research_ex("x", purpose="market_position_check", model=SOL)
    assert [kw["model"] for kw in recorder.sent] == [SOL, SOL]


def test_news_escalation_cannot_become_the_judgment_model(offline, monkeypatch):
    recorder, _ = offline
    monkeypatch.setattr(scanner, "_OPENAI_SOL_MODEL", SOL)
    diag = {}
    assert scanner._openai_prose("x", purpose="news_intel", model=scanner._OPENAI_SOL_MODEL,
                                 diagnostic=diag) is None
    assert diag["reason"] == "production_model_not_allowed" and recorder.sent == []


def test_position_check_search_uses_the_judgment_model_with_the_tool_on_standard(offline):
    recorder, reserved = offline
    text, result = scanner._openai_research_ex("q", role="standard", purpose="market_position_check",
                                               model=SOL, max_output=8000)
    assert text and result["status"] == "ok" and result["model"] == SOL
    body = recorder.sent[0]
    assert body["model"] == SOL and body["tools"] == [{"type": "web_search"}]
    assert "service_tier" not in body and body["max_output_tokens"] == 8000
    assert reserved[0][0] == "market_position_check"
    # A refused tool is a visible failure; nothing is sent again without it.
    recorder.sent.clear()
    refusal = type("BadRequestError", (Exception,), {"status_code": 400})("tool not supported")
    recorder.fail = refusal
    text, result = scanner._openai_research_ex("q", purpose="market_position_check", model=SOL)
    assert text is None and result["status"] == "search_failed"
    assert result["failureReasonRedacted"] == "BadRequestError"
    assert len(recorder.sent) == 1


def test_position_check_run_names_the_judgment_model(monkeypatch):
    seen = []
    monkeypatch.setattr(scanner, "_market_position_check_mode", lambda: "shadow")
    monkeypatch.setattr(scanner.argus_market_position_check, "due", lambda *a: "2026-11-21 08:30")
    monkeypatch.setattr(scanner, "_market_position_memory_locked", lambda: {"entries": []})
    monkeypatch.setattr(scanner.argus_market_position_memory, "snapshot", lambda *a, **k: {})
    monkeypatch.setattr(scanner, "_position_check_scheduled_events", lambda: [])
    monkeypatch.setattr(scanner.argus_market_position_check, "select_questions",
                        lambda *a, **k: [{"id": "q1"}])
    monkeypatch.setattr(scanner.argus_market_position_check, "build_prompt", lambda *a, **k: "q")
    monkeypatch.setattr(scanner, "_scheduled_ai_skip", lambda *a: None)
    monkeypatch.setattr(scanner, "_MARKET_POSITION_CHECK", {"lastSlot": None, "runs": 0})
    monkeypatch.setattr(scanner, "_openai_research_ex", lambda prompt, **kw: (
        seen.append(kw), (None, {"status": "search_failed"}))[1])
    scanner._market_position_check_run()
    assert seen and seen[0]["model"] == SOL and seen[0]["purpose"] == "market_position_check"


def test_ai_judgment_requests_records_and_prices_the_judgment_model(offline, monkeypatch):
    recorder, reserved = offline
    monkeypatch.setattr(scanner, "_AI_LAST_RUN", {})
    out, status = scanner._openai_judge({"labels": []})
    assert status == "live" and out["labels"] == []
    body = recorder.sent[0]
    assert body["model"] == SOL and "service_tier" not in body
    diag = scanner._AI_LAST_RUN["oaiDiagnostic"]
    assert diag["requestedModel"] == SOL and diag["returnedModel"] == SOL + "-2026-11-01"
    assert reserved[0][0] == "ai_judgment"
    monkeypatch.setattr(scanner, "_ai_cost_account_record", lambda rec: None)
    rec = scanner._ai_record_cost("run", "live", "unavailable", False)
    row = rec["rows"][0]
    assert row["model"] == SOL + "-2026-11-01"
    assert abs(row["estUsd"] - (1000 * 2.0 + 100 * 10.0) / 1_000_000) < 1e-9
    payload = scanner._ai_disabled_payload()
    assert payload["models"]["primary"] == SOL


def test_brief_reuse_and_comparison_compare_with_the_judgment_model(monkeypatch):
    monkeypatch.setattr(scanner, "_INDEX_RESEARCH_REPORTS", {})
    monkeypatch.setattr(scanner, "_backend_exact_sha", lambda: "a" * 40)
    policies = []
    monkeypatch.setattr(scanner, "_owner_overview_generation_policy",
                        lambda: {"model": TERRA, "ruleVersion": "a" * 40})
    monkeypatch.setattr(scanner, "_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE", {})
    monkeypatch.setattr(scanner, "_JP_MARKET_FEATURE_HISTORY", {"status": "AVAILABLE", "features": []})
    real_dumps = scanner.json.dumps

    def capture(value, *a, **k):
        if isinstance(value, dict) and "generationPolicy" in value:
            policies.append(value["generationPolicy"])
        return real_dumps(value, *a, **k)

    monkeypatch.setattr(scanner.json, "dumps", capture)
    brief = {"generatedAt": "2026-11-21T00:00:00Z", "facts": []}
    first = scanner._market_brief_generation_input_digest(brief, {"status": "AVAILABLE"})
    # The same inputs give the same digest: one rebuild after the switch, not every edition.
    assert scanner._market_brief_generation_input_digest(brief, {"status": "AVAILABLE"}) == first
    assert policies[0]["model"] == SOL and policies[0]["purpose"] == "market_brief"
    monkeypatch.setattr(scanner.json, "dumps", real_dumps)
    # The comparison reads only editions the current brief model wrote.
    rows = {"t": {"brief": {"presentationStatus": "GENERATED",
                            "aiDiagnostics": {"requestedModel": TERRA}}},
            "s": {"brief": {"presentationStatus": "GENERATED",
                            "aiDiagnostics": {"requestedModel": SOL}}}}
    monkeypatch.setattr(scanner, "_market_brief_history_path", lambda: "/synthetic")
    monkeypatch.setattr(scanner.argus_analysis_history, "read_page_index",
                        lambda path, limit: {"rows": [{"recordId": "t"}, {"recordId": "s"}]})
    monkeypatch.setattr(scanner.argus_analysis_history, "read_record", lambda path, rid: rows[rid])
    compared = []
    monkeypatch.setattr(scanner, "_market_brief_model_comparison_one",
                        lambda record, model: (compared.append(record), {"ok": True})[1])
    monkeypatch.setattr(scanner, "_MODEL_COMPARISON", {"jobId": "j"})
    scanner._market_brief_model_comparison_worker("j", "gpt-6-luna", 5)
    assert compared == [rows["s"]]


def test_brief_polish_names_the_judgment_model_for_both_requests(monkeypatch):
    from test_argus_brief_call_reduction import scheduled_brief
    from test_argus_unified_brief import model_response
    requests = []

    def provider(user, **kwargs):
        context, raw = model_response(user)
        requests.append(kwargs)
        for key in ("view", "reasons", "next", "invalidation"):
            raw[key]["textJa"] = "物価の方向を確認します。"
        if len(requests) == 1:
            raw["view"]["textJa"] = "根拠にない99%の値。"
        kwargs["diagnostic"].update(outcome="ok", requestedModel=kwargs["model"], estUsd=.01)
        return raw

    monkeypatch.setattr(scanner, "_openai_prose", provider)
    brief = scheduled_brief()
    brief["unifiedContext"] = scanner.argus_market_brief.unified_context(brief)
    result = scanner._market_brief_ai_polish(brief)
    assert len(requests) == 2 and result["unifiedStatus"] == "GENERATED"
    assert [r["model"] for r in requests] == [SOL, SOL]
    assert [r["purpose"] for r in requests] == ["market_brief", "market_brief"]
    assert [r["cache_prefix_chars"] for r in requests] == [None, None]
    assert result["aiDiagnostics"]["requestedModel"] == SOL
    policy = result["aiDiagnostics"]["promptCachePolicy"]
    assert policy["mode"] == "NONE_MODEL_NOT_REVIEWED" and policy["dynamicSuffixCached"] is False
    assert json.dumps(result, ensure_ascii=False)

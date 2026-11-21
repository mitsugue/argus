"""2026-11-11 owner 「見比べを作る」: saved editions written again by a candidate model."""
import copy

import scanner


ADMIN = {"X-ARGUS-ADMIN-TOKEN": "synthetic-admin"}


def _admin(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (
        (True, None, 200) if scanner.request.headers.get("X-ARGUS-ADMIN-TOKEN") == "synthetic-admin"
        else (False, {"error": "unauthorized"}, 401)))
    monkeypatch.setattr(scanner, "_MODEL_COMPARISON", {"status": "NOT_RUN"})


def _post(body, headers=ADMIN):
    with scanner.app.test_client() as client:
        return client.post("/api/argus/admin/model-comparison", json=body, headers=headers)


def test_route_is_admin_only_confirmed_and_bounded(monkeypatch):
    _admin(monkeypatch)
    started = []
    monkeypatch.setattr(scanner.threading, "Thread", lambda **kw: type("T", (), {
        "start": lambda self: started.append(kw["args"])})())
    monkeypatch.setattr(scanner, "_market_brief_history_path", lambda: "/synthetic/history.sqlite3")
    assert _post({"model": "gpt-6.1-terra", "confirm": True}, headers={}).status_code == 401
    assert _post({"model": "gpt-6.1-terra"}).get_json()["status"] == "confirmation_required"
    for model in ("gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", None):
        assert _post({"model": model, "confirm": True}).get_json()["status"] == "model_not_allowed"
    for editions in (0, 7, "5", True):
        assert _post({"model": "gpt-6.1-terra", "editions": editions, "confirm": True}
                     ).get_json()["status"] == "editions_out_of_range"
    assert started == []
    accepted = _post({"model": "gpt-6.1-terra", "editions": 3, "confirm": True})
    assert accepted.status_code == 202 and len(started) == 1
    assert started[0][2:] == (scanner._market_brief_model_comparison_worker,
                              accepted.get_json()["jobId"], "gpt-6.1-terra", 3, False)
    # One job at a time.
    assert _post({"model": "gpt-6.1-terra", "confirm": True}).get_json()["status"] == "already_running"


def test_candidate_model_is_allowed_only_for_the_confirmed_comparison(monkeypatch):
    reserved = []
    monkeypatch.setattr(scanner, "_cost_policy_reserve", lambda *a, **kw: (
        reserved.append(kw), ({"allowed": False, "reason": "synthetic_stop"}, None))[1])
    for kwargs in ({"purpose": "market_brief"}, {"purpose": "manual_api"},
                   {"purpose": "market_brief", "confirmed": True}):
        diag = {}
        assert scanner._openai_prose("x", model="gpt-6.1-terra", diagnostic=diag, **kwargs) is None
        assert diag["reason"] == "production_model_not_allowed"
    assert reserved == []
    diag = {}
    scanner._openai_prose("x", model="gpt-6.1-terra", purpose="manual_api", confirmed=True, diagnostic=diag)
    assert diag["reason"] == "synthetic_stop"
    assert reserved[-1]["automatic"] is False and reserved[-1]["confirmation"] is True
    # The production lane keeps its automatic authorisation.
    scanner._openai_prose("x", purpose="market_brief", diagnostic={})
    assert "automatic" not in reserved[-1]
    assert scanner._AI_PRICING["gpt-6.1-terra"] == {"in": 1.0, "out": 5.0, "cachedIn": 0.05}


def test_one_edition_is_written_again_without_saving_anything(monkeypatch):
    record = {"recordId": "a" * 64, "recordedAt": "2026-11-11T03:00:00Z", "calculations": {"5": {}},
              "brief": {"presentationStatus": "GENERATED", "unifiedContext": {"contextId": "c"},
                        "aiDiagnostics": {"requestedModel": "gpt-5.6-terra", "returnedModel": "gpt-5.6-terra",
                                          "attempts": [{}, {}], "inputTokens": 30000, "outputTokens": 4000},
                        "unifiedSummary": {"sections": {"view": {"textJa": "元の見立て。"}}}}}
    before = copy.deepcopy(record)
    seen = {}
    monkeypatch.setattr(scanner, "_market_brief_prompt", lambda brief: (seen.update(brief=brief), {
        "context": {}, "presentation_catalog": {}, "user": "request", "prompt_context": {},
        "restore_references": lambda value: value})[1])
    calls = []
    monkeypatch.setattr(scanner, "_openai_prose", lambda user, **kw: (calls.append((user, kw)), None)[1])
    for name in ("_market_brief_history_save", "_market_position_memory_locked"):
        monkeypatch.setattr(scanner, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError(name)))
    row = scanner._market_brief_model_comparison_one(record, "gpt-6.1-terra")
    assert record == before                                    # the saved edition is untouched
    assert seen["brief"]["calculationSnapshots"] == {"5": {}}  # its own calculations are sent
    assert calls == [("request", {"max_out": 5200, "system": scanner.argus_presentation_intent.VOICE,
        "purpose": "manual_api", "model": "gpt-6.1-terra", "diagnostic": calls[0][1]["diagnostic"],
        "confirmed": True})]
    assert row["original"] == {"model": "gpt-5.6-terra", "aiCalls": 2, "inputTokens": 30000,
                               "outputTokens": 4000, "sections": {"view": "元の見立て。"}}
    assert row["candidate"]["validation"]["status"] == "NO_ANSWER" and row["candidate"]["sections"] == {}


def test_newer_models_are_comparison_only_and_priced():
    """2026-11-21 (owner 【用途で分ける】): gpt-6-luna may be called only by the
    confirmed comparison, at the official Standard price. gpt-6.2-sol is
    routine only for the three judgment lanes (owner 【切り替える】,
    test_argus_judgment_model_sol) and stays comparable."""
    import scanner
    assert scanner._AI_PRICING["gpt-6.2-sol"] == {"in": 2.0, "out": 10.0, "cachedIn": 0.10}
    assert scanner._AI_PRICING["gpt-6-luna"] == {"in": 0.10, "out": 0.50, "cachedIn": 0.01}
    for model in ("gpt-6.2-sol", "gpt-6-luna"):
        assert model in scanner._COMPARISON_OPENAI_MODELS
        assert scanner._routine_openai_model(model) == "gpt-5.6-terra"
    assert "gpt-6-luna" not in scanner._ROUTINE_OPENAI_MODELS
    assert not scanner._openai_model_allowed("gpt-6-luna", "market_brief")
    assert scanner._openai_model_allowed("gpt-6.2-sol", "market_brief")
    assert not scanner._openai_model_allowed("gpt-6.2-sol", "news_intel")


# ── 2026-11-22 (owner 「全部やる」): explicit-cache trial, comparison only ──

import sys
from types import SimpleNamespace

import pytest

from test_argus_judgment_model_sol import offline  # noqa: F401  (fixture)

SOL = "gpt-6.2-sol"


def test_route_takes_an_optional_boolean_cache(monkeypatch):
    _admin(monkeypatch)
    started = []
    monkeypatch.setattr(scanner.threading, "Thread", lambda **kw: type("T", (), {
        "start": lambda self: started.append(kw["args"])})())
    monkeypatch.setattr(scanner, "_market_brief_history_path", lambda: "/synthetic/history.sqlite3")
    for cache in ("true", 1, None, "yes"):
        assert _post({"model": SOL, "editions": 1, "cache": cache, "confirm": True}
                     ).get_json()["status"] == "cache_invalid"
    assert started == []
    accepted = _post({"model": SOL, "editions": 1, "cache": True, "confirm": True})
    assert accepted.status_code == 202
    assert started[0][2:] == (scanner._market_brief_model_comparison_worker,
                              accepted.get_json()["jobId"], SOL, 1, True)
    assert scanner._MODEL_COMPARISON["cache"] is True


def _record():
    return {"recordId": "b" * 64, "recordedAt": "2026-11-21T23:00:00Z", "calculations": {},
            "brief": {"presentationStatus": "GENERATED", "unifiedContext": {"contextId": "c"},
                      "aiDiagnostics": {"requestedModel": SOL, "returnedModel": SOL, "attempts": [{}]},
                      "unifiedSummary": {"sections": {}}}}


def _fake_prompt(monkeypatch, user="規則と材料の全文"):
    monkeypatch.setattr(scanner, "_market_brief_prompt", lambda brief: {
        "context": {}, "presentation_catalog": {}, "user": user, "prompt_context": {},
        "restore_references": lambda value: value})


def test_cache_sends_the_production_shape_and_reads_it_back_once(monkeypatch):
    _fake_prompt(monkeypatch)
    calls = []

    def provider(user, **kw):
        calls.append((user, kw))
        second = len(calls) == 2
        kw["diagnostic"].update(outcome="ok", inputTokens=45000, outputTokens=3600,
                                cachedInputTokens=44800 if second else 0,
                                cacheWriteInputTokens=None if second else 45000, estUsd=0.12)
        return None
    monkeypatch.setattr(scanner, "_openai_prose", provider)
    for name in ("_market_brief_history_save", "_market_position_memory_locked"):
        monkeypatch.setattr(scanner, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError(name)))
    row = scanner._market_brief_model_comparison_one(_record(), SOL, cache=True, read_check=True)
    assert len(calls) == 2 and calls[0][0] == calls[1][0] == "規則と材料の全文"
    for _, kw in calls:
        assert kw["cache_prefix_chars"] == len("規則と材料の全文")
        assert kw["comparison_cache"] is True and kw["purpose"] == "manual_api"
        assert kw["confirmed"] is True and kw["model"] == SOL
    cache = row["candidate"]["cache"]
    assert cache["requested"] is True and cache["boundaryChars"] == len("規則と材料の全文")
    assert cache["first"]["cacheWriteInputTokens"] == 45000
    assert cache["readCheck"]["cachedInputTokens"] == 44800
    assert row["candidate"]["cachedInputTokens"] == 0          # the first call's own counts
    # Without the read check: one request with the cache shape.
    calls.clear()
    row = scanner._market_brief_model_comparison_one(_record(), SOL, cache=True)
    assert len(calls) == 1 and row["candidate"]["cache"]["readCheck"] is None
    # Without cache: the request is the plain one the comparison always sent.
    calls.clear()
    row = scanner._market_brief_model_comparison_one(_record(), SOL)
    assert "cache_prefix_chars" not in calls[0][1] and "comparison_cache" not in calls[0][1]
    assert "cache" not in row["candidate"]


def test_a_refused_first_request_is_not_sent_again(monkeypatch):
    _fake_prompt(monkeypatch)
    calls = []

    def provider(user, **kw):
        calls.append(kw)
        kw["diagnostic"].update(outcome="error", reason="model_call_failed", errorCode="invalid_request")
        return None
    monkeypatch.setattr(scanner, "_openai_prose", provider)
    row = scanner._market_brief_model_comparison_one(_record(), SOL, cache=True, read_check=True)
    assert len(calls) == 1
    assert row["candidate"]["cache"]["first"]["errorCode"] == "invalid_request"
    assert row["candidate"]["cache"]["readCheck"] is None


def test_worker_reads_back_only_the_first_edition(monkeypatch):
    seen = []
    rows = [{"recordId": c * 64} for c in "abc"]
    monkeypatch.setattr(scanner, "_market_brief_history_path", lambda: "/synthetic/history.sqlite3")
    monkeypatch.setattr(scanner.argus_analysis_history, "read_page_index", lambda path, limit: {"rows": rows})
    monkeypatch.setattr(scanner.argus_analysis_history, "read_record", lambda path, rid: _record())
    monkeypatch.setattr(scanner, "_market_brief_model_comparison_one",
                        lambda record, model, cache=False, read_check=False: (
                            seen.append((cache, read_check)), {"recordId": record["recordId"]})[1])
    monkeypatch.setattr(scanner, "_MODEL_COMPARISON", {"status": "RUNNING", "jobId": "j"})
    scanner._market_brief_model_comparison_worker("j", SOL, 3, True)
    assert seen == [(True, True), (True, False), (True, False)]
    seen.clear()
    scanner._market_brief_model_comparison_worker("j", SOL, 2)
    assert seen == [(False, False), (False, False)]


def test_comparison_cache_request_serializes_for_the_candidate(offline):  # noqa: F811
    recorder, reserved = offline
    diag = {}
    user = "規則と材料の全文"
    scanner._openai_prose(user, max_out=5200, system="voice", purpose="manual_api", model=SOL,
                          diagnostic=diag, confirmed=True, cache_prefix_chars=len(user),
                          comparison_cache=True)
    assert diag["outcome"] == "ok" and len(recorder.sent) == 1
    body = recorder.sent[0]
    assert body["model"] == SOL and body["prompt_cache_options"] == {"mode": "explicit"}
    assert body["input"] == [{"role": "user", "content": [
        {"type": "input_text", "text": user, "prompt_cache_breakpoint": {"mode": "explicit"}}]}]
    assert "service_tier" not in body
    assert reserved[-1][0] == "manual_api" and reserved[-1][1]["confirmation"] is True


def test_production_brief_on_sol_stays_without_the_cache(offline):  # noqa: F811
    recorder, _ = offline
    # The production brief names sol and its cache boundary is still None.
    assert SOL not in scanner._BRIEF_EXPLICIT_CACHE_MODELS
    assert scanner._OPENAI_JUDGMENT_MODEL == SOL
    assert scanner._brief_cache_prefix(SOL, "facts") is None
    # The trial flag opens the shape only for the comparison lane and models.
    for model, purpose in ((SOL, "market_brief"), ("gpt-5.6-sol", "manual_api"),
                           ("gpt-6-astra", "manual_api"), (SOL, "ai_judgment")):
        with pytest.raises(ValueError, match="brief_cache_boundary_invalid"):
            scanner._openai_prose_call(SimpleNamespace(), model, "p", "facts", purpose=purpose,
                                       cache_prefix_chars=5, comparison_cache=True)
    with pytest.raises(ValueError, match="brief_cache_boundary_invalid"):
        scanner._openai_prose_call(SimpleNamespace(), SOL, "p", "facts", purpose="manual_api",
                                   cache_prefix_chars=5)          # no flag: refused
    # A production brief call that tried the flag sends nothing to the provider.
    diag = {}
    assert scanner._openai_prose("facts", purpose="market_brief", model=SOL, diagnostic=diag,
                                 cache_prefix_chars=5, comparison_cache=True) is None
    assert recorder.sent == [] and diag["outcome"] == "error"
    # Unconfirmed manual use with the flag is not the comparison either.
    diag = {}
    assert scanner._openai_prose("facts", purpose="manual_api", model=SOL, diagnostic=diag,
                                 cache_prefix_chars=5, comparison_cache=True) is None
    assert diag["reason"] == "production_model_not_allowed" and recorder.sent == []

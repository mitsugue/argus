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
                              accepted.get_json()["jobId"], "gpt-6.1-terra", 3)
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

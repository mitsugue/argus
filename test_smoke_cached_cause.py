"""Monitor the cached explanation contract without triggering generation."""
import copy

import pytest

import smoke_test


def available(status="not_generated"):
    data = {
        "moverCauseAvailability": {"status": "available", "reasonCode": None},
        "moverCause": {"causeStatus": "no_lead_yet"},
        "explanationStatus": status,
    }
    if status == "cached":
        data["explanationJa"] = "保存済みの説明"
    return data


def unavailable():
    return {
        "moverCauseAvailability": {
            "status": "unavailable", "reasonCode": "current_trading_session_unavailable",
        },
        "explanationStatus": "not_generated",
        "explanationNoteJa": "現在のセッションの根拠がなく、評価できません。",
    }


def check(monkeypatch, data, code=200):
    calls = []

    def cached_get(path, timeout):
        calls.append((path, timeout))
        return code, copy.deepcopy(data)

    monkeypatch.setattr(smoke_test, "_get", cached_get)
    result = smoke_test.v_public_explain_cached_only()
    assert calls == [("/api/argus/cause-attribution?symbol=8058&market=JP&explain=1", 40)]
    return result


@pytest.mark.parametrize("status", ["cached", "not_generated", "queued"])
def test_available_cached_read(monkeypatch, status):
    assert check(monkeypatch, available(status))[0]


def test_absent_session_reports_unavailable_not_successful_analysis(monkeypatch):
    ok, detail = check(monkeypatch, unavailable())
    assert ok
    assert "analysis unavailable: current_trading_session_unavailable" in detail
    assert "no AI generated" in detail


@pytest.mark.parametrize("patch", [
    {"moverCauseAvailability": None},
    {"moverCauseAvailability": {"status": "available", "reasonCode": "error"}},
    {"moverCause": None}, {"moverCause": {}},
    {"moverCause": {"causeStatus": "invented"}},
    {"explanationStatus": "live"},
    {"explanationStatus": "cached"},
    {"explanationStatus": "cached", "explanationJa": "  "},
    {"explanationStatus": "cached", "explanationJa": 123},
    {"explanationJa": "unexpected text"},
])
def test_invalid_available_contract_fails(monkeypatch, patch):
    assert not check(monkeypatch, {**available(), **patch})[0]


@pytest.mark.parametrize("reason", ["cached_evidence_unavailable", "unknown", None])
def test_storage_or_unknown_errors_still_fail(monkeypatch, reason):
    data = unavailable()
    data["moverCauseAvailability"]["reasonCode"] = reason
    assert not check(monkeypatch, data)[0]


@pytest.mark.parametrize("patch", [
    {"moverCause": {}}, {"moverCause": None},
    {"explanationStatus": "cached"}, {"explanationStatus": "queued"},
    {"explanationJa": "stale explanation"}, {"explanationNoteJa": ""},
])
def test_unavailable_cannot_claim_ladder_or_generation(monkeypatch, patch):
    assert not check(monkeypatch, {**unavailable(), **patch})[0]


def test_missing_ladder_is_not_a_session_exception(monkeypatch):
    data = available()
    del data["moverCause"]
    assert not check(monkeypatch, data)[0]


@pytest.mark.parametrize("code,data", [(503, unavailable()), (200, []), (200, None)])
def test_invalid_response_fails(monkeypatch, code, data):
    assert not check(monkeypatch, data, code)[0]

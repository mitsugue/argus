import json
import sys
import types

import pytest

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *a, **k: None
_moomoo.OpenSecTradeContext = lambda *a, **k: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)

import argus_market_ledger as market_ledger
import scanner


RAW = [{"PubDate": "2026-07-16", "StDate": "2026-07-06",
        "EnDate": "2026-07-10", "Section": "TokyoNagoya",
        "FrgnBal": 10, "IndBal": -20, "InvTrBal": 3,
        "TrstBnkBal": 4, "PropBal": -5}]


@pytest.fixture()
def isolated(monkeypatch):
    old = market_ledger.normalize_state(scanner._MARKET_LEDGER)
    old_token, old_key = scanner._ARGUS_ADMIN_TOKEN, scanner._JQUANTS_API_KEY
    scanner._MARKET_LEDGER.clear()
    scanner._MARKET_LEDGER.update(market_ledger.empty_state())
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "test-admin")
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "configured-not-a-real-key")
    monkeypatch.setattr(scanner, "_jquants_paginated", lambda *a, **k: RAW)
    monkeypatch.setattr(scanner, "_osint_persist", lambda: None)
    monkeypatch.setattr(scanner, "_journal", lambda *a, **k: None)
    yield
    scanner._MARKET_LEDGER.clear()
    scanner._MARKET_LEDGER.update(old)
    scanner._ARGUS_ADMIN_TOKEN, scanner._JQUANTS_API_KEY = old_token, old_key


def test_public_phase3_is_get_only_and_secret_safe(isolated):
    client = scanner.app.test_client()
    response = client.get("/api/argus/market-ledger")
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["phase3"]["sections"]) == 16
    assert len(body["phase3"]["today"]) <= 3
    assert body["automaticAiCalls"] == 0
    text = json.dumps(body)
    assert "configured-not-a-real-key" not in text
    assert client.post("/api/argus/market-ledger").status_code == 405


def test_jquants_backfill_requires_admin_and_defaults_to_dry_run(isolated):
    client = scanner.app.test_client()
    url = "/api/argus/admin/market-ledger/jquants-backfill"
    assert client.post(url, json={}).status_code == 401
    response = client.post(url, json={"from": "2026-01-01", "to": "2026-07-20"},
                           headers={"X-ARGUS-ADMIN-TOKEN": "test-admin"})
    body = response.get_json()
    assert response.status_code == 200
    assert body["dryRun"] is True
    assert body["candidateRows"] == 5
    assert len(scanner._MARKET_LEDGER["observations"]) == 0


def test_confirmed_backfill_is_idempotent_and_append_only(isolated):
    client = scanner.app.test_client()
    url = "/api/argus/admin/market-ledger/jquants-backfill"
    headers = {"X-ARGUS-ADMIN-TOKEN": "test-admin"}
    payload = {"from": "2026-01-01", "to": "2026-07-20",
               "dryRun": False, "confirm": True}
    first = client.post(url, json=payload, headers=headers)
    assert first.status_code == 200
    ids = [x["id"] for x in scanner._MARKET_LEDGER["observations"]]
    assert len(ids) == len(set(ids)) == 5
    second = client.post(url, json=payload, headers=headers)
    assert second.status_code == 200
    assert second.get_json()["status"] == "no_changes"
    assert [x["id"] for x in scanner._MARKET_LEDGER["observations"]] == ids


def test_real_commit_needs_explicit_confirmation(isolated):
    response = scanner.app.test_client().post(
        "/api/argus/admin/market-ledger/jquants-backfill",
        json={"dryRun": False},
        headers={"X-ARGUS-ADMIN-TOKEN": "test-admin"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "explicit_confirmation_required"

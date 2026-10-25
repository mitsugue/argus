"""個別銘柄の「調べる」ボタン(2026-10-25 オーナー)。"""
import json

import pytest

import scanner

TOKEN = "owner-test-token"


@pytest.fixture
def owner(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGUS_OWNER_SYNC_TOKEN", TOKEN)
    monkeypatch.setattr(scanner, "_osint_owner_path", lambda: str(tmp_path / "owner.json"))
    monkeypatch.setattr(scanner, "_OSINT_OWNER", {
        "restored": False, "day": None, "symbols": [], "results": {},
        "pending": [], "running": None})
    monkeypatch.setattr(scanner, "_scheduled_ai_skip", lambda provider, purpose: None)
    started = []
    monkeypatch.setattr(scanner, "_osint_owner_start_runner",
                        lambda: started.append("osint_owner_request"))
    return started


def _post(client, symbol, market="JP", token=TOKEN):
    return client.post("/api/argus/osint/research-request",
                       json={"symbol": symbol, "market": market, "ownerToken": token})


def test_requires_the_owner_key(owner):
    with scanner.app.test_client() as c:
        assert _post(c, "5803", token="wrong").status_code == 401
        assert _post(c, "5803", token="").status_code == 401
    assert owner == []


def test_rejects_a_mismatched_symbol_and_market(owner):
    with scanner.app.test_client() as c:
        assert _post(c, "5803", market="US").status_code == 400
        assert _post(c, "NVDA", market="JP").status_code == 400
        assert _post(c, "../x", market="US").status_code == 400


def test_one_turn_per_symbol_and_five_a_day(owner):
    with scanner.app.test_client() as c:
        first = _post(c, "5803")
        assert first.status_code == 202 and first.get_json()["status"] == "started"
        assert owner == ["osint_owner_request"]
        assert _post(c, "5803").get_json()["status"] == "running"
        scanner._OSINT_OWNER["pending"].clear()
        scanner._OSINT_OWNER["running"] = None
        assert _post(c, "5803").get_json()["status"] == "already_today"
        for sym in ("6965", "7011", "8058", "9984"):
            assert _post(c, sym).get_json()["status"] == "started"
        limited = _post(c, "6501").get_json()
        assert limited["status"] == "daily_limit" and limited["remainingToday"] == 0


def test_stopped_ai_never_queues(owner, monkeypatch):
    monkeypatch.setattr(scanner, "_scheduled_ai_skip",
                        lambda provider, purpose: {"status": "blocked"})
    with scanner.app.test_client() as c:
        assert _post(c, "5803").get_json()["status"] == "ai_stopped"
    assert owner == [] and scanner._OSINT_OWNER["symbols"] == []


def test_runner_saves_the_public_result_and_failed_runs_return_the_turn(owner, monkeypatch):
    def worker(syms):
        sym = syms[0]
        scanner._OSINT_AGENT_QUEUE.pop(sym, None)
        scanner._OSINT_STORE[sym] = {"symbol": sym, "asOf": "2026-10-25T00:00:00Z",
                                     "ownerNote": "private", "verifiedSources": [],
                                     "agentRuns": [{"provider": "gpt", "status": "failed",
                                                    "failureReasonRedacted": "empty_output"}]}
        scanner._OSINT_PROGRESS[sym] = {"stage": "complete" if sym == "5803" else "partial"}

    monkeypatch.setattr(scanner, "_osint_agents_worker", worker)
    monkeypatch.setitem(scanner._OSINT_STORE, "__keep__", {})
    scanner._OSINT_OWNER.update(day=scanner.datetime.now(scanner.TZ_JST).date().isoformat(),
                                symbols=["5803", "6965"], pending=[("5803", "JP"), ("6965", "JP")])
    scanner._osint_owner_runner()
    assert scanner._OSINT_OWNER["running"] is None
    assert scanner._OSINT_OWNER["symbols"] == ["5803"]
    saved = scanner._OSINT_OWNER["results"]["5803"]
    assert saved["complete"] is True and "ownerNote" not in json.dumps(saved)
    assert scanner._OSINT_OWNER["results"]["6965"]["complete"] is False
    assert scanner._OSINT_OWNER["results"]["6965"]["failureReason"] == "empty_output"
    assert scanner._osint_owner_status("6965")["failureReason"] == "empty_output"
    # Restored after a restart, and served when the in-memory store is empty.
    scanner._OSINT_OWNER.update(restored=False, results={})
    scanner._OSINT_STORE.pop("5803", None)
    with scanner.app.test_client() as c:
        body = c.get("/api/argus/osint/investigation?symbol=5803").get_json()
    assert body["status"] == "live" and body["investigation"]["symbol"] == "5803"
    assert body["ownerRequest"]["requestedToday"] is True


def test_the_screen_name_reaches_the_search(owner, monkeypatch):
    monkeypatch.setattr(scanner, "_OSINT_NAME_HINTS", {})
    monkeypatch.setattr(scanner, "get_japan_watchlist_snapshot", lambda: {"stocks": []})
    monkeypatch.setattr(scanner, "_jq_name_for", lambda code, **kw: "")
    with scanner.app.test_client() as c:
        c.post("/api/argus/osint/research-request",
               json={"symbol": "4493", "market": "JP", "ownerToken": TOKEN,
                     "name": "サイバーセキュリティクラウド<script>"})
    assert scanner._osint_profile("4493", "JP")["nameJa"] == "サイバーセキュリティクラウドscript"


def test_a_stock_without_a_theme_does_not_take_market_headlines(monkeypatch):
    pool = [{"title": "President Trump Just Proclaimed Tariffs"},
            {"title": "Prediction: Amazon Stock Will Skyrocket"},
            {"title": "New AI chip orders lift suppliers"},
            {"titleJa": "サイバーセキュリティクラウド 上方修正"}]
    monkeypatch.setattr(scanner, "_osint_pool_items", lambda: pool)
    monkeypatch.setattr(scanner, "get_cause_attribution", lambda sym, market: {})
    bare = {"valueChain": [], "sector": [],
            "globalCatalyst": ["4493 stock news", "custom silicon", "AI chip", "AI capex"]}
    cands, _counts, _flow = scanner._osint_retrieve("4493", "JP", bare)
    assert cands == []
    themed = {"valueChain": ["AI chip"], "sector": [], "globalCatalyst": ["AI capex"]}
    titles = [c["titleJa"] for c in scanner._osint_retrieve("6965", "JP", themed)[0]]
    assert titles == ["New AI chip orders lift suppliers"]

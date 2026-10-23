"""2026-10-22 (owner: moomoo is the primary US source): US symbol search uses the
moomoo stock/ETF list the bridge sends once a day, not Twelve Data."""
import importlib.util
import sys
import types

import pytest

import argus_moomoo_us as mu
import scanner


def _list(extra=()):
    rows = [["AAPL", "Apple Inc.", "stock", "US_NASDAQ"],
            ["AAPU", "Direxion Daily AAPL Bull 2X", "etf", "US_NASDAQ"],
            ["APLE", "Apple Hospitality REIT", "stock", "US_NYSE"],
            ["AAPLX", "Apple OTC Shadow", "stock", "US_PINK"],
            ["NVDA", "NVIDIA Corp", "stock", "US_NASDAQ"],
            ["SPY", "SPDR S&P 500 ETF Trust", "etf", "US_NYSE_ARCA"]]
    rows += [[f"Z{i:04d}", f"Filler {i}", "stock", "US_NYSE"] for i in range(mu.MIN_COMPLETE_SYMBOLS)]
    return rows + list(extra)


def test_ranking_puts_the_exact_symbol_and_listed_stocks_first():
    rows, rejected = mu.normalize_symbol_rows(_list([["bad sym", "x", "stock", ""],
                                                     ["AAPL", "dup", "stock", "US_NYSE"],
                                                     ["AAPLB", "Apple Class B", "stock", "US_NYSE"]]))
    assert rejected == 1 and sum(1 for r in rows if r[0] == "AAPL") == 1
    found = [r["symbol"] for r in mu.search_symbols(rows, "aapl")]
    # exact → listed prefix → OTC prefix → name contains
    assert found == ["AAPL", "AAPLB", "AAPLX", "AAPU"]
    by_name = [r["symbol"] for r in mu.search_symbols(rows, "apple")]
    assert by_name[:2] == ["AAPL", "APLE"] and by_name[-1] == "AAPLX"
    assert mu.search_symbols(rows, "nvidia")[0] == {
        "symbol": "NVDA", "name": "NVIDIA Corp", "nameJa": "", "exchange": "US_NASDAQ",
        "type": "us_equity", "instrumentKind": "stock"}


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(scanner, "_require_admin", lambda: (True, None, 200))
    monkeypatch.setattr(scanner, "_verify_bridge_signature", lambda raw: (True, "test"))
    monkeypatch.setattr(scanner, "_US_SYMBOLS", {"rows": None, "receivedAt": None, "count": 0,
                                                 "loaded": False, "lastSaveError": None})
    monkeypatch.setattr(scanner, "_US_SYMBOLS_PENDING", {"runId": None, "parts": 0,
                                                         "received": {}, "startedAt": 0.0})
    monkeypatch.setattr(scanner, "_us_symbols_path", lambda: None)
    monkeypatch.setattr(scanner, "_SEARCH_Q_CACHE", {})
    monkeypatch.setattr(scanner, "_moomoo_daily_plan", lambda now_epoch=None: ([], __import__("datetime").date(2026, 10, 22)))
    monkeypatch.setattr(scanner, "_td_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Twelve Data")))
    return scanner.app.test_client()


def _send(client, rows, parts=2, run_id="run-0001"):
    size = (len(rows) + parts - 1) // parts
    out = None
    for part in range(parts):
        out = client.post("/api/argus/us-reference-push", json={
            "kind": "symbolList", "runId": run_id, "part": part, "parts": parts,
            "rows": rows[part * size:(part + 1) * size]}).get_json()
    return out


def test_search_waits_for_the_list_then_uses_it_without_twelve_data(server):
    client = server
    body = client.get("/api/argus/symbol-search?q=apple&market=US").get_json()
    assert body["status"] == "unavailable" and body["results"] == []
    plan = client.get("/api/argus/us-universe?scope=reference").get_json()
    assert plan["symbolListNeeded"] is True
    first = client.post("/api/argus/us-reference-push", json={
        "kind": "symbolList", "runId": "run-0001", "part": 0, "parts": 2, "rows": _list()[:3]}).get_json()
    assert first["status"] == "partial"
    done = client.post("/api/argus/us-reference-push", json={
        "kind": "symbolList", "runId": "run-0001", "part": 1, "parts": 2, "rows": _list()[3:]}).get_json()
    assert done["status"] == "replaced" and done["count"] == len(_list())
    body = client.get("/api/argus/symbol-search?q=apple&market=US").get_json()
    assert body["status"] == "live" and body["results"][0]["symbol"] == "AAPL"
    assert client.get("/api/argus/us-universe?scope=reference").get_json()["symbolListNeeded"] is False


def test_a_short_or_broken_list_never_replaces_a_good_one(server):
    client = server
    assert _send(client, _list())["status"] == "replaced"
    assert _send(client, _list()[:10], run_id="run-0002")["status"] == "too_few"
    assert scanner._US_SYMBOLS["count"] == len(_list())
    bad = client.post("/api/argus/us-reference-push", json={
        "kind": "symbolList", "runId": "x", "part": 0, "parts": 1, "rows": []})
    assert bad.status_code == 400


def test_the_list_survives_a_restart(server, tmp_path, monkeypatch):
    client = server
    monkeypatch.setattr(scanner, "_us_symbols_path", lambda: str(tmp_path / "moomoo_us_symbols.json"))
    _send(client, _list())
    scanner._US_SYMBOLS.update(rows=None, loaded=False, count=0, receivedAt=None)
    body = client.get("/api/argus/symbol-search?q=NVDA&market=US").get_json()
    assert body["results"][0]["symbol"] == "NVDA"


def _bridge(monkeypatch):
    monkeypatch.setitem(sys.modules, "moomoo", types.SimpleNamespace(
        OpenQuoteContext=None, RET_OK=0, Market=types.SimpleNamespace(US="US"),
        SecurityType=types.SimpleNamespace(STOCK="STOCK", ETF="ETF")))
    spec = importlib.util.spec_from_file_location("moomoo_push_symbols_test", "bridge/moomoo_push.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DF:
    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, row


def test_bridge_sends_stocks_and_etfs_in_parts(monkeypatch):
    m = _bridge(monkeypatch)
    monkeypatch.setattr(m, "SYMBOL_LIST_PART_ROWS", 2)

    class QC:
        def get_stock_basicinfo(self, market, security_type):
            assert market == "US"
            if security_type == "STOCK":
                return 0, _DF([{"code": "US.AAPL", "name": "Apple Inc.", "delisting": False,
                                "exchange_type": "US_NASDAQ"},
                               {"code": "US.OLD", "name": "Gone", "delisting": True},
                               {"code": "US.NVDA", "name": "NVIDIA Corp", "delisting": False,
                                "exchange_type": "US_NASDAQ"}])
            return 0, _DF([{"code": "US.SPY", "name": "SPDR S&P 500", "delisting": False,
                            "exchange_type": "US_NYSE_ARCA"}])

    posted = []
    monkeypatch.setattr(m, "_post_reference", lambda payload: posted.append(payload) or True)
    state = {}
    assert m.run_symbol_list_job(QC(), state=state) == 3
    assert [p["part"] for p in posted] == [0, 1] and {p["parts"] for p in posted} == {2}
    assert len({p["runId"] for p in posted}) == 1
    assert [r[0] for p in posted for r in p["rows"]] == ["AAPL", "NVDA", "SPY"]
    assert posted[1]["rows"][0] == ["SPY", "SPDR S&P 500", "etf", "US_NYSE_ARCA"]
    assert state["symbolListStatus"] == "ok" and state["symbolListCount"] == 3


def test_bridge_does_not_send_a_half_list(monkeypatch):
    m = _bridge(monkeypatch)

    class QC:
        def get_stock_basicinfo(self, market, security_type):
            return (0, _DF([{"code": "US.AAPL", "name": "Apple"}])) if security_type == "STOCK" \
                else (-1, "error")

    monkeypatch.setattr(m, "_post_reference", lambda payload: (_ for _ in ()).throw(AssertionError()))
    state = {}
    assert m.run_symbol_list_job(QC(), state=state) == 0 and state["symbolListStatus"] == "provider_error"

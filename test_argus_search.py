"""ARGUS v11.1 — symbol search relevance (JP ranking). Offline: monkeypatches the
J-Quants master so it needs no key/network."""
import scanner

MASTER = [
    # a 三菱UFJ-MAXIS ETF whose name STARTS WITH 三菱 (the real-world foil for "三菱")
    {"code4": "1346", "ja": "三菱UFJ-MAXIS 日経225上場投信", "en": "MAXIS NIKKEI 225 ETF", "mkt": "ETF"},
    {"code4": "8058", "ja": "三菱商事", "en": "Mitsubishi Corp", "mkt": "P"},
    {"code4": "8031", "ja": "三井物産", "en": "Mitsui & Co", "mkt": "P"},
    {"code4": "7011", "ja": "三菱重工業", "en": "Mitsubishi Heavy", "mkt": "P"},
    {"code4": "285A", "ja": "キオクシア", "en": "Kioxia", "mkt": "P"},
]


def test_jp_exact_code_ranks_first(monkeypatch):
    monkeypatch.setattr(scanner, "_jq_master", lambda: MASTER)
    res, st = scanner._search_jp("8058")
    assert st == "live"
    assert res[0]["symbol"] == "8058" and res[0]["nameJa"] == "三菱商事"


def test_jp_alphanumeric_code(monkeypatch):
    monkeypatch.setattr(scanner, "_jq_master", lambda: MASTER)
    res, _ = scanner._search_jp("285A")
    assert res and res[0]["symbol"] == "285A"


def test_jp_name_query_surfaces_equities_before_etf(monkeypatch):
    monkeypatch.setattr(scanner, "_jq_master", lambda: MASTER)
    res, _ = scanner._search_jp("三菱")
    syms = [r["symbol"] for r in res]
    # both 三菱 equities present; the unrelated 三井 must not appear
    assert "8058" in syms and "7011" in syms
    assert "8031" not in syms
    # the operating companies must rank BEFORE the 三菱UFJ-MAXIS ETF (1346)
    assert syms.index("8058") < syms.index("1346")
    assert syms.index("7011") < syms.index("1346")


def test_jp_empty_master_is_unavailable(monkeypatch):
    monkeypatch.setattr(scanner, "_jq_master", lambda: [])
    res, st = scanner._search_jp("三菱")
    assert res == [] and st == "unavailable"

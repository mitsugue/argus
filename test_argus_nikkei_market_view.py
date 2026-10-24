"""日経平均そのものを市場の正規の値にする第2段(2026-10-23)の配線の試験。

オーナー「全て日経平均そのもので見ること」。答え合わせ用データと検証済みの
スナップショットは日経平均で作り、名前は INDEX。現在の判断の対象(1321)は
第3段で移すまで、その日足の根拠として 1321 の検証済みビューも作り続ける。"""
import inspect
import json
import pathlib
import sys
import types

sys.modules.setdefault("moomoo", types.SimpleNamespace(
    OpenQuoteContext=object, OpenSecTradeContext=object, RET_OK=0))
import scanner  # noqa: E402
import argus_market_replay  # noqa: E402


def test_instrument_types_name_the_index_as_an_index():
    assert scanner._market_instrument_type("N225") == "INDEX"
    assert scanner._market_instrument_type("1321") == "ETF"
    assert scanner._market_instrument_type("SPY") == "ETF"
    assert scanner._market_instrument_type("7203") == "EQUITY"
    assert scanner._market_display_name("N225") == "日経平均株価(指数)"
    assert scanner._market_display_name("1321") == "日経225 ETF"


def test_replay_rejects_an_unknown_instrument_type():
    try:
        argus_market_replay.build_context([], symbol="N225", market="JP",
                                          horizon=5, asset_type="FUND")
    except ValueError as exc:
        assert str(exc) == "unsupported_instrument_type"
    else:
        raise AssertionError("unknown instrument type accepted")


def test_natural_tick_makes_the_nikkei_primary_and_no_longer_builds_1321():
    mission = inspect.getsource(scanner._api_argus_admin_missions_tick_impl)
    assert '("M6", "jp_primary", "N225", "JP")' in mission
    assert 'market_scope=_market_symbol == "N225"' in mission
    assert '"1321", "jp_primary"' not in mission
    # Step 3 (owner approval 2026-10-23): the judgment's subject is the Nikkei
    # 225 too, so the separate 1321 view for the judgment is no longer built.
    assert '_precompute_verified_market_view("1321"' not in mission


def test_release_matrix_moves_its_jp_primary_to_the_nikkei():
    seed = inspect.getsource(scanner._release_seed_verified_market_views)
    assert '("N225", "JP", True)' in seed
    assert '"1321"' not in seed
    contract = json.loads(pathlib.Path(
        "release/v13-snapshot-readiness-contract.json").read_text())
    identities = [row["identity"] for row in contract["snapshots"]]
    assert contract["snapshotExpected"] == 12 == len(set(identities))
    assert [i for i in identities if i.startswith("market-chart:N225:")] == [
        "market-chart:N225:1D", "market-chart:N225:5D", "market-chart:N225:20D"]
    assert not any(":1321:" in identity for identity in identities)
    assert all(row["requiredness"] == "SEED_REQUIRED" for row in contract["snapshots"])


def test_public_market_view_defaults_to_the_nikkei_and_still_reads_1321():
    route = inspect.getsource(scanner.api_argus_chart_intelligence)
    assert 'request.args.get("symbol") or "N225"' in route
    assert '{"N225", "1321", "1306", "SPY", "QQQ"}' in route


def test_nikkei_rows_wait_for_an_acquisition_time(monkeypatch):
    rows = [{"instrumentId": "NIKKEI_225_INDEX", "date": f"2026-08-{day:02d}",
             "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1,
             "availableFrom": f"2026-08-{day:02d}T07:00:00Z", "adjusted": False}
            for day in range(1, 31)] + [
            {"instrumentId": "NIKKEI_225_INDEX", "date": "2026-09-01",
             "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1,
             "availableFrom": "2026-09-01T07:00:00Z", "adjusted": False}]
    monkeypatch.setattr(scanner, "_N225_ANALOG_HISTORY", {})
    monkeypatch.setitem(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE, "^N225",
                        {"data": rows, "expires": 0})
    monkeypatch.setattr(scanner, "_N225_CHART_KNOWLEDGE",
                        {"contentDigest": None, "knownAt": None})
    # No acquisition time: the bars cannot pass the time check, so none.
    assert scanner._n225_chart_rows() == []
    monkeypatch.setitem(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE, "^N225",
                        {"data": rows, "expires": 0,
                         "acquiredAt": "2026-09-01T07:30:00Z"})
    chart = scanner._n225_chart_rows()
    assert len(chart) == 31
    assert {row["knownAt"] for row in chart} == {"2026-09-01T07:30:00.000000Z"}
    assert {row["source"] for row in chart} == {"yahoo_index"}
    # A newer receipt of different bars is a new revision.
    changed = [dict(row) for row in rows]
    changed[-1]["close"] = 2.0
    monkeypatch.setitem(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE, "^N225",
                        {"data": changed, "expires": 0,
                         "acquiredAt": "2026-09-02T07:30:00Z"})
    assert {row["knownAt"] for row in scanner._n225_chart_rows()} == {
        "2026-09-02T07:30:00.000000Z"}


def test_producer_restores_saved_history_after_a_restart(monkeypatch):
    """The release seed runs before the collection lane: the producer reads the
    saved history (local file) and, when it ends before the latest completed
    session, may refresh the received window; a cached read restores the
    saved history but never requests the provider."""
    rows = [{"instrumentId": "NIKKEI_225_INDEX", "date": f"2026-08-{day:02d}",
             "open": 1.0, "high": 1.0, "low": 1.0, "close": float(day), "volume": 1,
             "availableFrom": f"2026-08-{day:02d}T07:00:00Z", "adjusted": False}
            for day in range(1, 31)]
    calls = []
    monkeypatch.setattr(scanner, "_N225_ANALOG_HISTORY", {})
    monkeypatch.setattr(scanner, "_JP_MARKET_ENGINE_INDEX_OHLCV_CACHE", {})
    monkeypatch.setattr(scanner, "_N225_CHART_KNOWLEDGE",
                        {"contentDigest": None, "knownAt": None})

    def restore():
        calls.append("restore")
        scanner._N225_ANALOG_HISTORY.update(
            data=rows, currentSourceAcquiredAt="2026-08-30T08:00:00Z")
        return None

    def yahoo(symbol, instrument, *, fetch=False, **kwargs):
        calls.append(("yahoo", symbol, fetch))
        return []

    monkeypatch.setattr(scanner, "_yahoo_index_ohlcv", yahoo)
    # Nothing held at all: nothing is requested (the collection lane owns the
    # first acquisition) and there are no rows to publish.
    monkeypatch.setattr(scanner, "_n225_analog_history_restore", lambda: None)
    assert scanner._chart_history("N225", "JP") == []
    assert calls == []
    monkeypatch.setattr(scanner, "_n225_analog_history_restore", restore)
    cached = scanner._chart_history_cached("N225", "JP")
    assert calls == ["restore"]
    produced = scanner._chart_history("N225", "JP")
    assert calls == ["restore", "restore", ("yahoo", "^N225", True)]
    assert cached == produced and len(produced) == 30
    assert produced[-1]["close"] == 30.0
    assert {row["knownAt"] for row in produced} == {"2026-08-30T08:00:00.000000Z"}


def _browser_portable_number(value):
    """The browser's portableNumber: Number#toFixed(8) on the exact binary
    value, a tie resolved to the larger digit (here: positive prices)."""
    from decimal import Decimal, ROUND_HALF_UP
    text = format(Decimal(value).quantize(Decimal("1e-8"), rounding=ROUND_HALF_UP), "f")
    text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def test_nikkei_prices_hash_the_same_in_python_and_the_browser(monkeypatch):
    """2026-10-24: Yahoo's ^N225 float noise (17278.119140625) sat on an
    8-decimal rounding tie, so the browser rejected every verified Nikkei view
    (payload_hash_mismatch). Prices are kept at the index's two decimals."""
    import argus_verified_snapshot
    noisy = 17278.119140625
    assert argus_verified_snapshot._portable_number(noisy) != _browser_portable_number(noisy)
    rows = [{"instrumentId": "NIKKEI_225_INDEX", "date": f"2026-08-{day:02d}",
             "open": 17346.390625, "high": 17414.2109375, "low": noisy,
             "close": 17336.419921875, "volume": 107600000,
             "availableFrom": f"2026-08-{day:02d}T07:00:00Z", "adjusted": False}
            for day in range(1, 31)]
    monkeypatch.setattr(scanner, "_N225_ANALOG_HISTORY", {})
    monkeypatch.setitem(scanner._JP_MARKET_ENGINE_INDEX_OHLCV_CACHE, "^N225",
                        {"data": rows, "expires": 0, "acquiredAt": "2026-09-01T07:30:00Z"})
    monkeypatch.setattr(scanner, "_N225_CHART_KNOWLEDGE", {"contentDigest": None, "knownAt": None})
    chart = scanner._n225_chart_rows()
    assert len(chart) == 30
    for bar in chart:
        for key in ("open", "high", "low", "close"):
            assert round(bar[key], 2) == bar[key]
            assert argus_verified_snapshot._portable_number(bar[key]) == \
                _browser_portable_number(bar[key])
        assert bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]

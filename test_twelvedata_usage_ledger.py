"""2026-10-21 (owner): Twelve Data use is measured per UTC day across every call and survives restarts."""
from datetime import datetime

import pytz

import scanner


class Response:
    status_code = 200


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_cost_policy_durable_enabled", lambda: True)
    monkeypatch.setitem(scanner._DURABILITY_PATHS, "root", str(tmp_path))
    monkeypatch.setattr(scanner, "_TD_USAGE", {"days": None, "lastSaveError": None})
    monkeypatch.setattr(scanner.requests, "get", lambda url, **kw: Response())


def test_calls_and_credits_are_counted_per_day_and_kept(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    scanner._td_get("quote", scanner._TWELVEDATA_QUOTE, params={"symbol": "NVDA,AAPL,MU", "apikey": "k"})
    scanner._td_get("time_series", scanner._TWELVEDATA_TS, params={"symbol": "SPY", "apikey": "k"})
    day = datetime.now(pytz.utc).strftime("%Y-%m-%d")
    row = scanner._TD_USAGE["days"][day]
    assert row["calls"] == 2 and row["credits"] == 4 and row["byKind"]["quote"]["credits"] == 3
    monkeypatch.setattr(scanner, "_TD_USAGE", {"days": None, "lastSaveError": None})      # a restart
    assert scanner._td_usage_days()[day]["credits"] == 4


def test_a_failed_call_is_still_counted_as_an_error(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    def boom(url, **kw):
        raise TimeoutError()
    monkeypatch.setattr(scanner.requests, "get", boom)
    try:
        scanner._td_get("quote", scanner._TWELVEDATA_QUOTE, params={"symbol": "NVDA"})
    except TimeoutError:
        pass
    day = datetime.now(pytz.utc).strftime("%Y-%m-%d")
    assert scanner._TD_USAGE["days"][day]["errors"] == 1


def test_every_twelve_data_call_goes_through_the_counter():
    import inspect
    source = inspect.getsource(scanner)
    import re
    direct = [m for m in re.finditer(r"requests\.get\(\s*(_TWELVEDATA_|f?\"https://api\.twelvedata)", source)]
    assert direct == []

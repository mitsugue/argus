"""Resident warm for the owner's JP names outside the curated list.

The public japan-watchlist route is cache-only. Until now the only fetch path
for the owner's own codes was the admin collect (GitHub cron, hours late,
and it forgets device-requested codes on restart). The scheduler tick is the
bounded background authority: one batch per five minutes, capped, repeated
per code every six hours, never raising.
"""
from unittest import mock

import pytest

import scanner


@pytest.fixture(autouse=True)
def _reset():
    saved = dict(scanner._JP_OWNER_WARM_STATE)
    saved_warmed = dict(scanner._JP_OWNER_WARM_STATE.get("warmedAtMonotonic") or {})
    scanner._JP_OWNER_WARM_STATE.clear()
    scanner._JP_OWNER_WARM_STATE.update({
        "lastAttemptMonotonic": None, "warmedAtMonotonic": {},
        "lastCodes": (), "lastResult": None, "lastAt": None})
    try:
        yield
    finally:
        scanner._JP_OWNER_WARM_STATE.clear()
        scanner._JP_OWNER_WARM_STATE.update(saved)
        scanner._JP_OWNER_WARM_STATE["warmedAtMonotonic"] = saved_warmed


def _ready(monkeypatch, codes):
    monkeypatch.setitem(scanner._STARTUP, "state", "ready")
    monkeypatch.setattr(scanner, "_owner_jp_symbols_for_warm",
                        lambda limit=None: tuple(codes))


def test_tick_warms_owner_codes_once_per_window_and_repeats_after_six_hours(monkeypatch):
    _ready(monkeypatch, ["7203", "6758"])
    core = mock.Mock(return_value={"status": "delayed"})
    history = mock.Mock(return_value={"closes": [1.0]})
    monkeypatch.setattr(scanner, "_get_japan_watchlist_core", core)
    monkeypatch.setattr(scanner, "_jq_price_history", history)

    first = scanner._jp_owner_quote_warm_tick(now_monotonic=1_000.0)
    assert first == {"status": "warmed", "codes": ["7203", "6758"], "bars": 2}
    core.assert_called_once_with(["7203", "6758"], allow_provider_fetch=True)
    assert history.call_count == 2

    # Within five minutes nothing runs again.
    assert scanner._jp_owner_quote_warm_tick(now_monotonic=1_200.0) == {"status": "throttled"}
    # After the window the same codes are still fresh (six-hour repeat).
    assert scanner._jp_owner_quote_warm_tick(now_monotonic=2_000.0) == {"status": "nothing_due"}
    assert core.call_count == 1
    # A newly requested code is warmed on the next window.
    _ready(monkeypatch, ["7203", "6758", "9432"])
    third = scanner._jp_owner_quote_warm_tick(now_monotonic=2_400.0)
    assert third == {"status": "warmed", "codes": ["9432"], "bars": 1}
    # Six hours later every code is due again.
    assert scanner._jp_owner_quote_warm_tick(
        now_monotonic=1_000.0 + 6 * 3600 + 1)["codes"] == ["7203", "6758"]


def test_tick_is_bounded_by_the_dynamic_cap(monkeypatch):
    codes = [f"{1000 + i}" for i in range(scanner._JP_DYN_MAX + 7)]
    _ready(monkeypatch, codes)
    core = mock.Mock(return_value={"status": "delayed"})
    monkeypatch.setattr(scanner, "_get_japan_watchlist_core", core)
    monkeypatch.setattr(scanner, "_jq_price_history", lambda code: None)
    result = scanner._jp_owner_quote_warm_tick(now_monotonic=10.0)
    assert len(result["codes"]) == scanner._JP_DYN_MAX
    assert result["bars"] == 0


def test_tick_never_runs_before_restore_or_without_codes(monkeypatch):
    core = mock.Mock()
    monkeypatch.setattr(scanner, "_get_japan_watchlist_core", core)
    monkeypatch.setitem(scanner._STARTUP, "state", "bootstrapping")
    monkeypatch.setattr(scanner, "_owner_jp_symbols_for_warm", lambda limit=None: ("7203",))
    assert scanner._jp_owner_quote_warm_tick(now_monotonic=1.0) == {"status": "not_ready"}
    _ready(monkeypatch, [])
    assert scanner._jp_owner_quote_warm_tick(now_monotonic=1.0) == {"status": "nothing_due"}
    core.assert_not_called()


def test_tick_records_a_failure_and_never_raises(monkeypatch):
    _ready(monkeypatch, ["7203"])
    monkeypatch.setattr(scanner, "_get_japan_watchlist_core",
                        mock.Mock(side_effect=RuntimeError("provider down")))
    logs = []
    monkeypatch.setattr(scanner, "add_log", logs.append)
    result = scanner._jp_owner_quote_warm_tick(now_monotonic=5.0)
    assert result == {"status": "failed", "errorClass": "RuntimeError"}
    assert scanner._JP_OWNER_WARM_STATE["lastResult"] == "RuntimeError"
    assert logs and "provider down" not in logs[0]


def test_scheduler_dispatches_the_warm_next_to_the_residency_tick():
    import inspect
    source = inspect.getsource(scanner.run_scheduler)
    assert '"jp_owner_quote_warm"' in source
    assert "_jp_owner_quote_warm_tick" in source
    assert source.index("residency_ai_tick") < source.index("jp_owner_quote_warm")

"""2026-10-24: once the next weekly CFTC report is due, retry hourly instead of waiting 20 hours."""
from datetime import datetime, timezone

import scanner


def _latest(monkeypatch, position_date):
    monkeypatch.setattr(scanner.jp_market_positioning, "latest_from_ledger",
                        lambda ledger, cutoff=None: {"positionDate": position_date})


def test_due_after_the_next_friday_release(monkeypatch):
    _latest(monkeypatch, "2026-10-13")
    assert not scanner._cftc_jpy_next_report_due(datetime(2026, 10, 23, 19, 0, tzinfo=timezone.utc))
    assert scanner._cftc_jpy_next_report_due(datetime(2026, 10, 23, 19, 45, tzinfo=timezone.utc))
    assert scanner._cftc_jpy_next_report_due(datetime(2026, 10, 24, 0, 40, tzinfo=timezone.utc))


def test_not_due_once_the_new_week_is_held(monkeypatch):
    _latest(monkeypatch, "2026-10-20")
    assert not scanner._cftc_jpy_next_report_due(datetime(2026, 10, 24, 0, 40, tzinfo=timezone.utc))


def test_unknown_position_keeps_the_old_interval(monkeypatch):
    _latest(monkeypatch, None)
    assert not scanner._cftc_jpy_next_report_due(datetime(2026, 10, 24, 0, 40, tzinfo=timezone.utc))


def test_autorefresh_retries_hourly_when_the_next_week_is_due(monkeypatch):
    _latest(monkeypatch, "2026-10-13")
    calls = []
    monkeypatch.setattr(scanner, "_CFTC_JPY_STATE", {"lastAttemptAt": None, "lastSuccessfulAcquisitionAt": None,
                        "status": "AVAILABLE", "persistenceStatus": "VERIFIED",
                        "lastAttemptMonotonic": scanner.time.monotonic() - 2 * 3600})
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(RuntimeError("offline")))
    result = scanner._cftc_jpy_autorefresh()
    assert calls and result["status"] == "FAILED"

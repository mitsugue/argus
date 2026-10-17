"""Seven-condition date acquisition must cover its actual ten-session window."""
from datetime import datetime
from unittest.mock import Mock

import pytest
import scanner


@pytest.mark.parametrize('stamp,required', [
    ('2026-09-24T18:00:00+09:00', ['2026-09-08','2026-09-09','2026-09-10','2026-09-11',
      '2026-09-14','2026-09-15','2026-09-16','2026-09-17','2026-09-18','2026-09-24']),
    ('2026-09-28T09:00:00+09:00', ['2026-09-09','2026-09-10','2026-09-11','2026-09-14',
      '2026-09-15','2026-09-16','2026-09-17','2026-09-18','2026-09-24','2026-09-25']),
    ('2026-10-11T08:00:00+09:00', ['2026-09-28','2026-09-29','2026-09-30','2026-10-01',
      '2026-10-02','2026-10-05','2026-10-06','2026-10-07','2026-10-08','2026-10-09']),
])
def test_warm_covers_last_ten_closed_sessions_with_existing_request_budget(monkeypatch, stamp, required):
    now = datetime.fromisoformat(stamp)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.setattr(scanner, 'datetime', Clock)
    monkeypatch.setattr(scanner, '_JQUANTS_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr(scanner, '_N225_ANALOG_HISTORY', {'calendar': []})
    cache = {'rows': [], 'fetchedAt': None, 'expires': 0, 'source': 'cold', 'schemaSample': None}
    monkeypatch.setattr(scanner, '_JP_MARKET_ENGINE_STATEMENTS_CACHE', cache)
    acquire = Mock(return_value=[])
    retain = Mock()
    monkeypatch.setattr(scanner, '_jquants_paginated', acquire)
    monkeypatch.setattr(scanner, '_jp_earnings_history_retain', retain)
    scanner._jp_market_engine_statements_rows(warm=True)
    dates = [call.args[1]['date'] for call in acquire.call_args_list]
    assert set(required) <= set(dates)
    assert len(dates) == len(set(dates)) <= 14
    assert all(day <= stamp[:10] for day in dates)
    assert dates[0] == stamp[:10]
    assert [call.kwargs['query_date'] for call in retain.call_args_list] == dates
    # Even an empty successful date response is required coverage. A holiday
    # outside the ten sessions cannot stand in for a missing session receipt.
    from argus_warning_candidates import earnings_rule
    members = [str(1000 + i) for i in range(225)]
    from datetime import date, timedelta
    first = date.fromisoformat(required[0])
    earlier = next((first - timedelta(days=i)).isoformat() for i in range(1, 10)
                   if scanner.argus_market_clock.canonical_trading_day(
                       scanner.argus_market_clock.JP_EQUITY, first - timedelta(days=i)))
    result = earnings_rule(sessions=[earlier, *required], financial_rows=[],
        membership_by_day={day: members for day in required}, stock_bars={}, topix_rows=[],
        coverage_by_day={day: {'complete':True, 'memberCodes':members, 'knownAt':stamp}
                         for day in dates}, cutoff=stamp)
    assert result['state'] == 'CLEAR' and result['goodEarningsCount'] == 0
    assert result['underperformedCount'] is None


def test_cached_read_never_selects_dates_or_acquires(monkeypatch):
    old = [{'Code':'10000', 'DiscDate':'2026-10-07'}]
    monkeypatch.setattr(scanner, '_JP_MARKET_ENGINE_STATEMENTS_CACHE', {'rows':old})
    forbidden = Mock(side_effect=AssertionError('GET reads cached rows only'))
    monkeypatch.setattr(scanner, '_jp_market_engine_statements_dates', forbidden)
    monkeypatch.setattr(scanner, '_jquants_paginated', forbidden)
    assert scanner._jp_market_engine_statements_rows() is old
    forbidden.assert_not_called()


def test_unknown_calendar_preserves_saved_rows_and_does_not_acquire(monkeypatch):
    monkeypatch.setattr(scanner, '_JQUANTS_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr(scanner, '_jp_exchange_sessions', lambda *args: ([], True))
    old = [{'Code':'10000', 'DiscDate':'2026-10-07'}]
    cache = {'rows':old, 'expires':0, 'source':'saved'}
    monkeypatch.setattr(scanner, '_JP_MARKET_ENGINE_STATEMENTS_CACHE', cache)
    acquire = Mock(side_effect=AssertionError('unknown calendar cannot collect guessed dates'))
    monkeypatch.setattr(scanner, '_jquants_paginated', acquire)
    assert scanner._jp_market_engine_statements_rows(warm=True) is old
    assert cache['source'] == 'calendar_unavailable'
    acquire.assert_not_called()

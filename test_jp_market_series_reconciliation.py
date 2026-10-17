import json
from datetime import date, timedelta

import pytest

import jp_market_series_reconciliation as rec


def weekdays(first, last, *, closed=()):
    day, out = date.fromisoformat(first), []
    while day <= date.fromisoformat(last):
        if day.weekday() < 5 and day.isoformat() not in closed:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


OPEN = weekdays('2020-09-01', '2026-10-16', closed={'2026-10-12', '2020-09-21', '2020-09-22'})


def bars(days, **extra):
    return [{'date': d, 'close': 100.0, **extra} for d in days]


def test_equal_count_with_a_duplicate_still_finds_the_gap():
    days = [d for d in OPEN if '2026-10-01' <= d <= '2026-10-16']
    rows = bars(days[:3] + days[4:]) + bars([days[0]])
    row = rec.reconcile_series('price_series:nikkei', rows, open_days=OPEN)
    assert row['rows'] == len(days)                         # the count alone looks complete
    assert row['status'] == 'GAPS_FOUND'
    assert row['missingDates']['first'] == [days[3]] and row['duplicatedDates']['first'] == [days[0]]


def test_holiday_row_is_unexpected_and_store_is_not_changed():
    days = [d for d in OPEN if '2026-10-05' <= d <= '2026-10-16'] + ['2026-10-12']
    rows = bars(sorted(days))
    before = json.dumps(rows)
    row = rec.reconcile_series('price_series:topix', rows, open_days=OPEN)
    assert row['unexpectedDates']['first'] == ['2026-10-12'] and row['missingDates']['count'] == 0
    assert json.dumps(rows) == before


def test_exchange_outage_is_not_expected():
    days = [d for d in OPEN if '2020-09-28' <= d <= '2020-10-06']
    without = rec.reconcile_series('price_series:nikkei', bars([d for d in days if d != '2020-10-01']), open_days=OPEN)
    assert without['status'] == 'COMPLETE' and without['expected'] == len(days) - 1
    held = rec.reconcile_series('price_series:nikkei', bars(days), open_days=OPEN)
    assert held['status'] == 'COMPLETE' and held['knownNontradingRows'] == ['2020-10-01']


def test_weekly_series_check_the_week_not_the_weekday():
    # A Friday holiday moves the week's date to Thursday; a missing week is found.
    rows = [{'periodEnd': d, 'seriesId': s, 'value': 1.0, 'knownAt': d + 'T09:00:00Z'}
            for d in ('2026-09-04', '2026-09-10', '2026-09-25') for s in ('credit.long_balance', 'credit.short_balance')]
    row = rec.reconcile_series('two_market_credit', rows, open_days=OPEN)
    assert row['status'] == 'GAPS_FOUND' and row['missingDates']['first'] == ['2026-W38']
    assert row['duplicatedDates']['count'] == 0 and row['parts'] == 2


def test_revisions_are_not_duplicates():
    rows = [{'periodEnd': '2026-10-02', 'seriesId': 'flow.foreign', 'value': 1.0, 'knownAt': t}
            for t in ('2026-10-08T06:00:00Z', '2026-10-15T06:00:00Z')]
    row = rec.reconcile_series('foreign_flow', rows, open_days=OPEN)
    assert row['status'] == 'COMPLETE' and row['revisedDates'] == 1 and row['duplicatedDates']['count'] == 0


def test_margin_switches_from_weeks_to_sessions_on_the_application_date():
    weekly = ['2026-09-04', '2026-09-11', '2026-09-18']
    daily = [d for d in OPEN if '2026-09-25' <= d <= '2026-10-09']
    row = rec.reconcile_series('margin_1570', bars(weekly + daily), open_days=OPEN)
    assert row['status'] == 'COMPLETE', row
    gap = rec.reconcile_series('margin_1570', bars(weekly + [d for d in daily if d != '2026-10-01']), open_days=OPEN)
    assert gap['missingDates']['first'] == ['2026-10-01']


def test_series_without_official_calendar_is_never_complete_and_derived_is_not_checked():
    us = rec.reconcile_series('price_series:sp500', bars(OPEN[-5:]), open_days=OPEN)
    assert us['status'] == 'EXPECTED_CALENDAR_UNAVAILABLE' and us['expected'] is None
    assert rec.reconcile_series('valuation_loss', bars(OPEN[-5:]), open_days=OPEN)['status'] == 'NOT_EXPECTED'
    assert rec.reconcile_series('sq_events', [], open_days=OPEN)['status'] == 'NOT_EXPECTED'


def test_unknown_calendar_days_are_not_called_complete_or_unexpected():
    days = [d for d in OPEN if '2026-10-05' <= d <= '2026-10-16']
    row = rec.reconcile_series('price_series:nikkei', bars(days), open_days=[d for d in OPEN if d != '2026-10-07'],
                               unknown_days=['2026-10-07'])
    assert row['status'] == 'COMPLETE_WHERE_CALENDAR_KNOWN' and row['calendarUnknownDays'] == 1


def test_invalid_values_and_list_limit_and_no_values_leave():
    days = [d for d in OPEN if d >= '2025-01-01']
    rows = [{'date': d, 'close': 98765.4321} for d in days[::2]] + [{'date': days[1], 'close': float('nan')}]
    document = rec.reconcile({'price_series': {'nikkei': rows}}, open_days=OPEN, measured_at='2026-10-18T00:00:00Z')
    row = document['series']['price_series:nikkei']
    assert row['invalidValueDates']['first'] == [days[1]]
    assert row['missingDates']['truncated'] and len(row['missingDates']['first']) == rec.LIST_LIMIT
    assert '98765' not in json.dumps(document) and document['gapsFound'] == ['price_series:nikkei']
    short = rec.summary(document)['series']['price_series:nikkei']
    assert set(short) == {'status', 'expected', 'actual', 'missing', 'unexpected', 'duplicated', 'invalidValues'}
    assert document['automaticRepair'] is False and document['actionAuthority'] is False


def test_bounds_and_every_condition_input_has_a_calendar():
    with pytest.raises(ValueError):
        rec.reconcile_series('price_series:nikkei', [{}] * (rec.MAX_ROWS + 1), open_days=OPEN)
    import jp_market_analogs
    covered = {f for features in rec.AFFECTED_FEATURES.values() for f in features}
    assert covered == set(jp_market_analogs.FEATURE_DEFINITIONS)
    assert set(rec.AFFECTED_FEATURES) == set(rec.CALENDARS)

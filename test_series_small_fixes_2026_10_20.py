"""2026-10-20: holiday weeks of the margin series and the holiday copy of a Nikkei bar."""
from datetime import date, timedelta

import argus_index_history
import jp_market_series_reconciliation as rec


def sessions(first, last, closed=()):
    day, out = date.fromisoformat(first), []
    while day <= date.fromisoformat(last):
        if day.weekday() < 5 and day.isoformat() not in closed:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


# 2026 Golden Week: 4, 5, 6 May closed -> 7 and 8 May are the week's only sessions.
OPEN = sessions('2026-04-20', '2026-05-22', closed={'2026-04-29', '2026-05-04', '2026-05-05', '2026-05-06'})
FRIDAYS = ['2026-04-24', '2026-05-01', '2026-05-15', '2026-05-22']


def rows(days):
    return [{'periodEnd': d, 'value': 1.0, 'knownAt': d + 'T09:00:00Z'} for d in days]


def test_a_margin_week_with_two_sessions_is_not_expected():
    two_market = rec.reconcile_series('two_market_credit', rows(FRIDAYS), open_days=OPEN)
    assert two_market['status'] == 'COMPLETE' and two_market['missingDates']['count'] == 0
    assert two_market['expected'] == 4


def test_a_publication_in_such_a_week_is_accepted_and_a_full_week_is_still_required():
    published = rec.reconcile_series('two_market_credit', rows(FRIDAYS + ['2026-05-08']), open_days=OPEN)
    assert published['status'] == 'COMPLETE'
    gap = rec.reconcile_series('two_market_credit', rows([d for d in FRIDAYS if d != '2026-05-15']), open_days=OPEN)
    assert gap['status'] == 'GAPS_FOUND' and gap['missingDates']['first'] == ['2026-W20']


def test_investor_flows_keep_every_week():
    flows = rec.reconcile_series('foreign_flow', rows(FRIDAYS), open_days=OPEN)
    assert flows['status'] == 'GAPS_FOUND' and flows['missingDates']['first'] == ['2026-W19']


def test_margin_weekly_part_uses_the_same_rule():
    margin = rec.reconcile_series('margin_1570', rows(FRIDAYS), open_days=OPEN)
    assert margin['missingDates']['count'] == 0


def bar(day, close, volume=1000.0):
    return {'date': day, 'open': close - 1, 'high': close + 1, 'low': close - 2, 'close': close, 'volume': volume}


def test_the_holiday_copy_of_the_previous_bar_is_dropped():
    copy = dict(bar('2018-07-13', 22597.35), date='2018-07-16', volume=0.0)
    kept = argus_index_history.drop_stale_holiday_copies(
        [bar('2018-07-12', 22187.96), bar('2018-07-13', 22597.35), copy, bar('2018-07-17', 22697.36)])
    assert [r['date'] for r in kept] == ['2018-07-12', '2018-07-13', '2018-07-17']


def test_a_real_zero_volume_or_changed_bar_is_kept():
    vix = [bar('2026-10-15', 18.0, 0.0), bar('2026-10-16', 18.0, 0.0)]          # zero volume throughout
    assert argus_index_history.drop_stale_holiday_copies(vix) == vix
    moved = [bar('2026-10-15', 100.0), bar('2026-10-16', 101.0, 0.0)]           # prices changed
    assert argus_index_history.drop_stale_holiday_copies(moved) == moved


def test_a_repeated_import_of_the_same_observation_reaches_the_inputs_once():
    row = {'seriesId': 'flow.foreign', 'periodEnd': '2026-10-09', 'knownAt': '2026-10-15T06:00:00Z', 'value': -1.5e11}
    revised = dict(row, knownAt='2026-10-16T06:00:00Z', value=-1.4e11)
    kept = rec.drop_exact_duplicates([row, dict(row, importId='second'), revised])
    assert kept == [row, revised]
    flows = rec.reconcile_series('foreign_flow', [row, dict(row)], open_days=['2026-10-09'])
    assert flows['duplicatedDates']['count'] == 1      # the check still names a duplicate when it is given one

"""2026-10-21: the same ledger observation received twice no longer stops the feature history."""
import pytest

import jp_market_engine
import jp_market_series_reconciliation as rec


def flow(known, value=-1234.0, **extra):
    return {'seriesId': 'flow.foreign', 'periodEnd': '2016-10-28', 'value': value, 'instrumentId': 'MARKET',
            'availableFrom': known, 'knownAt': known, 'importId': 'imp-' + known, **extra}


def test_the_same_observation_received_again_keeps_its_first_receipt():
    first, later = flow('2016-11-03T09:00:00Z'), flow('2026-10-20T09:30:00Z')
    kept = rec.keep_first_receipt([later, first])
    assert kept == [first]
    rows, _ = jp_market_engine.point_in_time_rows(kept, '2026-10-21T00:00:00Z')
    assert len(rows) == 1


def test_the_admission_still_stops_on_two_values_for_one_revision():
    rows = rec.keep_first_receipt([flow('2016-11-03T09:00:00Z'), flow('2026-10-20T09:30:00Z', value=-1.0)])
    assert len(rows) == 2
    with pytest.raises(ValueError, match='conflicting_row_revision'):
        jp_market_engine.point_in_time_rows(rows, '2026-10-21T00:00:00Z')


def test_a_correction_and_unreadable_times_are_kept():
    revised = flow('2026-10-20T09:30:00Z', value=-1.0, revision=1)
    broken = flow('not-a-time')
    original = flow('2016-11-03T09:00:00Z')
    assert rec.keep_first_receipt([original, revised]) == [original, revised]
    assert rec.keep_first_receipt([original, broken]) == [original, broken]


def test_without_the_fix_the_same_two_rows_stop_the_admission():
    with pytest.raises(ValueError, match='conflicting_row_revision:MARKET:.*:2016-10-28:0'):
        jp_market_engine.point_in_time_rows([flow('2016-11-03T09:00:00Z'), flow('2026-10-20T09:30:00Z')],
                                            '2026-10-21T00:00:00Z')

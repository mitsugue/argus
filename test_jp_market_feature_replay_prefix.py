"""過去再生のVIX交差は、接頭部分の実受領最大時刻を維持する。"""
from copy import deepcopy
from datetime import date, timedelta
import pytest
import jp_market_features as features


def rows():
    start = date(2025, 1, 1)
    return [{'instrumentId': 'VIX', 'seriesId': 'close',
             'date': str(start + timedelta(days=i)), 'value': 15 + (i % 15),
             'availableFrom': str(start + timedelta(days=i)) + 'T22:00:00Z'}
            for i in range(400)]


def expected_crosses(source, cutoff):
    visible = features._history(source, 'VIX', cutoff)
    macd = features._macd([row['numericValue'] for row in visible], features.ARGUS_MACD_BASELINE)
    result = []
    for i in range(sum(features.ARGUS_MACD_BASELINE[:2]), len(visible)):
        previous, current = macd[i - 1]['histogram'], macd[i]['histogram']
        direction = 1 if previous <= 0 < current else -1 if previous >= 0 > current else None
        if direction:
            result.append({'instrumentId': features.INSTRUMENT, 'seriesId': 'vix_macd_cross',
                           'date': visible[i]['date'], 'value': direction, 'unit': 'DIRECTION',
                           'availableFrom': max(features._knowledge_time(row) for row in visible[:i + 1]).isoformat(),
                           'sourceRef': 'derived:vix-macd-12-26-9', 'validationStatus': 'UNVALIDATED'})
    return result


@pytest.mark.parametrize('case', ['ordered', 'late_receipt', 'future_receipt', 'revision'])
def test_cross_time_and_direction_match_independent_prefix_definition(case):
    source = rows()
    if case == 'late_receipt':
        source[45]['knownAt'] = '2025-12-30T23:00:00Z'
    elif case == 'future_receipt':
        source[45]['knownAt'] = '2027-01-01T00:00:00Z'
    elif case == 'revision':
        source.append({**source[45], 'revision': 1, 'value': 45, 'knownAt': '2025-12-30T23:00:00Z'})
    original = deepcopy(source)
    for cutoff in ('2025-12-20T23:59:59Z', '2026-02-06T23:59:59Z'):
        actual = features.build_market_features(cutoff=cutoff, price_series={'vix': source})
        assert [r for r in actual['conditions'] if r['seriesId'] == 'vix_macd_cross'] == expected_crosses(source, cutoff)
    assert source == original


def test_cross_receipts_are_read_once_per_prefix_not_once_per_cross(monkeypatch):
    source = rows()
    calls = []
    original = features._knowledge_time
    def counted(row):
        calls.append(row)
        return original(row)
    monkeypatch.setattr(features, '_knowledge_time', counted)
    actual = features.build_market_features(cutoff='2026-02-06T23:59:59Z', price_series={'vix': source})
    assert len([r for r in actual['conditions'] if r['seriesId'] == 'vix_macd_cross']) > 20
    # emit(full-history), the prefix maxima and short recent features only.
    assert len(calls) <= 2 * len(source) + 20

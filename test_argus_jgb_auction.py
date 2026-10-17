from copy import deepcopy
from datetime import date
import pytest

import argus_jgb_auction as auction
AT = '2026-10-06T06:50:00+09:00'


def calendar_raw(link=None):
    result = '入札結果' if link is None else f'<a href="{link}">入札結果</a>'
    return ('<h1>入札カレンダー：令和8年10月</h1><table><tr>'
        '<td>10月6日（火）</td><td>10年利付国債</td><td>詳細</td><td>詳細</td>'
        f'<td>{result}</td><td><a href="nyusatsu/resul20261006a.htm">入札結果</a></td>'
        '</tr></table>').encode()


def result_raw(tenor=10):
    head = f'<h1>{tenor}年利付国債（第999回）の入札結果（令和8年10月6日入札）</h1>'
    fields = [('6．','価格競争入札について',''), ('','(1)応募額','2兆5,000億円'),
        ('','(2)募入決定額','5,000億円'), ('','（募入最高利回り）','（3.125％）'),
        ('','（募入平均利回り）','（3.100％）'), ('7．','非競争入札について',''),
        ('','(1)応募額','100億円'), ('','(2)募入決定額','100億円')]
    if tenor == 40:
        fields = [('6．','応募額','2兆5,000億円'), ('7．','募入決定額','5,000億円'),
            ('8．','応募者利回り','3.125％'), ('','（募入最高利回り）','')]
    return (head+'<table>'+''.join(f'<tr><td>{n}</td><td>{k}</td><td></td><td>{v}</td></tr>'
        for n,k,v in fields)+'</table>').encode()


def expected(tenor=10):
    return {'sessionDate':'2026-10-06', 'tenorYears':tenor,
        'sourceUrl':auction.ROOT+'nyusatsu/resul20261006.htm'}


def test_calendar_keeps_pending_without_guessing_or_supplementary_result():
    row = auction.parse_calendar(calendar_raw(), source_url=auction.ROOT+'2610.htm')[0]
    assert row['sourceUrl'] is None
    row = auction.parse_calendar(calendar_raw('nyusatsu/resul20261006.htm'), source_url=auction.ROOT+'2610.htm')[0]
    assert row == expected()
    assert auction.calendar_urls(date(2026,1,1)) == [auction.ROOT+'2512.htm', auction.ROOT+'2601.htm']


@pytest.mark.parametrize('link', ['https://other.example/result.htm',
    'https://www.mof.go.jp@other.example/result.htm', 'nyusatsu/resul20261006a.htm',
    'nyusatsu/resul20261007.htm', 'http://www.mof.go.jp/jgbs/auction/calendar/nyusatsu/resul20261006.htm'])
def test_calendar_rejects_wrong_origin_date_and_supplementary_column(link):
    with pytest.raises(ValueError):
        auction.parse_calendar(calendar_raw(link), source_url=auction.ROOT+'2610.htm')


@pytest.mark.parametrize('raw,url', [(calendar_raw(),auction.ROOT+'2609.htm'),
    (calendar_raw().replace(b'</table>',calendar_raw()+b'</table>'),auction.ROOT+'2610.htm'),
    (b'x'*256001,auction.ROOT+'2610.htm')])
def test_calendar_refuses_wrong_period_duplicate_or_size(raw,url):
    with pytest.raises(ValueError): auction.parse_calendar(raw, source_url=url)


@pytest.mark.parametrize('tenor', [10,20,30])
def test_competitive_amounts_use_one_section_and_tail_is_not_price(tenor):
    row = auction.parse_result(result_raw(tenor), expected=expected(tenor), acquired_at=AT)
    assert row['bidToCover'] == 5 and row['yieldTailBp'] == pytest.approx(2.5)
    assert row['competitiveAcceptedAmountJpy'] == 5*10**11
    assert row['knownAt'] == AT and row['publishedAt'] is None
    assert row['publishedDate'] == '2026-10-06'
    assert row['predictivePerformance'] == 'UNVALIDATED' and not row['actionAuthority']
    later = auction.parse_result(result_raw(tenor), expected=expected(tenor), acquired_at='2026-10-06T07:00:00+09:00')
    assert later['id'] == row['id'] and later['knownAt'] != row['knownAt']


def test_uniform_yield_has_no_average_or_tail():
    row = auction.parse_result(result_raw(40), expected=expected(40), acquired_at=AT)
    assert row['auctionMethod'] == 'UNIFORM_YIELD'
    assert row['highestAcceptedYieldPct'] == 3.125
    assert row['averageAcceptedYieldPct'] is None and row['yieldTailBp'] is None


@pytest.mark.parametrize('raw,identity,at', [
    (result_raw(20),expected(),AT),
    (result_raw(),{**expected(),'sourceUrl':auction.ROOT+'nyusatsu/resul20261006a.htm'},AT),
    (result_raw(),expected(),'2026-10-05T23:59:00+09:00'),
    (result_raw(),expected(),'2026-10-06T06:50:00'),
    (result_raw().replace('2兆5,000億円'.encode(),'10億円'.encode()),expected(),AT),
    (result_raw().replace('3.100'.encode(),b'4.100'),expected(),AT),
    (result_raw().replace('3.100'.encode(),b'NaN'),expected(),AT),
    (result_raw().replace('2兆5,000億円'.encode(),'2兆5,00億円'.encode()),expected(),AT),
    (result_raw().replace('（募入平均利回り）'.encode(),'欠測'.encode()),expected(),AT),
    (result_raw().replace('価格競争入札について'.encode(),'別の入札'.encode()),expected(),AT),
    (b'x'*256001,expected(),AT),
])
def test_result_rejects_unsafe_or_ambiguous_inputs(raw,identity,at):
    with pytest.raises(ValueError): auction.parse_result(raw, expected=identity, acquired_at=at)


def test_revision_can_restore_an_earlier_value_without_overwriting_receipt():
    first = auction.parse_result(result_raw(), expected=expected(), acquired_at=AT)
    revision = auction.parse_result(result_raw().replace(b'3.100',b'3.101'), expected=expected(), acquired_at=AT)
    restored = auction.parse_result(result_raw(), expected=expected(), acquired_at='2026-10-06T07:00:00+09:00')
    assert first['id'] != revision['id'] and restored['id'] == first['id']
    assert first['knownAt'] == AT and restored['knownAt'] != AT


def test_shared_ledger_preserves_receipt_revisions_restore_and_no_effective_macro(monkeypatch):
    import argus_market_ledger as ledger
    from datetime import timedelta, datetime
    monkeypatch.setattr(ledger, 'SERIES', {**ledger.SERIES, **auction.ledger_series()})
    first = auction.parse_result(result_raw(), expected=expected(), acquired_at=AT)
    start = ledger.empty_state()
    def append(state, row):
        candidates = auction.missing_candidates(state, auction.ledger_candidates([row]))
        result = ledger.import_rows(state, candidates, now_iso=row['knownAt'], dry_run=False, rebuild_after_commit=False)
        assert result['ok']
        return ledger.normalize_state(result['state'])
    stored = append(start, first)
    assert not start['observations']
    assert ledger.effective_observations(stored, AT) == []
    assert auction.saved_rows(stored, as_of='2026-10-06T06:49:59+09:00') == []
    same = {**first, 'knownAt':'2026-10-06T07:00:00+09:00', 'acquiredAt':'2026-10-06T07:00:00+09:00'}
    assert auction.missing_candidates(stored, auction.ledger_candidates([same])) == []
    revised = auction.parse_result(result_raw().replace(b'3.100', b'3.101'), expected=expected(), acquired_at=same['knownAt'])
    second = append(stored, revised)
    third = append(second, {**first, 'knownAt':'2026-10-06T08:00:00+09:00', 'acquiredAt':'2026-10-06T08:00:00+09:00'})
    assert len(third['observations']) == 3
    assert auction.saved_rows(third, as_of=AT) == [first]
    assert auction.saved_rows(third, as_of=same['knownAt']) == [revised]
    assert auction.saved_rows(third, as_of='2026-10-06T08:00:00+09:00')[0]['id'] == first['id']
    rolled = ledger.rollback_import(third, third['observations'][-1]['importId'], '2026-10-06T09:00:00+09:00')
    assert auction.saved_rows(rolled, as_of='2026-10-06T09:00:00+09:00') == [revised]


def test_pending_projection_keeps_previous_result_without_claiming_current(monkeypatch):
    import argus_market_ledger as ledger
    monkeypatch.setattr(ledger, 'SERIES', {**ledger.SERIES, **auction.ledger_series()})
    first = auction.parse_result(result_raw(), expected=expected(), acquired_at=AT)
    stored = ledger.import_rows(ledger.empty_state(), auction.ledger_candidates([first]), now_iso=AT,
        dry_run=False, rebuild_after_commit=False)['state']
    doc = auction.projection(stored, as_of=AT, expected=[expected()], acquisition='AVAILABLE')
    assert doc['series']['10']['status'] == 'AVAILABLE'
    future = {'tenorYears':10, 'sessionDate':'2026-11-06', 'sourceUrl':None}
    pending = auction.projection(stored, as_of='2026-11-06T09:00:00+09:00', expected=[future], acquisition='UPDATE_WAIT')
    assert pending['series']['10']['status'] == 'UPDATE_WAIT'
    assert pending['series']['10']['latestResult'] == first
    assert pending['id'] != doc['id'] and not pending['actionAuthority']


def test_collection_bounds_receipt_and_pending_does_not_guess_a_url():
    calls = []
    def read(url, limit):
        calls.append((url, limit))
        if url.endswith('2609.htm'):
            return '<h1>入札カレンダー：令和8年9月</h1>'.encode(), '2026-10-06T06:50:01+09:00'
        return calendar_raw(), '2026-10-06T06:50:02+09:00'
    outcome = auction.collect({'observations':[]}, as_of=AT, read=read)
    assert len(calls) == outcome['requests'] == 2
    assert outcome['acquisitionStatus'] == 'UPDATE_WAIT'
    assert not outcome['candidates']
    assert outcome['completedAt'] == '2026-10-06T06:50:02+09:00'


def test_partial_calendar_failure_preserves_rows_and_refuses_result_fetch():
    calls = []
    def read(url, limit):
        calls.append(url)
        if url.endswith('2609.htm'): raise TimeoutError('fixture')
        return calendar_raw('nyusatsu/resul20261006.htm'), AT
    outcome = auction.collect({'observations':[]}, as_of=AT, read=read)
    assert outcome['acquisitionStatus'] == 'FAILED' and len(calls) == 2
    assert not outcome['candidates']


def test_collection_uses_each_actual_completion_and_ignores_future_calendar():
    calls = []
    def read(url, limit):
        calls.append(url)
        if url.endswith('2609.htm'):
            return '<h1>入札カレンダー：令和8年9月</h1>'.encode(), '2026-10-06T06:50:01+09:00'
        if url.endswith('2610.htm'):
            return calendar_raw('nyusatsu/resul20261006.htm'), '2026-10-06T06:50:02+09:00'
        return result_raw(), '2026-10-06T06:50:05+09:00'
    outcome = auction.collect({'observations':[]}, as_of=AT, read=read)
    assert len(calls) == 3 and outcome['acquisitionStatus'] == 'UPDATE_WAIT'
    assert outcome['candidates'][0]['availableFrom'] == '2026-10-06T06:50:05+09:00'
    assert outcome['candidates'][0]['metadata']['jgbAuctionInput']['publishedAt'] is None


def test_receipt_before_start_is_not_admitted():
    result = auction.collect({'observations':[]}, as_of=AT,
        read=lambda *args: (calendar_raw(), '2026-10-06T06:49:59+09:00'))
    assert result['acquisitionStatus'] == 'FAILED' and not result['candidates']


def all_calendar():
    return ('<h1>入札カレンダー：令和8年10月</h1><table>'+''.join(
        '<tr><td>10月6日（火）</td><td>'+str(tenor)+'年利付国債</td>'
        '<td>詳細</td><td>詳細</td><td><a href="nyusatsu/resul20261006.htm">入札結果</a></td><td></td></tr>'
        for tenor in auction.TENORS)+'</table>').encode()


def test_six_read_limit_partial_result_and_constant_receipt_identity(monkeypatch):
    # A synthetic separate date per tenor models a real monthly calendar.
    days = {10:6, 20:5, 30:2, 40:1}
    cal = all_calendar().decode()
    for tenor, day in days.items():
        fragment = '<tr><td>10月6日（火）</td><td>'+str(tenor)+'年利付国債</td>'
        replacement = '<tr><td>10月'+str(day)+'日（火）</td><td>'+str(tenor)+'年利付国債</td>'
        start = cal.index(fragment); end = cal.index('</tr>', start) + len('</tr>')
        row = cal[start:end].replace(fragment, replacement).replace('resul20261006.htm',f'resul202610{day:02d}.htm')
        cal = cal[:start]+row+cal[end:]
    calls = []
    def read(url, limit):
        calls.append(url)
        if url.endswith('2609.htm'): return '<h1>入札カレンダー：令和8年9月</h1>'.encode(), AT
        if url.endswith('2610.htm'): return cal.encode(), AT
        day = int(url[-6:-4]); tenor = next(k for k,v in days.items() if v==day)
        return result_raw(tenor).replace('令和8年10月6日'.encode(),f'令和8年10月{day}日'.encode()), AT
    result = auction.collect({'observations':[]}, as_of=AT, read=read)
    assert result['requests'] == len(calls) == 6
    assert result['acquisitionStatus'] == 'AVAILABLE' and len(result['candidates']) == 4
    assert result['candidates'][-1]['metadata']['jgbAuctionInput']['yieldTailBp'] is None
    def fail_one(url, limit):
        if url.endswith('resul20261005.htm'): raise TimeoutError()
        return read(url, limit)
    partial = auction.collect({'observations':[]}, as_of=AT, read=fail_one)
    assert partial['requests'] == 6 and partial['acquisitionStatus'] == 'FAILED'
    assert len(partial['candidates']) == 3


def test_future_receipt_cannot_suppress_a_current_official_observation(monkeypatch):
    import argus_market_ledger as ledger
    monkeypatch.setattr(ledger, 'SERIES', {**ledger.SERIES, **auction.ledger_series()})
    current = auction.parse_result(result_raw(), expected=expected(), acquired_at=AT)
    future = {**current, 'knownAt':'2026-10-06T12:00:00+09:00', 'acquiredAt':'2026-10-06T12:00:00+09:00'}
    stored = ledger.import_rows(ledger.empty_state(), auction.ledger_candidates([future]), now_iso=future['knownAt'],
        dry_run=False, rebuild_after_commit=False)['state']
    assert auction.missing_candidates(stored, auction.ledger_candidates([current])) == auction.ledger_candidates([current])

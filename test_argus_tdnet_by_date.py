"""2026-11-18 owner 【日付でまとめて取る】: TDnet (yanoshin) is read by date, not as the latest 150."""
from datetime import date

import argus_tdnet
import scanner


def test_today_and_the_previous_trading_day_are_read():
    weekday = lambda d: d.weekday() < 5
    assert argus_tdnet.yanoshin_dates(date(2026, 11, 18), weekday) == ['20261118', '20261117']
    # Monday morning reads Friday (the weekend is skipped).
    assert argus_tdnet.yanoshin_dates(date(2026, 11, 16), weekday) == ['20261116', '20261113']
    # A holiday before is skipped too (11/23 is a public holiday).
    closed = lambda d: d.weekday() < 5 and d != date(2026, 11, 23)
    assert argus_tdnet.yanoshin_dates(date(2026, 11, 24), closed) == ['20261124', '20261120']


def test_wrapped_and_flat_rows_are_both_read():
    wrapped = {'items': [{'Tdnet': {'id': '1', 'title': 'a'}}, 'junk']}
    flat = {'items': [{'id': '2', 'title': 'b'}]}
    assert [r['id'] for r in argus_tdnet.yanoshin_rows(wrapped)] == ['1']
    assert [r['id'] for r in argus_tdnet.yanoshin_rows(flat)] == ['2']
    assert list(argus_tdnet.yanoshin_rows(None)) == [] and list(argus_tdnet.yanoshin_rows([])) == []


class _Response:
    def __init__(self, data, ok=True):
        self.ok, self._data = ok, data

    def json(self):
        return self._data


def _day(day, count, minute_of=lambda i: '15:30:00'):
    stamp = f'{day[:4]}-{day[4:6]}-{day[6:]}'
    return {'items': [{'id': f'{day}-{i}', 'pubdate': f'{stamp} {minute_of(i)}',
                       'company_code': f'{1000 + i:04d}0', 'company_name': f'会社{i}',
                       'title': '決算短信', 'document_url': f'https://example.test/{day}/{i}.pdf'}
                      for i in range(count)]}


def _fetch(monkeypatch, responses):
    asked = []

    def get(url, **kwargs):
        asked.append(url)
        for key, value in responses.items():
            if key in url:
                return value
        raise AssertionError(url)
    monkeypatch.setattr(scanner.requests, 'get', get)
    monkeypatch.setitem(scanner._TDNET_FEED_CACHE, 'data', None)
    monkeypatch.setitem(scanner._TDNET_FEED_CACHE, 'expires', 0.0)
    monkeypatch.setattr(argus_tdnet, 'yanoshin_dates', lambda today, trading: ['20261114', '20261113'])
    return scanner._get_tdnet_yanoshin(150), asked


def test_a_15_00_result_on_a_busy_day_is_seen(monkeypatch):
    # 11/13: 300 disclosures; the first 100 at 15:00, the rest at 15:30.
    busy = _day('20261113', 300, lambda i: '15:00:00' if i < 100 else '15:30:00')
    out, asked = _fetch(monkeypatch, {'/20261114.json': _Response(_day('20261114', 1)),
                                      '/20261113.json': _Response(busy)})
    assert out['status'] == 'live' and out['official'] is False
    assert out['coverage'] == {'mode': 'by_date', 'dates': ['20261114', '20261113'],
                               'count': 301, 'truncatedDates': []}
    # Company 1050 disclosed only at 15:00 on 11/13: outside the latest 150 before.
    assert [d['time'] for d in out['bySymbol']['1050']] == ['2026-11-13 15:00:00']
    assert [d['time'] for d in out['bySymbol']['1000']] == ['2026-11-14 15:30:00', '2026-11-13 15:00:00']
    assert [u.split('/list/')[1] for u in asked] == ['20261114.json?limit=5000', '20261113.json?limit=5000']
    assert out['items'][0]['time'] == '2026-11-14 15:30:00' and len(out['items']) == 200
    # Nothing about the owner is sent: only dates.
    assert all('/list/2026111' in u for u in asked)


def test_a_day_that_cannot_be_read_falls_back_to_the_latest_list(monkeypatch):
    out, asked = _fetch(monkeypatch, {'/20261114.json': _Response({}, ok=False),
                                      '/recent.json': _Response({'items': [{'Tdnet': _day('20261114', 1)['items'][0]}]})})
    assert out['status'] == 'live' and out['coverage'] == {'mode': 'latest', 'limit': 150, 'count': 1}
    assert asked[-1].endswith('/recent.json?limit=150')


def test_a_full_day_is_marked_truncated(monkeypatch):
    monkeypatch.setattr(argus_tdnet, 'YANOSHIN_DAY_LIMIT', 3)
    out, _ = _fetch(monkeypatch, {'/20261114.json': _Response(_day('20261114', 1)),
                                  '/20261113.json': _Response(_day('20261113', 3))})
    assert out['coverage']['truncatedDates'] == ['20261113']

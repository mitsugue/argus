"""会社予定接続後に実経路へ適用する検査候補。公開入力は固定共有だけ。"""
from copy import deepcopy
import scanner
from test_argus_corporate_earnings_calendar import items


def setup_saved(monkeypatch):
    saved = items()
    saved['US:OWNER_ONLY'] = deepcopy(saved['US:AAA'])
    saved['US:OWNER_ONLY']['earnings']['symbol'] = 'OWNER_ONLY'
    monkeypatch.setattr(scanner, '_JP_WATCHLIST', [{'symbol':'1111','name':'共有日本株'}])
    monkeypatch.setattr(scanner, '_US_WATCHLIST', [{'symbol':'AAA','name':'共有米国株'}])
    monkeypatch.setattr(scanner, '_ANALYST_TARGETS', {'items':saved,'loaded':True})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda:'2026-10-31T01:00:00Z')
    monkeypatch.setattr(scanner, '_analyst_targets_load_saved', lambda:None)
    monkeypatch.setattr(scanner, '_jp_ex_dividend_estimates', lambda day:{})
    monkeypatch.setattr(scanner.jp_equity_event_calendar,'equity_event_calendar',lambda **kw:{'events':[],'gaps':[],'status':'AVAILABLE'})
    def forbidden(*args, **kwargs):
        raise AssertionError('保存予定の読取から取得・本人登録・AIへ進んだ')
    monkeypatch.setattr(scanner, '_analyst_targets_warm', forbidden)
    monkeypatch.setattr(scanner, '_analyst_targets_symbols', forbidden)
    monkeypatch.setattr(scanner, '_layer2b_read_latest', forbidden)
    monkeypatch.setattr(scanner.requests, 'get', forbidden)
    return saved


def test_public_calendar_uses_saved_fixed_universe_without_fetch_or_owner_projection(monkeypatch):
    saved = setup_saved(monkeypatch)
    original = deepcopy(saved)
    with scanner.app.test_request_context('/api/argus/jp-equity-calendar'):
        actual = scanner.api_argus_jp_equity_calendar().get_json()
    assert len(actual['events']) == 2
    assert all(row['kind']=='CORPORATE_EARNINGS' and row['dateOnly'] for row in actual['events'])
    assert all(row['actionAuthority'] is False for row in actual['events'])
    assert 'OWNER_ONLY' not in str(actual)
    assert saved == original


def test_missing_saved_company_dates_keep_other_calendar_events(monkeypatch):
    setup_saved(monkeypatch)
    monkeypatch.setattr(scanner, '_ANALYST_TARGETS', {'items':{},'loaded':True})
    original={'eventId':'fixture-sq','kind':'SQ','at':'2026-11-13','date':'2026-11-13'}
    monkeypatch.setattr(scanner.jp_equity_event_calendar,'equity_event_calendar',lambda **kw:{'events':[deepcopy(original)],'gaps':[],'status':'AVAILABLE'})
    with scanner.app.test_request_context('/api/argus/jp-equity-calendar'):
        actual = scanner.api_argus_jp_equity_calendar().get_json()
    assert actual['events'] == [original]

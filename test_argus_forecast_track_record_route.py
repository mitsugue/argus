import argus_analysis_history as history
import scanner
from test_argus_analysis_history import _issue


def test_market_brief_serves_the_issued_forecast_record_read_only(tmp_path, monkeypatch):
    path = tmp_path/'history.sqlite'; history.initialize(path)
    _issue(path, '2026-09-13T00:00:00Z', '2026-09-11', 102, [{'date':'2026-09-14','close':98}], '2026-09-14T07:00:00Z')
    monkeypatch.setattr(scanner, '_market_brief_history_path', lambda: str(path))
    monkeypatch.setattr(scanner, '_MARKET_BRIEF_TRACK_RECORD', {'value': None, 'at': 0.0})
    reply = scanner.app.test_client().get('/api/argus/market-brief?trackRecord=1')
    body = reply.get_json()
    assert reply.status_code == 200 and body['status'] == 'AVAILABLE' and body['actionAuthority'] is False
    one = body['trackRecord']['horizons']['1']
    assert one['directionalForecasts'] == 1 and one['hits'] == 0 and one['status'] == 'INSUFFICIENT_SAMPLE'
    assert body['trackRecord']['predictiveProbabilities'] is None


def test_track_record_without_history_storage_is_unavailable(monkeypatch):
    monkeypatch.setattr(scanner, '_market_brief_history_path', lambda: None)
    reply = scanner.app.test_client().get('/api/argus/market-brief?trackRecord=1')
    assert reply.status_code == 503 and reply.get_json()['reason'] == 'history_storage_not_configured'

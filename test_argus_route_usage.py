"""2026-10-22 (owner): calls per route rule per UTC day, without raw paths or queries."""
import json
from types import SimpleNamespace

import argus_route_usage as usage


def test_counts_per_rule_method_status_and_caller():
    state = usage.empty()
    for status, ua in ((200, 'Mozilla/5.0 (iPhone)'), (404, 'python-requests/2.32'), (503, 'curl/8')):
        usage.note(state, day='2026-10-22', rule='/api/argus/event-memory/<event_id>', method='get',
                   status=status, caller=usage.caller_kind(ua))
    row = state['days']['2026-10-22']['/api/argus/event-memory/<event_id> GET']
    assert row == {'calls': 3, 'ok': 1, 'clientError': 1, 'serverError': 1, 'browser': 1, 'other': 2}


def test_parse_rejects_malformed_and_keeps_only_recent_days():
    state = usage.empty()
    for i in range(usage.KEEP_DAYS + 5):
        usage.note(state, day=f'2026-09-{i % 30 + 1:02d}' if i < 30 else f'2026-10-{i - 29:02d}',
                   rule='/x', method='GET', status=200, caller='other')
    assert len(state['days']) <= usage.KEEP_DAYS
    again = usage.parse(json.loads(json.dumps(state)))
    assert again == state
    assert usage.parse({'schemaVersion': 'other'}) == usage.empty()
    assert usage.parse({'schemaVersion': usage.SCHEMA, 'days': {'bad': {}, '2026-10-01': {'k': {'calls': -1}}}}) \
        == {'schemaVersion': usage.SCHEMA, 'days': {'2026-10-01': {}}}


def test_summary_names_catalogued_routes_never_called():
    state = usage.empty()
    usage.note(state, day='2026-10-22', rule='/api/argus/market-brief', method='GET', status=200, caller='browser')
    catalog = [SimpleNamespace(route='/api/argus/market-brief', trustDomain='PUBLIC'),
               SimpleNamespace(route='/api/argus/pro-handoff', trustDomain='PUBLIC')]
    result = usage.summary(state, catalog=catalog)
    assert result['routes']['/api/argus/market-brief GET']['calls'] == 1
    assert result['catalogNeverCalled'] == [{'route': '/api/argus/pro-handoff', 'trustDomain': 'PUBLIC'}]


def test_the_server_counts_the_rule_not_the_path(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_cost_policy_durable_enabled', lambda: False)
    monkeypatch.setattr(scanner, '_ROUTE_USAGE', {'state': usage.empty(), 'lastSavedMonotonic': 0.0, 'lastSaveError': None})
    with scanner.app.test_client() as client:
        client.get('/healthz?token=should-not-be-kept', headers={'User-Agent': 'curl/8'})
    rows = next(iter(scanner._ROUTE_USAGE['state']['days'].values()))
    assert '/healthz GET' in rows and rows['/healthz GET']['other'] == 1
    assert 'should-not-be-kept' not in json.dumps(scanner._ROUTE_USAGE['state'])

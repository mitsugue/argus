"""Real data clocks, analysis-window capacity, and private response boundary."""
import copy
import json

import pytest

from argus_collection_health import build_collection_health

NOW = '2026-10-06T02:00:00+09:00'


def source(inputs, key):
    return next(r for r in build_collection_health(inputs, now_iso=NOW)['sources'] if r['key'] == key)


def test_recent_poll_does_not_refresh_old_forecast():
    doc = {'sources': {'future_map': {'dataUpdatedAt': '2026-10-01T00:00:00+09:00',
                                    'lastCheckedAt': NOW, 'rowCount': 5}}}
    before = copy.deepcopy(doc)
    row = source(doc, 'future_map')
    assert row['status'] == 'stale' and row['dataAgeSec'] > 3 * 86400
    assert row['lastCheckedAt'] != row['dataUpdatedAt']
    assert doc == before


@pytest.mark.parametrize('stamp', [None, '', 'bad', '2026-10-06T02:00:00',
                                   '2026-10-06T02:01:00+09:00', '2026-02-30T00:00:00Z'])
def test_unknown_and_future_timestamp_never_becomes_current(stamp):
    row = source({'sources': {'future_map': {'dataUpdatedAt': stamp, 'lastCheckedAt': NOW}}}, 'future_map')
    assert row['status'] == 'unknown' and row['dataUpdatedAt'] is None


def test_just_imported_old_monthly_period_is_stale_not_new_weekly_data():
    row = source({'sources': {'credit_valuation': {'dataUpdatedAt': NOW, 'latestPeriod': '2026-08-28'}}}, 'credit_valuation')
    assert row['status'] == 'stale' and row['freshnessBasis'] == 'period_end'
    recent = source({'sources': {'credit_valuation': {'dataUpdatedAt': NOW, 'latestPeriod': '2026-09-25'}}}, 'credit_valuation')
    assert recent['status'] == 'current'


@pytest.mark.parametrize('rows,status', [(2399, 'within_limit'), (2400, 'warning'), (3000, 'warning'),
                                         (None, 'unknown'), (-1, 'unknown'), (True, 'unknown')])
def test_analysis_window_capacity_is_not_archive_capacity(rows, status):
    health = build_collection_health({'inputSpans': {'price_series:vix': {'rows': rows}}}, now_iso=NOW)
    window = next(w for w in health['inputWindows'] if w['key'] == 'vix')
    assert window['status'] == status and window['warningAt'] == 2400 and window['limit'] == 3000
    assert window['scope'] == 'calculation_window' and window['archiveRowsMeasured'] is False


def test_only_closed_metadata_survives_hostile_inputs():
    sentinel = 'PRIVATE_DOMAIN_SENTINEL'
    health = build_collection_health({'sources': {'future_map': {'dataUpdatedAt': NOW, 'payload': sentinel,
          'lastCheckedAt': sentinel, 'rowCount': sentinel, 'latestPeriod': sentinel}, sentinel: {'dataUpdatedAt': NOW}},
          'inputSpans': {'price_series:vix': {'rows': 2400, 'private': sentinel}}, 'namingPolicy': sentinel,
          'private': sentinel}, now_iso=NOW)
    assert sentinel not in json.dumps(health)
    assert health['namingPolicy'] == 'unknown' and health['actionAuthority'] is False


def test_real_admin_route_only_adds_metadata_and_public_dto_stays_unchanged(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_MARKET_LEDGER', {'observations': [], 'rolledBackImports': []})
    monkeypatch.setattr(scanner, '_FUTURE_MAP', {'public': {'updatedAt': '2026-10-01T00:00:00+09:00',
                                                      'rows': [{'private': 'PRIVATE_BODY'}]}, 'lastReadOkAt': NOW})
    monkeypatch.setattr(scanner, '_JP_MARKET_FEATURE_INPUT_SPANS', {'price_series:vix': {'rows': 2400}})
    monkeypatch.setenv('PRODUCT_NAMING_POLICY', '{"schemaVersion":"product-naming-policy-v1","rules":[{"id":"N999","pattern":"FORBIDDEN_FIXTURE"}]}')
    inputs = scanner._collection_health_inputs(NOW)
    health = build_collection_health(inputs, now_iso=NOW)
    assert source(inputs, 'future_map')['status'] == 'stale'
    assert health['namingPolicy'] == 'configured_valid'
    assert 'PRIVATE_BODY' not in json.dumps(health)
    monkeypatch.setattr(scanner, '_collection_health_inputs', lambda now: (_ for _ in ()).throw(AssertionError('public must not call admin monitor')))
    assert 'collectionHealth' not in scanner._public_diagnostics_snapshot()
    monkeypatch.setattr(scanner, '_ARGUS_ADMIN_TOKEN', 'monitor-fixture-admin')
    monkeypatch.setattr(scanner, '_operational_diagnostics_snapshot', lambda: {'collectionHealth': health})
    with scanner.app.test_client() as client:
        assert client.get('/api/argus/admin/diagnostics/operational').status_code == 401
        response = client.get('/api/argus/admin/diagnostics/operational', headers={'X-ARGUS-ADMIN-TOKEN': 'monitor-fixture-admin'})
    assert response.status_code == 200 and 'no-store' in response.headers['Cache-Control']
    assert response.get_json()['collectionHealth'] == health


def test_credit_metadata_requires_both_balances_in_same_published_week(monkeypatch):
    import argus_market_ledger as ledger
    import scanner
    state = ledger.empty_state()
    for sid, day, known in [('credit.short_balance', '2026-09-18', '2026-09-28T07:00:00Z'),
                            ('credit.long_balance', '2026-09-18', '2026-09-28T07:00:00Z'),
                            ('credit.short_balance', '2026-09-25', '2026-09-29T07:00:00Z'),
                            ('credit.long_balance', '2026-10-02', '2026-10-06T07:00:00Z')]:
        outcome = ledger.import_rows(state, [{'seriesId': sid, 'periodEnd': day, 'availableFrom': known,
            'observedAt': '2026-10-05T16:00:00Z', 'value': 900_000_000_000, 'unit': 'JPY',
            'source': 'https://www.jpx.co.jp', 'sourceKind': 'official', 'status': 'live'}], now_iso='2026-10-05T16:00:00Z', dry_run=False)
        assert outcome['ok'], outcome['errors']
        state = outcome['state']
    monkeypatch.setattr(scanner, '_MARKET_LEDGER', state)
    inputs = scanner._collection_health_inputs(NOW)
    assert inputs['sources']['credit_balances']['latestPeriod'] == '2026-09-18'
    assert inputs['sources']['credit_balances']['rowCount'] == 1
    assert source(inputs, 'credit_valuation')['status'] == 'unknown'


def test_recalculation_success_does_not_claim_inputs_changed(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_MARKET_LEDGER', {'observations': [], 'rolledBackImports': []})
    monkeypatch.setattr(scanner, '_JP_MARKET_FEATURE_HISTORY', {
        'lastSuccessfulCalculationAt': NOW, 'lastCutoff': NOW, 'status': 'AVAILABLE', 'features': []})
    monkeypatch.setattr(scanner, '_JP_MARKET_FEATURE_INPUT_SPANS', {
        'price_series:nikkei': {'last': '2026-10-02', 'rows': 10}})
    row = source(scanner._collection_health_inputs(NOW), 'feature_history')
    assert row['status'] == 'unknown' and row['dataUpdatedAt'] is None
    assert row['lastCheckedAt'] and row['latestPeriod'] == '2026-10-02'


def test_current_by_age_can_still_be_missing_the_newly_due_week():
    doc = {"sources": {"credit_balances": {"dataUpdatedAt": NOW, "latestPeriod": "2026-09-25"}}}
    before = build_collection_health(doc, now_iso="2026-10-06T15:59:59+09:00")["sources"][0]
    after = build_collection_health(doc, now_iso="2026-10-06T16:00:00+09:00")["sources"][0]
    assert before["publicationState"] == "current"
    assert before["expectedLatestPeriod"] == "2026-09-25"
    assert before["nextScheduledPeriod"] == "2026-10-02"
    assert after["status"] == "current"  # Under the coarse fourteen-day age limit.
    assert after["publicationState"] == "overdue"
    assert after["expectedLatestPeriod"] == "2026-10-02"
    assert after["publicationBasis"] == "nominal_schedule_not_actual_receipt"


def test_missing_week_is_visible_after_deadline_even_without_data_clock():
    row = build_collection_health({}, now_iso="2026-10-06T16:01:00+09:00")["sources"][1]
    assert row["status"] == "unknown" and row["publicationState"] == "overdue"
    assert row["dataUpdatedAt"] is None


def test_missing_authority_calendar_does_not_guess_publication_deadline(monkeypatch):
    import argus_market_clock as clock
    def unavailable(*args, **kwargs):
        raise clock.CalendarUnavailableError("fixture")
    monkeypatch.setattr(clock, "canonical_trading_day", unavailable)
    row = source({}, "credit_balances")
    assert row["publicationState"] == "unknown"
    assert row["expectedLatestPeriod"] is None and row["nextScheduledPublicationAt"] is None

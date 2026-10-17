"""Receipt provenance across existing adapters, collection, revisions and readers."""
from copy import deepcopy
import hashlib
import json
import pytest
import argus_macro_results as results
import argus_macro_event_store as store
import argus_macro_event_analysis as analysis
import argus_dashboard_event_summary as summary

START = '2026-07-15T12:30:00Z'
RECEIVED = '2026-07-15T12:35:00Z'
LATER = '2026-07-15T18:35:00Z'
EVENT = {'eventId': 'fixture-gdp', 'eventDate': '2026-07-15', 'eventTimeUtc': START}
BLS = {'Results': {'series': [
    {'seriesID': sid, 'data': [{'year': '2026', 'period': month, 'value': value}
                              for month, value in [('M06', '312'), ('M05', '311')]]}
    for sid in ['CUSR0000SA0', 'CUSR0000SA0L1E', 'WPSFD4', 'WPSFD49104',
                'JTS000000000000000JOL', 'CES0000000001', 'LNS14000000']]}}
FRED = {'observations': [{'date': '2026-06-01', 'value': '2.8'},
                         {'date': '2026-05-01', 'value': '2.7'}]}
CASES = [(results.parse_cpi, [BLS]), (results.parse_ppi, [BLS]),
         (results.parse_jolts, [BLS]), (results.parse_pce, [FRED, FRED]),
         (results.parse_gdp, [FRED]), (results.parse_fomc, [FRED, FRED])]

@pytest.mark.parametrize('parser,raws', CASES)
def test_success_uses_receipt_not_schedule_reference_date_or_publication(parser, raws):
    before = deepcopy(raws)
    actual = parser(*raws, EVENT, RECEIVED)
    assert actual['available']
    assert actual['releasedAt'] is None
    assert actual['receivedAt'] == actual['availableFrom'] == RECEIVED
    assert actual['availabilityBasis'] == 'RESPONSE_RECEIPT'
    assert actual['historicalVintageVerified'] is False
    assert results._RECEIPT_LIMITATION in actual['limitationsJa']
    assert len(actual['sourceResponseSha256']) == 64
    assert raws == before
    late = parser(*raws, {**EVENT, 'eventTimeUtc': '2030-01-01T00:00:00Z'}, LATER)
    assert late['metrics'] == actual['metrics']
    assert late['receivedAt'] == LATER and late['releasedAt'] is None
    assert store.actual_revision_id(late) == store.actual_revision_id(actual)
    assert late['sourceResponseSha256'] == actual['sourceResponseSha256']

@pytest.mark.parametrize('at', [None, '', '2026-07-15', '2026-07-15T12:35:00', 'invalid'])
def test_invalid_receipt_cannot_be_an_available_result(at):
    with pytest.raises(ValueError, match='macro_receipt_time_invalid'):
        results.parse_gdp(FRED, EVENT, at)

@pytest.mark.parametrize('parser,raws', CASES)
def test_missing_results_do_not_claim_available_receipt(parser, raws):
    actual = parser(*[{} for _ in raws], EVENT, RECEIVED)
    assert not actual['available'] and actual['releasedAt'] is None
    assert 'availableFrom' not in actual

@pytest.mark.parametrize('code', ['NFP', 'CPI', 'PPI', 'JOLTS', 'PCE', 'GDP', 'FOMC'])
def test_dispatch_samples_receipt_after_all_provider_responses(code, monkeypatch):
    import scanner
    observed = []
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: RECEIVED if observed else START)
    def bls(*args, **kwargs):
        observed.append('BLS')
        return deepcopy(BLS), 200
    def fred(*args, **kwargs):
        observed.append('FRED')
        return deepcopy(FRED)
    class Response:
        status_code = 200
        def json(self):
            observed.append('NFP_JSON_READ')
            return deepcopy(BLS)
    monkeypatch.setattr(scanner, '_bls_fetch', bls)
    monkeypatch.setattr(scanner, '_fred_raw', fred)
    monkeypatch.setattr(scanner.requests, 'post', lambda *a, **k: Response())
    monkeypatch.setattr(scanner, '_MACRO_RESULT_STATE', deepcopy(scanner._MACRO_RESULT_STATE))
    actual = scanner._macro_result_fetch({**EVENT, 'eventCode': code})
    assert actual['available'] and actual['receivedAt'] == RECEIVED
    assert actual['releasedAt'] is None
    assert len(observed) == (2 if code in ('PCE', 'FOMC') else 1)


def test_provider_failure_does_not_invent_result_receipt(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_bls_fetch', lambda *a: (None, 403))
    actual = scanner._macro_result_fetch({**EVENT, 'eventCode': 'PPI'})
    assert not actual['available'] and actual['status'] == 'source_unreachable'
    assert actual['releasedAt'] is None and 'receivedAt' not in actual


def test_digest_is_canonical_parsed_response_and_changes_with_revision():
    first = results.series_receipt({'a': 1, 'b': 2}, RECEIVED)
    reordered = results.series_receipt({'b': 2, 'a': 1}, LATER)
    assert first['sourceResponseSha256'] == reordered['sourceResponseSha256']
    assert first['sourceResponseSha256'] == hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
    assert first['sourceResponseSha256'] != results.series_receipt({'a': 3, 'b': 2}, LATER)['sourceResponseSha256']


def test_legacy_snapshot_and_explanation_survive_forward_only_migration():
    actual = results.parse_gdp(FRED, EVENT, RECEIVED)
    old_actual = {k: v for k, v in actual.items() if k not in (
        'schemaVersion', 'receivedAt', 'availableFrom', 'availabilityBasis',
        'historicalVintageVerified', 'sourceResponseSha256')}
    old_actual['releasedAt'] = START
    old_actual['limitationsJa'] = []
    original = {**EVENT, 'eventCode': 'GDP', 'phase': 'post_result', 'updatedAt': START,
                'actual': old_actual, 'post': {'generatedAt': START, 'verdict': 'miss'}}
    saved = store.merge_record(None, original, now_iso=START)
    old_revision = deepcopy(saved['resultRevisions'][0])
    new = store.merge_record(saved, {**EVENT, 'updatedAt': RECEIVED, 'actual': actual}, now_iso=RECEIVED)
    assert old_revision in new['resultRevisions'] and old_revision['receiptStatus'] == 'LEGACY_UNVERIFIED'
    assert old_revision['actual'] == old_actual
    assert len(new['resultRevisions']) == 2 and new['post']['verdict'] == 'not_scoreable'
    assert any(r['analysis']['verdict'] == 'miss' for r in new['analysisRevisions'])
    repeated = store.merge_record(new, {**EVENT, 'updatedAt': LATER,
        'actual': results.parse_gdp(FRED, EVENT, LATER)}, now_iso=LATER)
    assert repeated['resultRevisions'] == new['resultRevisions']
    restored = store.restore_from_snapshot(json.loads(json.dumps(store.serialize_snapshot([repeated], as_of=LATER))))
    assert restored[EVENT['eventId']] == repeated


def test_summary_and_prompt_retain_receipt_basis_and_unknown_publication():
    actual = results.parse_gdp(FRED, EVENT, RECEIVED)
    rec = {**EVENT, 'eventCode': 'GDP', 'actual': actual}
    item = summary.build_summary_item(important_event=rec, macro_record=rec, now_iso=LATER)
    official = item['officialResult']
    for key in ('releasedAt', 'receivedAt', 'availableFrom', 'availabilityBasis',
                'historicalVintageVerified', 'sourceResponseSha256'):
        assert official[key] == actual[key]
        assert json.dumps(key) in analysis.build_post_prompt(EVENT, {}, actual)

@pytest.mark.parametrize('source', ['BLS', 'FRED/BEA', 'FRED/Fed'])
def test_legacy_readers_hide_unverified_publication_without_rewriting_source(source):
    actual = {'available': True, 'source': source, 'releasedAt': START,
              'metrics': {'value': 2}, 'limitationsJa': []}
    original = deepcopy(actual)
    rec = {**EVENT, 'eventCode': 'GDP', 'actual': actual}
    item = summary.build_summary_item(important_event=rec, macro_record=rec, now_iso=LATER)
    official = item['officialResult']
    assert official['releasedAt'] is None and official['receivedAt'] is None
    assert official['availableFrom'] is None and official['availabilityBasis'] == 'LEGACY_UNVERIFIED'
    prompt = analysis.build_post_prompt({}, {}, actual)
    assert START not in prompt and 'LEGACY_UNVERIFIED' in prompt
    assert actual == original


def test_previous_cpi_receipt_remains_usable_from_receipt_only():
    actual = {'available': True, 'source': 'BLS', 'receivedAt': RECEIVED, 'releasedAt': None}
    projected = results.project_series_timing(actual)
    assert projected['availableFrom'] == RECEIVED and projected['releasedAt'] is None
    assert projected['availabilityBasis'] == 'RESPONSE_RECEIPT'
    assert not projected['historicalVintageVerified']


def test_invalid_legacy_receipt_stays_unknown_and_projection_is_idempotent():
    actual = {'available': True, 'source': 'BLS', 'receivedAt': 'bad', 'releasedAt': START}
    projected = results.project_series_timing(actual)
    assert projected['availableFrom'] is None and projected['receivedAt'] is None
    assert projected['availabilityBasis'] == 'LEGACY_UNVERIFIED'
    assert results.project_series_timing(projected) == projected

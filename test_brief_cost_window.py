import json
import pytest
from scripts.brief_cost_window import report
from argus_ai_usage_receipt import make_receipt
from argus_ai_usage_store import initialize, append


def test_window_reads_all_receipts_preserves_unknowns_and_excludes_other_features(tmp_path):
    path = tmp_path / 'existing.sqlite3'; initialize(path)
    rows = [make_receipt(call_id=f'fixture-{i}', provider='openai', feature=feature,
        started_at=at, completed_at=at, requested_model='unchanged-model', returned_model='unchanged-model',
        outcome='success', provider_called=True, input_tokens=100, output_tokens=10,
        cached_input_tokens=None if i == 1 else 20, estimated_cost_usd=None if i == 1 else .001)
        for i, (feature, at) in enumerate([
            ('market_brief','2026-10-01T00:00:00Z'), ('market_brief','2026-10-07T23:59:59Z'),
            ('market_brief','2026-10-08T00:00:00Z'), ('news_intel','2026-10-03T00:00:00Z')])]
    append(path, rows); original = path.read_bytes()
    result = report(path, '2026-10-01T09:00:00+09:00', '2026-10-08T09:00:00+09:00')
    assert result['seconds'] == 7 * 86400 and result['throughSequence'] == 4
    assert result['summary']['uniqueReceipts'] == 2
    assert sum(g['unknownCostRecords'] for g in result['summary']['groups']) == 1
    assert sum(g['unknownTokenRecords']['cachedInputTokens'] for g in result['summary']['groups']) == 1
    assert result['qualityAcceptanceRate'] == 'NOT_AVAILABLE_FROM_PROVIDER_RECEIPTS'
    assert not result['invoiceSavingsVerified'] and not result['causalReductionVerified']
    assert 'callId' not in json.dumps(result) and 'sourceRef' not in json.dumps(result)
    assert path.read_bytes() == original
    assert report(path, '2026-11-01T00:00:00Z', '2026-11-08T00:00:00Z')['status'] == 'NO_RECORDED_GENERATION'


@pytest.mark.parametrize('start,end', [('2026-10-01','2026-10-08'),
                                      ('2026-10-08T00:00:00Z','2026-10-01T00:00:00Z')])
def test_invalid_window_never_fabricates_a_report(start, end):
    with pytest.raises(ValueError): report('unused', start, end)

import pytest
import argus_jpx_credit_valuation as v
from test_argus_jpx_credit_valuation import inputs

def row():
    result = {**v.calculate(inputs()), 'periodEnd':'2026-09-25'}
    return v.ledger_observation(result, url='https://www.jpx.co.jp/markets/statistics-equities/margin/tvdivq0000001rk9-att/20260925_mtcurrent.xlsx', sha256='ab'*32, received_at='2026-10-05T15:00:00Z')

def test_all_inputs_and_actual_receipt_survive():
    r=row()
    assert v.audited_ledger_observation(r)
    assert r['availableFrom']==r['metadata']['sourceDocument']['receivedAt']
    assert r['metadata']['valuationCalculation']['inputs']==inputs()
    assert r['publishedAt']=='' and not r['metadata']['historicalVintageVerified']

@pytest.mark.parametrize('mutation',[
    lambda r:r.update(value=0),
    lambda r:r['metadata']['valuationCalculation']['inputs'].update(jsfFinanceMillionJpy=0),
    lambda r:r.update(availableFrom='2026-09-29T07:00:00Z'),
    lambda r:r.update(sourceKind='official'),
    lambda r:r['metadata']['sourceDocument'].update(url='https://other.test/source.xlsx'),
    lambda r:r['metadata']['sourceDocument'].update(sha256='x'),
    lambda r:r.update(publishedAt='2026-09-29T07:00:00Z'),
    lambda r:r['metadata'].update(historicalVintageVerified=True),
])
def test_changed_input_value_receipt_or_source_is_not_an_audited_row(mutation):
    r=row(); mutation(r)
    assert not v.audited_ledger_observation(r)

def test_official_missing_inputs_remain_missing():
    r=row()
    calc=r['metadata']['valuationCalculation']; calc['inputs']['jsfFinanceMillionJpy']=None
    calc.update(value=None,classification='official_inputs_not_published',missingInputs=['jsfFinanceMillionJpy'])
    r.update(value=None,status='missing')
    assert v.audited_ledger_observation(r)
    r['value']=0
    assert not v.audited_ledger_observation(r)

def test_snapshot_copies_inputs_instead_of_aliasing_the_source():
    result={**v.calculate(inputs()),'periodEnd':'2026-09-25'}
    r=v.ledger_observation(result,url=row()['metadata']['sourceDocument']['url'],sha256='ab'*32,received_at='2026-10-05T15:00:00Z')
    result['inputs']['jsfFinanceMillionJpy']=0
    assert v.audited_ledger_observation(r)


def test_csv_import_keeps_typed_inputs_and_dry_run_does_not_write():
    import csv
    import io
    import json
    import argus_market_ledger as ledger
    source = row()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(source))
    writer.writeheader()
    writer.writerow({**source, 'metadata': json.dumps(source['metadata'])})
    parsed = ledger.parse_csv(buffer.getvalue())
    assert parsed[0]['metadata']['valuationCalculation']['inputs'] == inputs()
    dry = ledger.import_rows(ledger.empty_state(), parsed, now_iso='2026-10-05T15:01:00Z')
    assert dry['ok'] and not dry['state']['observations']
    committed = ledger.import_rows(ledger.empty_state(), parsed, now_iso='2026-10-05T15:01:00Z', dry_run=False)
    assert committed['ok']
    assert committed['state']['observations'][0]['metadata'] == source['metadata']
    view = next(r for r in ledger.public_view(committed['state'], '2026-10-05T15:01:00Z')['table']
                if r['seriesId'] == source['seriesId'])
    assert view['latestValue'] == source['value']
    assert v.audited_ledger_observation(view['history'][0]['auditedObservation'])
    assert view['history'][0]['calculationDigest'] == v.ledger_observation_digest(source)
    assert ledger.SERIES[source['seriesId']][3] == 'licensed'


def test_official_display_does_not_expose_old_licensed_values_or_deltas():
    import copy
    import argus_market_ledger as ledger
    legacy = {'seriesId':'credit.valuation_loss_pct', 'periodEnd':'2026-09-18',
              'availableFrom':'2026-09-23T06:00:00Z', 'value':-90, 'unit':'percent',
              'source':'manual legacy', 'sourceKind':'licensed'}
    state, _ = ledger.append_observation(ledger.empty_state(), legacy, now_iso='2026-10-05T15:00:00Z')
    original = copy.deepcopy(state['observations'])
    hidden = next(r for r in ledger.public_view(state, '2026-10-05T15:00:00Z')['table']
                  if r['seriesId'] == legacy['seriesId'])
    assert hidden['latestValue'] is hidden['historicalPercentile'] is hidden['fourPeriodDirection'] is None
    assert hidden['history'] == []
    state, _ = ledger.append_observation(state, row(), now_iso='2026-10-05T15:00:00Z')
    shown = next(r for r in ledger.public_view(state, '2026-10-05T15:00:00Z')['table']
                 if r['seriesId'] == legacy['seriesId'])
    assert shown['sourceKind'] == 'derived' and shown['latestValue'] == row()['value']
    assert len(shown['history']) == 1 and shown['previousChange'] is None
    assert state['observations'][:1] == original
    assert len(state['observations']) == 2


def test_past_cutoff_cannot_use_today_reconstructed_inputs():
    import argus_market_ledger as ledger
    import jp_market_engine as engine
    state, _ = ledger.append_observation(ledger.empty_state(), row(), now_iso='2026-10-05T15:00:00Z')
    assert ledger.effective_observations(state, '2026-09-30T00:00:00Z') == []
    before = engine.evaluate_d01(state['observations'], cutoff='2026-10-05T14:59:59Z')
    after = engine.evaluate_d01(state['observations'], cutoff='2026-10-05T15:00:00Z')
    assert before['features']['valuationLossPct'] is None
    assert after['features']['valuationLossPct'] == row()['value']
    assert after['validationStatus'] == 'UNVALIDATED'


@pytest.mark.parametrize('metadata', ['[]', '"text"', '{invalid', {'large':'x'*17000}, {'nonfinite':float('nan')}])
def test_invalid_metadata_is_rejected_without_mutating_ledger(metadata):
    import argus_market_ledger as ledger
    source = row(); source['metadata'] = metadata
    original = ledger.empty_state()
    result = ledger.import_rows(original, [source], now_iso='2026-10-05T15:00:00Z', dry_run=False)
    assert not result['ok'] and result['state'] == original


def test_csv_metadata_remains_optional_for_old_imports():
    import argus_market_ledger as ledger
    parsed = ledger.parse_csv('seriesId,periodEnd,availableFrom,value,unit,source\ncredit.short_balance,2026-09-25,2026-10-05T15:00:00Z,100,JPY,fixture\n')
    assert ledger.import_rows(ledger.empty_state(), parsed, now_iso='2026-10-05T15:00:00Z')['ok']


def test_history_keeps_compact_receipts_and_only_latest_full_inputs():
    import argus_market_ledger as ledger
    state = ledger.empty_state()
    first = row()
    state, _ = ledger.append_observation(state, first, now_iso='2026-10-05T15:00:00Z')
    second = v.ledger_observation({**v.calculate(inputs(buyAmountMillionJpy=1200)), 'periodEnd':'2026-10-02'},
        url=first['metadata']['sourceDocument']['url'], sha256='cd'*32, received_at='2026-10-06T08:00:00Z')
    state, _ = ledger.append_observation(state, second, now_iso='2026-10-06T08:00:00Z')
    history = next(r for r in ledger.public_view(state,'2026-10-06T08:00:00Z')['table']
                   if r['seriesId']==first['seriesId'])['history']
    assert len(history)==2 and all(len(r['calculationDigest'])==64 for r in history)
    assert 'auditedObservation' not in history[0]
    assert v.audited_ledger_observation(history[1]['auditedObservation'])
    assert len(state['observations'][0]['metadata']['valuationCalculation']['inputs']) == 6

from copy import deepcopy
import json
import pytest
import argus_jp_fiscal_monitor as fiscal
import argus_jp_fiscal_sources as sources
import argus_market_ledger as ledger

AT = '2026-09-16T05:04:00Z'


def test_reviewed_official_table_is_case_separated_and_not_an_observed_future():
    table = sources.reviewed_table()
    report = sources.fiscal_report(table, fiscal_year=2026, acquired_at=AT, as_of=AT)
    assert len(report['cases']) == 3
    for result in report['cases'].values():
        assert result['status'] == 'AVAILABLE'
        assert result['definition']['estimateType'] == 'FORECAST'
        assert result['values']['spreadPoints'] == pytest.approx(1.8)
        assert result['values']['pressurePoints'] == pytest.approx(-3.09242718446602)
        assert result['inputs']['debt_ratio']['year'] == 2025
        assert result['values']['effectiveRatePct'] == 1.2
        assert table['cases']['baseline']['market_yield'][2] == '2.7'
        assert result['otherStockFlowAdjustments'] is None
        assert result['probability'] is None
        assert not result['actionAuthority']
    assert report['sourceUpdateStatus'] == 'NOT_CHECKED'
    assert report['publishedAt'] is None


def test_repeated_revision_preserves_change_reason_instead_of_silently_clearing():
    rows = sources.annual_rows(sources.reviewed_table(), year=2026, case='baseline', acquired_at=AT)
    old = fiscal.calculate(rows, as_of=AT)
    revised = deepcopy(rows); revised['nominal_growth'].update(value=2., id='revision')
    change = fiscal.calculate(revised, as_of=AT, previous=old)
    assert 'GROWTH_RATE_GAP_NARROWED' in change['reasons']
    again = fiscal.calculate(revised, as_of=AT, previous=change)
    assert again['id'] == change['id']
    assert again['reasons'] == change['reasons']
    assert fiscal.transition(change, again)['event'] is None


def test_existing_ledger_roundtrip_reuses_identical_inputs_without_losing_revision(monkeypatch):
    monkeypatch.setattr(ledger, 'SERIES', {**ledger.SERIES, **sources.ledger_series()})
    table = sources.reviewed_table()
    candidates = sources.annual_ledger_candidates(table, acquired_at=AT)
    result = ledger.import_rows(ledger.empty_state(), candidates, now_iso=AT,
        dry_run=False, rebuild_after_commit=False)
    assert result['ok'], result.get('errors')
    saved = json.loads(json.dumps(result['state']))
    assert sources.missing_ledger_candidates(saved, candidates) == []
    for case in table['cases']:
        rows = sources.ledger_fiscal_inputs(saved, year=2026, case=case, as_of=AT)
        assert fiscal.calculate(rows, as_of=AT)['status'] == 'AVAILABLE'
    # The ordinary macro panel must not silently present 2040 projections as current values.
    assert ledger.effective_observations(saved, AT) == []
    assert sources.ledger_fiscal_inputs(saved, year=2026, case='baseline', as_of='2026-09-15T00:00:00Z') == {}
    previous_count = len(saved['observations'])
    revision = deepcopy(candidates[0]); revision['metadata']['fiscalInput']['id'] = 'revised-source'
    revision['availableFrom'] = '2026-09-16T05:05:00Z'
    newer = ledger.import_rows(saved, [revision], now_iso=revision['availableFrom'],
        dry_run=False, rebuild_after_commit=False)
    assert newer['ok']
    assert len(newer['state']['observations']) == previous_count+1


def csv_bytes(cells):
    return ('国債金利情報 (令和8年9月),,,,,\n基準日,10年,20年,30年,40年\n'+cells+'\n').encode('cp932')


def test_market_rates_keep_instrument_and_missing_cells():
    rows = sources.parse_jgb_csv(csv_bytes('R8.9.15,1.123,-,3.456,4.567'), acquired_at=AT)
    assert len(rows) == 4 and rows[1]['value'] is None
    assert rows[1]['acquisitionStatus'] == 'MISSING'
    assert rows[0]['publishedAt'] is None
    assert rows[0]['rateBasis'] == 'MARKET_YIELD'
    assert rows[0]['sessionDate'] == '2026-09-15'
    assert rows[0]['compounding'] == 'SEMIANNUAL'
    annual = sources.annual_rows(sources.reviewed_table(), year=2026, case='baseline', acquired_at=AT)
    annual['effective_rate'] = rows[0]
    assert fiscal.calculate(annual, as_of=AT)['status'] == 'DATA_GATED'


@pytest.mark.parametrize('cells', ['R8.9.17,1.123,2.345,3.456,4.567',
    'R8.9.15,NaN,2.345,3.456,4.567', 'R8.9.15,1.123,2.345,3.456',
    'R8.9.15,1.123,2.345,3.456,4.567\nR8.9.15,1.123,2.345,3.456,4.567'])
def test_unusable_market_source_does_not_become_normal(cells):
    with pytest.raises(ValueError):sources.parse_jgb_csv(csv_bytes(cells), acquired_at=AT)


def test_market_ledger_preserves_receipt_revisions_and_missing_values(monkeypatch):
    monkeypatch.setattr(ledger,'SERIES',{**ledger.SERIES,**sources.ledger_series()})
    original=sources.parse_jgb_csv(csv_bytes('R8.9.15,1.123,-,3.456,4.567'),acquired_at=AT)
    candidates=sources.market_ledger_candidates(original)
    imported=ledger.import_rows(ledger.empty_state(),candidates,now_iso=AT,dry_run=False,rebuild_after_commit=False)
    assert imported['ok'],imported.get('errors')
    saved=json.loads(json.dumps(imported['state']))
    assert len(sources.ledger_market_rows(saved,as_of=AT))==4
    assert sources.ledger_market_rows(saved,as_of='2026-09-16T05:00:00Z')==[]
    repeat=sources.parse_jgb_csv(csv_bytes('R8.9.15,1.123,-,3.456,4.567'),acquired_at='2026-09-16T06:00:00Z')
    assert sources.missing_market_candidates(saved,sources.market_ledger_candidates(repeat))==[]
    changed=sources.parse_jgb_csv(csv_bytes('R8.9.15,1.124,2.345,3.456,4.567'),acquired_at='2026-09-16T06:00:00Z')
    diff=sources.missing_market_candidates(saved,sources.market_ledger_candidates(changed))
    assert len(diff)==2
    updated=ledger.import_rows(saved,diff,now_iso='2026-09-16T06:00:00Z',dry_run=False,rebuild_after_commit=False)
    assert updated['ok']
    assert len(updated['state']['observations'])==6
    old=sources.ledger_market_rows(updated['state'],as_of=AT)
    current=sources.ledger_market_rows(updated['state'],as_of='2026-09-16T06:01:00Z')
    assert old[0]['value']==1.123 and current[0]['value']==1.124
    assert old[1]['value'] is None and current[1]['value']==2.345
    assert len(sources.missing_market_candidates(updated['state'],sources.market_ledger_candidates(repeat)))==2
    assert ledger.effective_observations(updated['state'],'2026-09-16T06:01:00Z')==[]


def test_saved_ledger_connects_fiscal_cases_and_market_without_network_or_new_rows(monkeypatch):
    monkeypatch.setattr(ledger, 'SERIES', {**ledger.SERIES, **sources.ledger_series()})
    candidates = sources.annual_ledger_candidates(sources.reviewed_table(), acquired_at=AT)
    rates = sources.parse_jgb_csv(csv_bytes('\n'.join(
        f'R8.9.{day},{1+i/100:.3f},{2+i/100:.3f},{3+i/100:.3f},{4+i/100:.3f}'
        for i,day in enumerate((8,9,10,11,14,15)))), acquired_at=AT)
    candidates += sources.market_ledger_candidates(rates)
    imported = ledger.import_rows(ledger.empty_state(), candidates, now_iso=AT,
        dry_run=False, rebuild_after_commit=False)
    assert imported['ok'], imported.get('errors')
    saved = json.loads(json.dumps(imported['state']))
    before = deepcopy(saved)
    report = sources.ledger_environment_report(saved, fiscal_year=2026,
        expected_session='2026-09-15', as_of=AT)
    assert saved == before and report['selectedCase'] is None
    assert report['fetchesDuringRead'] == report['aiCallsDuringRead'] == 0
    for case, value in report['cases'].items():
        assert value['fiscal']['definition']['scenario'] == case
        assert value['fiscal']['definition']['estimateType'] == 'FORECAST'
        assert value['fiscal']['values']['spreadPoints'] == pytest.approx(1.8)
        assert value['market']['groups']['JGB']['adverse'] is True
        assert value['market']['groups']['FX']['status'] == 'MISSING'
        assert value['dataCompleteness'] == 'INCOMPLETE'
        assert value['notificationCandidate']['deliveryConfirmed'] is False
    repeated = sources.ledger_environment_report(saved, fiscal_year=2026,
        expected_session='2026-09-15', as_of='2026-09-16T06:00:00Z', previous=report)
    assert repeated['id'] == report['id']
    assert all(v['notificationCandidate'] is None for v in repeated['cases'].values())
    failed = sources.ledger_environment_report(saved, fiscal_year=2026,
        expected_session='2026-09-16', as_of='2026-09-17T06:00:00Z', previous=report,
        market_acquisition='FAILED')
    assert all(v['previousWarningRetained'] and v['notificationCandidate'] is None
        for v in failed['cases'].values())

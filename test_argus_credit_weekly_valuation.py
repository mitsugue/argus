import copy
import json
from datetime import date

import argus_market_ledger as ledger
import argus_jpx_credit_valuation as valuation
import scripts.jpx_credit_weekly as jw
from test_argus_jpx_credit_valuation import new_grid

STAMP = '2026-10-05T15:00:00Z'
URL = jw.NEW_URL_TEMPLATE.format(ymd='20260925')


def collect(monkeypatch, since='2026-09-18', valuation_since='2026-09-18'):
    monkeypatch.setattr(jw, 'load_workbook_grid', lambda _: new_grid())
    return jw.collect(since, valuation_since=valuation_since, today=date(2026,9,25),
                      fetcher=lambda _:b'workbook', listing_fetcher=lambda:{'2026-09-25':URL}, now_iso=STAMP)


def test_one_fetch_yields_balances_and_six_input_calculation_with_real_receipt(monkeypatch):
    result=collect(monkeypatch)
    assert result['failures']==[] and len(result['rows'])==3
    row=result['rows'][-1]
    assert valuation.audited_ledger_observation(row)
    assert row['availableFrom']==row['observedAt']==STAMP and row['publishedAt']==''
    assert row['value']==valuation.extract(new_grid())['value']
    parsed=ledger.parse_csv(result['csv'])
    assert parsed[-1]['metadata']==row['metadata']
    imported=ledger.import_rows(ledger.empty_state(),parsed,now_iso=STAMP,dry_run=False)
    assert imported['ok'] and len(imported['preview'])==3
    assert valuation.audited_ledger_observation(imported['preview'][-1])


def test_valuation_backfill_does_not_reimport_already_held_balances(monkeypatch):
    result=collect(monkeypatch,since='2026-09-25')
    assert [x['seriesId'] for x in result['rows']]==['credit.valuation_loss_pct']
    assert valuation.audited_ledger_observation(result['rows'][0])
    called=[]
    none=jw.collect('2026-09-25',valuation_since='2026-09-25',today=date(2026,9,25),
                    fetcher=lambda url:called.append(url),listing_fetcher=lambda:{},now_iso=STAMP)
    assert none['rows']==[] and called==[]


def test_missing_financing_inputs_keeps_balances_but_is_a_failure_not_zero(monkeypatch):
    grid=new_grid();grid[16][1]='lending instead of financing'
    monkeypatch.setattr(jw,'load_workbook_grid',lambda _:grid)
    result=jw.collect('2026-09-18',valuation_since='2026-09-18',today=date(2026,9,25),
                      fetcher=lambda _:b'workbook',listing_fetcher=lambda:{'2026-09-25':URL},now_iso=STAMP)
    assert len(result['rows'])==2
    assert result['failures']==['2026-09-25:valuation_inputs_unreadable']


def test_transport_settlement_requires_every_imported_calculation_digest(monkeypatch):
    result=collect(monkeypatch)
    parsed=ledger.parse_csv(result['csv'])
    imported=ledger.import_rows(ledger.empty_state(),parsed,now_iso=STAMP,dry_run=False)
    view=ledger.public_view(imported['state'],STAMP)
    readback={x['seriesId']:{'periodEnd':x['periodEnd'],'latestValue':x['latestValue'],
              'availableFrom':x['availableFrom'],'history':x['history']} for x in view['table']}
    def post(url,body,token):
        if body['dryRun']:return {'ok':True}
        raise TimeoutError('protected transport body')
    monkeypatch.setattr(jw,'post_json',post)
    monkeypatch.setattr(jw,'ledger_newest_credit',lambda *a,**k:readback)
    ok=jw.import_rows(result['csv'],backend='https://fixture.test',token='secret',expected_newest='2026-09-25')
    assert ok['ok'] and ok['settledByReadback']
    history=readback['credit.valuation_loss_pct']['history']
    original=copy.deepcopy(history)
    for change in ('digest','audit','value','receipt'):
        history[:]=copy.deepcopy(original)
        if change=='digest':history[-1]['calculationDigest']='0'*64
        if change=='audit':history[-1]['auditedObservation']['metadata']['sourceDocument']['sha256']='0'*64
        if change=='value':history[-1]['value']=0
        if change=='receipt':history[-1]['availableFrom']='2026-10-05T14:59:59Z'
        assert jw.import_rows(result['csv'],backend='https://fixture.test',token='secret',expected_newest='2026-09-25')['stage']=='readback_content'


def test_valuation_only_readback_does_not_require_or_rewrite_balance_series(monkeypatch):
    result=collect(monkeypatch,since='2026-09-25')
    imported=ledger.import_rows(ledger.empty_state(),ledger.parse_csv(result['csv']),now_iso=STAMP,dry_run=False)
    value=next(x for x in ledger.public_view(imported['state'],STAMP)['table'] if x['seriesId']=='credit.valuation_loss_pct')
    monkeypatch.setattr(jw,'post_json',lambda *a,**k:{'ok':True})
    monkeypatch.setattr(jw,'ledger_newest_credit',lambda *a,**k:{value['seriesId']:value})
    assert jw.import_rows(result['csv'],backend='https://fixture.test',token='secret')['ok']
    assert jw.valuation_cursor([value])=='2026-09-25'
    value['history'][-1]['auditedObservation']['sourceKind']='licensed'
    assert jw.valuation_cursor([value])=='2026-07-10'


def test_all_backfilled_periods_must_be_read_back_not_only_latest(monkeypatch):
    result=collect(monkeypatch,since='2026-09-25')
    newer=copy.deepcopy(result['rows'][0]);newer['periodEnd']='2026-10-02'
    rows=[result['rows'][0],newer];text=jw.rows_to_csv(rows)
    imported=ledger.import_rows(ledger.empty_state(),ledger.parse_csv(text),now_iso=STAMP,dry_run=False)
    value=next(x for x in ledger.public_view(imported['state'],STAMP)['table'] if x['seriesId']=='credit.valuation_loss_pct')
    monkeypatch.setattr(jw,'post_json',lambda *a,**k:{'ok':True})
    monkeypatch.setattr(jw,'ledger_newest_credit',lambda *a,**k:{value['seriesId']:value})
    assert jw.import_rows(text,backend='https://fixture.test',token='secret')['ok']
    value['history']=value['history'][-1:]
    assert jw.import_rows(text,backend='https://fixture.test',token='secret')['stage']=='readback_content'


def test_import_exception_is_fixed_public_status_without_protected_body(monkeypatch,capsys):
    result=collect(monkeypatch)
    monkeypatch.setattr(jw,'collect',lambda *a,**k:result)
    monkeypatch.setenv('ARGUS_ADMIN_TOKEN','fixture-private-token')
    def fail(*a,**k):raise ValueError('private response content')
    monkeypatch.setattr(jw,'import_rows',fail)
    assert jw.main(['--import','--valuation-since','2026-09-18'])==1
    text=capsys.readouterr().out
    assert json.loads(text)=={'ok':False,'stage':'authenticated_import'}
    assert 'private' not in text

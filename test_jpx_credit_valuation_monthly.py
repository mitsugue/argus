import copy
import hashlib
import json

import pytest
import argus_jpx_credit_valuation as valuation
import argus_market_ledger as ledger
import scripts.jpx_credit_valuation_monthly as monthly
import scripts.jpx_credit_weekly as weekly
from test_argus_jpx_credit_valuation import inputs

STAMP='2026-10-05T16:00:00Z'


def index(years=(2026,),months=(3,6,8)):
    options=''.join(f'<option value="index.html">{year}年</option>' for year in years)
    links=''.join(f'<a href="a-att/12_sinyou26{m:02d}.pdf">{m}月</a>' for m in months)
    return f'<select>{options}</select><table><tr><td>信用取引現在高</td><td>{links}</td></tr></table>'.encode()


def record(period='2026-02-27'):
    return dict(valuation.calculate(inputs()),periodEnd=period)


def fetcher(url,limit):
    return index() if url.endswith('.html') else b'%PDF-fixture'


def test_complete_backfill_deduplicates_inputs_and_uses_actual_receipt_only():
    rows=monthly.collect([],start_year=2026,end_year=2026,fetcher=fetcher,
                         parser=lambda _: [record()],clock=lambda:STAMP)
    assert len(rows)==1 and valuation.audited_ledger_observation(rows[0])
    assert rows[0]['publishedAt']=='' and rows[0]['availableFrom']==STAMP
    assert rows[0]['metadata']['retrospective'] is True
    assert rows[0]['metadata']['historicalVintageVerified'] is False
    state=ledger.import_rows(ledger.empty_state(),rows,now_iso=STAMP,dry_run=False)['state']
    assert ledger.effective_observations(state,'2026-02-28T00:00:00Z')==[]
    table=ledger.public_view(state,STAMP)['table']
    before=copy.deepcopy(state)
    assert monthly.collect(table,start_year=2026,end_year=2026,fetcher=fetcher,
                           parser=lambda _: [record()],clock=lambda:STAMP)==[]
    assert state==before


def test_legacy_or_unverified_histories_cannot_skip_new_official_inputs():
    table=[{'seriesId':'credit.valuation_loss_pct','sourceKind':'licensed',
            'history':[{'periodEnd':'2026-02-27','calculationDigest':'0'*64}]}]
    assert monthly.held_periods(table)==set()
    table[0].update(sourceKind='derived',acquisition='jpx_official_formula')
    assert monthly.held_periods(table)==set()


def test_conflicting_duplicate_or_month_future_period_aborts_entire_backfill():
    calls=[]
    def parse(_):
        calls.append(1)
        result=record()
        if len(calls)>1:result=valuation.calculate(inputs(buyAmountMillionJpy=900));result['periodEnd']='2026-02-27'
        return [result]
    with pytest.raises(ValueError,match='input_conflict'):
        monthly.collect([],start_year=2026,end_year=2026,fetcher=fetcher,parser=parse,clock=lambda:STAMP)
    with pytest.raises(ValueError,match='future_period'):
        monthly.collect([],start_year=2026,end_year=2026,fetcher=fetcher,
                        parser=lambda _:[record('2026-04-03')],clock=lambda:STAMP)


@pytest.mark.parametrize('url',['http://www.jpx.co.jp/markets/statistics-equities/monthly/index.html',
 'https://elsewhere.test/a.pdf','https://www.jpx.co.jp/markets/statistics-equities/monthly/../a.pdf',
 'https://www.jpx.co.jp/markets/statistics-equities/monthly/%2e%2e/a.pdf',
 'https://www.jpx.co.jp/markets/statistics-equities/monthly/a.pdf?token=x'])
def test_source_and_redirect_boundary_rejects_other_hosts_or_ambiguous_paths(url):
    with pytest.raises(ValueError,match='source_invalid'):monthly.official_url(url)


def test_missing_year_or_quarter_fails_instead_of_claiming_full_coverage():
    with pytest.raises(ValueError,match='years_missing'):
        monthly.selected_sources(monthly.parse_index(index()),start_year=2016,end_year=2026)
    first=monthly.parse_index(index(years=(2025,2026)))
    with pytest.raises(ValueError,match='period_invalid'):
        monthly.selected_sources(first,start_year=2025,end_year=2026)
    with pytest.raises(ValueError,match='year_range'):
        monthly.selected_sources(first,start_year=2015,end_year=2026)


def test_monthly_mode_writes_only_missing_valuation_rows_and_verifies_them(monkeypatch,capsys):
    calls=[]
    row=valuation.ledger_observation(record(),url=monthly.INDEX.replace('index.html','a-att/12_sinyou2603.pdf'),
         sha256=hashlib.sha256(b'fixture').hexdigest(),received_at=STAMP,retrospective=True)
    monkeypatch.setenv('ARGUS_ADMIN_TOKEN','private-token')
    monkeypatch.setattr(weekly,'ledger_newest_credit',lambda *a,**k:{})
    monkeypatch.setattr(monthly,'collect',lambda _: [row])
    def post(text,**kwargs):
        values=ledger.parse_csv(text)
        assert [r['seriesId'] for r in values]==['credit.valuation_loss_pct']
        assert kwargs['expected_newest'] is None
        calls.append(values)
        return {'ok':True,'stage':'verified_import','ledger':{'private':'owner-response'}}
    monkeypatch.setattr(weekly,'import_rows',post)
    assert weekly.main(['--import','--valuation-monthly-backfill'])==0
    assert len(calls)==1
    assert json.loads(capsys.readouterr().out)=={'ok':True,'stage':'verified_import'}


def test_monthly_library_is_only_enabled_for_explicit_backfill():
    from pathlib import Path
    text=Path('.github/workflows/jpx-credit-weekly.yml').read_text()
    assert "github.event_name == 'workflow_dispatch' && inputs.valuation_monthly_backfill" in text
    assert 'pdfplumber==0.11.7' in text
    assert 'actions/upload-artifact' not in text and '$RUNNER_TEMP/jpx-credit-summary.json' in text

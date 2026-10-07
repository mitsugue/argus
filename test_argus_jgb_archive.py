from copy import deepcopy
from datetime import datetime
import json

import pytest
import xlrd

import argus_jgb_auction as auction
import argus_jp_fiscal_runtime as runtime
import argus_market_ledger as ledger

AT = '2026-10-08T02:00:00+09:00'


class Sheet:
    def __init__(self,tenor):
        self.name=f'{tenor}年債'
        labels=['回号','入札日','発行日','償還日','表面利率','発行予定額','応募額','落札・割当額']
        labels += ['最低価格','最高利回','第Ⅱ非価格競争'] if tenor==40 else ['平均価格','平均利回','最低価格','最高利回','第Ⅰ非価格競争','第Ⅱ非価格競争']
        unit={'応募額':'（億円）\n(100 million yen)','落札・割当額':'（億円）\n(100 million yen)',
              '平均利回':'（％）','最高利回':'（％）'}
        values={'回号':100,'入札日':42736,'応募額':1000.5,'落札・割当額':200,
                '最高利回':3.125,'平均利回':3.100,'第Ⅰ非価格競争':900,'第Ⅱ非価格競争':900}
        self.rows=[['']*len(labels),['']*len(labels),labels,['']*len(labels),
                   [unit.get(k,'') for k in labels],[values.get(k,0) for k in labels]]
    @property
    def nrows(self):return len(self.rows)
    @property
    def ncols(self):return len(self.rows[2])
    def row_values(self,r):return self.rows[r][:]
    def cell_value(self,r,c):return self.rows[r][c]
    def set(self,r,label,value):self.rows[r][self.rows[2].index(label)]=value


class Book:
    datemode=0
    def __init__(self):self.sheets={f'{k}年債':Sheet(k) for k in auction.TENORS}; self.released=False
    def sheet_by_name(self,name):return self.sheets[name]
    def release_resources(self):self.released=True


def install(monkeypatch):
    book=Book()
    monkeypatch.setattr(xlrd,'open_workbook',lambda **kwargs:book)
    return book


def test_archive_units_competitive_only_and_no_backdated_clock(monkeypatch):
    book=install(monkeypatch)
    rows=auction.parse_archive(b'fixture',acquired_at=AT)
    assert len(rows)==4 and book.released
    assert rows[0]['competitiveBidAmountJpy']==100050000000
    assert rows[0]['competitiveAcceptedAmountJpy']==20000000000
    assert rows[0]['bidToCover']==pytest.approx(5.0025)
    assert rows[0]['yieldTailBp']==pytest.approx(2.5)
    assert rows[-1]['tenorYears']==40 and rows[-1]['yieldTailBp'] is None
    assert all(r['knownAt']==AT and r['publishedAt'] is None and r['publishedDate'] is None
               and r['historicalVintageVerified'] is False and r['actionAuthority'] is False for r in rows)
    assert all(r['sourceUrl']==auction.ARCHIVE_URL for r in rows)
    candidates=auction.ledger_candidates(rows)
    saved=ledger.import_rows(ledger.empty_state(),candidates,now_iso=AT,dry_run=False,rebuild_after_commit=False)
    assert saved['ok']
    restored=ledger.normalize_state(json.loads(json.dumps(saved['state'])))
    assert auction.saved_rows(restored,as_of='2026-10-07T23:00:00+09:00')==[]
    assert ledger.effective_observations(restored,AT)==[]
    assert auction.saved_rows(restored,as_of=AT)==rows
    assert auction.missing_candidates(restored,candidates)==[]


@pytest.mark.parametrize('label,value',[
    ('応募額',float('nan')),('応募額',True),('落札・割当額',0),
    ('落札・割当額',2000),('平均利回',4),('最高利回','―'),
    ('回号',1.5),('入札日',60000),('入札日',42736.5)])
def test_archive_rejects_bad_values_and_releases_workbook(monkeypatch,label,value):
    book=install(monkeypatch); book.sheets['10年債'].set(5,label,value)
    with pytest.raises(ValueError):auction.parse_archive(b'fixture',acquired_at=AT)
    assert book.released


def test_archive_rejects_changed_unit_header_duplicate_session_and_empty_tenor(monkeypatch):
    for damage in ('unit','duplicate_header','duplicate_date','recent_only'):
        book=install(monkeypatch); sheet=book.sheets['10年債']
        if damage=='unit':sheet.set(4,'応募額','百万円')
        if damage=='duplicate_header':sheet.rows[2][-1]='応募額'
        if damage=='duplicate_date':sheet.rows.append(sheet.rows[5][:])
        if damage=='recent_only':sheet.set(5,'入札日',46300)
        with pytest.raises(ValueError):auction.parse_archive(b'fixture',acquired_at=AT)
        assert book.released


def test_archive_limits_bytes_before_opening(monkeypatch):
    monkeypatch.setattr(xlrd,'open_workbook',lambda **kwargs:pytest.fail('opened oversized source'))
    for raw in (b'',b'x'*1000001,'not bytes'):
        with pytest.raises(ValueError):auction.parse_archive(raw,acquired_at=AT)


def test_background_archive_reuses_ten_read_budget_saved_ledger_and_no_read_fetch(monkeypatch):
    from test_argus_jp_fiscal_runtime import fixture, calendar, Reply, AT as start
    get,calls,bodies,_=fixture(monkeypatch)
    initial=runtime.refresh(ledger.empty_state(),now_iso=start,calendar=calendar(),get=get)['state']
    assert len(calls)==10 and not initial['fiscalMonitor'].get('auctionArchiveSuccessAt')
    book=install(monkeypatch)
    bodies[auction.ARCHIVE_URL]=b'archive-fixture'
    before=deepcopy(initial)
    update=runtime.refresh(initial,now_iso='2026-09-17T07:00:01Z',calendar=calendar(),get=get)
    assert update['requests']==10 and initial==before
    state=update['state']; control=state['fiscalMonitor']
    assert control['auctionArchiveStatus']=='AVAILABLE' and book.released
    assert control['auctionArchiveHistoricalVintageVerified'] is False
    assert sum(v['rowCount'] for v in control['auctionArchiveReport']['series'].values())==4
    count=len(calls)
    view=runtime.public_document(ledger.normalize_state(json.loads(json.dumps(state))))
    assert view['auctionHistory']==control['auctionArchiveReport'] and len(calls)==count
    reference=runtime.context_reference(view)
    view['auctionHistory']['lastSuccessAt']='2026-09-18T07:00:01Z'
    assert runtime.context_reference(view)==reference
    # The reserved archive read leaves one native read for the next existing
    # retry; the archive is not fetched again in the same month.
    retry=runtime.refresh(state,now_iso='2026-09-17T08:00:02Z',calendar=calendar(),get=get)
    assert retry['requests']==10
    assert sum(url==auction.ARCHIVE_URL for url,_ in calls)==1
    assert retry['state']['fiscalMonitor']['auctionAcquisitionStatus']=='AVAILABLE'


def test_archive_failure_keeps_native_rows_no_repeat_or_exception_body(monkeypatch):
    from test_argus_jp_fiscal_runtime import fixture,calendar,AT as start
    get,calls,_,_=fixture(monkeypatch)
    first=runtime.refresh(ledger.empty_state(),now_iso=start,calendar=calendar(),get=get)['state']
    def failing(url,**kwargs):
        if url==auction.ARCHIVE_URL:raise TimeoutError('private source response must not be stored')
        return get(url,**kwargs)
    result=runtime.refresh(first,now_iso='2026-09-17T07:00:01Z',calendar=calendar(),get=failing)
    assert result['requests']==10 and result['state']['observations']==first['observations']
    assert result['state']['fiscalMonitor']['auctionArchiveStatus']=='ARCHIVE_ACQUISITION_FAILED'
    assert 'private source response' not in json.dumps(result)
    retry=runtime.refresh(result['state'],now_iso='2026-09-17T08:00:02Z',calendar=calendar(),get=failing)
    assert retry['requests']==10


def test_missing_native_input_does_not_block_independent_archive(monkeypatch):
    from test_argus_jp_fiscal_runtime import fixture,calendar,AT as start
    get,_,bodies,_=fixture(monkeypatch)
    first=runtime.refresh(ledger.empty_state(),now_iso=start,calendar=calendar(),get=get)['state']
    first['fiscalMonitor']['auctionAcquisitionStatus']='FAILED'
    install(monkeypatch); bodies[auction.ARCHIVE_URL]=b'archive-fixture'
    def broken_native(url,**kwargs):
        if url.startswith(auction.ROOT):raise TimeoutError('fixture')
        return get(url,**kwargs)
    result=runtime.refresh(first,now_iso='2026-09-16T08:00:01Z',calendar=calendar(),get=broken_native)
    assert result['requests']==7
    assert result['state']['fiscalMonitor']['auctionArchiveStatus']=='AVAILABLE'
    assert result['state']['fiscalMonitor']['auctionAcquisitionStatus']=='FAILED'
    assert len(auction.saved_rows(result['state'],as_of='2026-09-16T08:00:01Z'))==8


def test_bounded_native_budget_requires_five_or_six():
    for budget in (True,4,7,None):
        with pytest.raises(ValueError):auction.collect({},as_of=AT,read=lambda *a:pytest.fail('network'),max_requests=budget)

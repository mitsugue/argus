import json
from copy import deepcopy

import pytest

import argus_earnings_history as history
import jp_market_acquisition as sources

AT = '2026-10-06T10:00:00Z'
LATER = '2026-10-07T10:00:00Z'


def row(**changes):
    return dict(Code='10000', DiscDate='2026-10-06', DiscTime='15:31:00', DiscNo='100',
                DocType='ForecastRevision', CurPerType='2Q', CurFYEn='2027-03-31',
                FOP='1000000000', NxFOP='', **changes)


def test_history_preserves_forecasts_receipts_and_revisions_without_dividend_overwrite(tmp_path):
    path = tmp_path/'shared.sqlite3'
    original = row(); original['OwnerSecret'] = 'must-not-store'
    before = deepcopy(original)
    first = history.retain(path, [original], received_at=AT, member_codes=['1000'], query_date='2026-10-06')
    assert first['newObservations'] == 1 and original == before
    assert history.retain(path, [original], received_at=LATER, member_codes=['1000'])['newObservations'] == 0
    revised = {**original, 'FOP': '1100000000'}
    assert history.retain(path, [revised], received_at=LATER, member_codes=['1000'])['newObservations'] == 1
    past = history.read(path, cutoff=AT, member_codes=['1000'])
    assert len(past) == 1 and past[0]['summary']['FOP'] == '1000000000'
    assert 'OwnerSecret' not in past[0]['summary'] and past[0]['knownAt'] == AT
    assert history.read(path, cutoff='2026-10-06T06:00:00Z', member_codes=['1000']) == []
    restarted = history.read(path, cutoff=LATER, member_codes=['1000'])
    assert len(restarted) == 2 and [r['receivedAt'] for r in restarted] == [AT, LATER]
    assert all(not r['historicalVintageVerified'] for r in restarted)
    db = sources.connect(path)
    sources.verify_raw(db)
    assert path.stat().st_mode & 0o777 == 0o600
    db.execute("UPDATE observations SET body=replace(body,'1000000000','9900000000')")
    db.commit(); db.close()
    with pytest.raises(ValueError, match='integrity'):
        history.read(path, cutoff=LATER, member_codes=['1000'])


def test_empty_success_future_invalid_and_unrelated_issuers_are_distinct(tmp_path):
    path = tmp_path/'shared.sqlite3'
    bad = {**row(), 'DiscTime': '23:00:00'}
    result = history.retain(path, [bad, {**row(), 'Code': '99990'}], received_at=AT, member_codes=['1000'])
    assert result['status'] == 'PARTIAL' and result['rejectedRows'] == 1 and result['retainedRows'] == 0
    result = history.retain(path, [], received_at=LATER, member_codes=['1000'], query_date='2026-10-07')
    assert result['status'] == 'RECEIVED' and result['retainedRows'] == 0
    db = sources.connect(path)
    stored = json.loads(db.execute("SELECT value FROM metadata WHERE key='financial-summary-date:2026-10-07'").fetchone()[0])
    assert stored['receivedAt'] == LATER and not stored['goodEarningsRuleDefined']
    db.close()


def test_read_does_not_create_store_and_empty_fields_are_not_zero(tmp_path):
    path = tmp_path/'not-created.sqlite3'
    assert history.read(path, cutoff=AT, member_codes=['1000']) == [] and not path.exists()
    raw = {**row(), 'FOP': '', 'DiscTime': ''}
    history.retain(path, [raw], received_at=AT, member_codes=['1000'])
    result = history.read(path, cutoff=AT, member_codes=['1000'])[0]
    assert result['summary']['FOP'] == '' and result['publishedAt'] is None


def test_existing_dividend_acquisition_is_shared_without_extra_requests(monkeypatch, tmp_path):
    import scanner
    monkeypatch.setattr(scanner, '_JP_DIVIDEND_STORE', {'rows': {}, 'fetchedAt': {}, 'closes': None,
        'restoreAttempted': True, 'lastError': None, 'requestsLastWarm': 0})
    monkeypatch.setattr(scanner, '_JP_EARNINGS_HISTORY_STATUS', {})
    monkeypatch.setattr(scanner, '_cost_policy_durable_enabled', lambda: True)
    monkeypatch.setattr(scanner, '_DURABILITY_PATHS', {'root': str(tmp_path)})
    monkeypatch.setattr(scanner, '_nikkei225_constituent_changes', lambda: {'rows': []})
    monkeypatch.setattr(scanner, '_JQUANTS_API_KEY', 'test')
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: AT)
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args)
        return [{**row(), 'FDivFY': '50'}, {**row(), 'DiscDate': '2026-09-01', 'FOP': '900000000'}]
    monkeypatch.setattr(scanner, '_jquants_paginated', fetch)
    scanner._jp_dividend_warm(['1000'])
    assert len(calls) == 1
    assert scanner._JP_DIVIDEND_STORE['rows']['1000']['FDivFY'] == '50'
    assert 'FOP' not in scanner._JP_DIVIDEND_STORE['rows']['1000']
    assert len(history.read(tmp_path/'jp_market_source_history.sqlite3', cutoff=AT, member_codes=['1000'])) == 2
    scanner._jp_dividend_warm(['1000'])
    assert len(calls) == 1


def test_complete_date_scope_needs_225_members_and_original_receipt(tmp_path):
    path=tmp_path/'shared.sqlite3';members=[str(1000+i) for i in range(225)]
    history.retain(path,[],received_at=AT,member_codes=members,query_date='2026-10-06')
    assert history.read_coverage(path,cutoff=AT)['2026-10-06']['complete'] is False
    history.retain(path,[],received_at=LATER,member_codes=members,query_date='2026-10-06',complete_scope=members)
    assert history.read_coverage(path,cutoff=LATER)['2026-10-06']['complete'] is True
    assert history.read_coverage(path,cutoff=AT)['2026-10-06']['complete'] is False
    db=sources.connect(path)
    db.execute("UPDATE metadata SET value=replace(value,'225','224')")
    db.commit();db.close()
    with pytest.raises(ValueError,match='integrity'):history.read_coverage(path,cutoff=LATER)


def test_whole_company_receipt_is_separate_from_date_cohort_and_deduplicated(tmp_path):
    path=tmp_path/'shared.sqlite3'
    assert history.completed_codes(path,cutoff=AT,member_codes=['1000'])==set()
    assert not path.exists()
    history.retain(path,[],received_at=AT,member_codes=['1000'],query_code='1000')
    assert history.completed_codes(path,cutoff=AT,member_codes=['1000'])=={'1000'}
    assert history.completed_codes(path,cutoff='2026-10-06T06:00:00Z',member_codes=['1000'])==set()
    assert history.read_coverage(path,cutoff=AT)=={}
    history.retain(path,[],received_at=AT,member_codes=['1000'],query_code='1000')
    db=sources.connect(path)
    assert db.execute("SELECT count(*) FROM metadata WHERE key LIKE 'financial-summary-code:%'").fetchone()[0]==1
    db.execute("UPDATE metadata SET value=replace(value,'true','false')")
    db.commit();db.close()
    with pytest.raises(ValueError,match='integrity'):history.completed_codes(path,cutoff=AT,member_codes=['1000'])


def test_wrong_issuer_or_rejected_forecast_is_not_complete_company_history(tmp_path):
    path=tmp_path/'shared.sqlite3'
    history.retain(path,[{**row(),'Code':'99990'}],received_at=AT,member_codes=['1000'],query_code='1000')
    assert history.completed_codes(path,cutoff=AT,member_codes=['1000'])==set()
    history.retain(path,[{**row(),'DiscTime':'23:00:00'}],received_at=AT,member_codes=['1000'],query_code='1000')
    assert history.completed_codes(path,cutoff=AT,member_codes=['1000'])==set()


def test_old_dividend_refresh_does_not_hide_missing_financial_originals(monkeypatch,tmp_path):
    import scanner
    from unittest.mock import Mock
    monkeypatch.setattr(scanner,'_JP_EARNINGS_BACKFILL_ATTEMPTS',{})
    monkeypatch.setattr(scanner,'_JP_DIVIDEND_STORE',dict(rows={},fetchedAt={'1000':1000},closes=None,restoreAttempted=True,lastError=None,requestsLastWarm=0))
    monkeypatch.setattr(scanner,'_JP_EARNINGS_HISTORY_STATUS',{})
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:True)
    monkeypatch.setattr(scanner,'_DURABILITY_PATHS',{'root':str(tmp_path)})
    monkeypatch.setattr(scanner,'_nikkei225_constituent_changes',lambda:{'rows':[]})
    monkeypatch.setattr(scanner,'_JQUANTS_API_KEY','test')
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:AT)
    monkeypatch.setattr(scanner.time,'time',lambda:1001)
    fetch=Mock(return_value=[row()]);monkeypatch.setattr(scanner,'_jquants_paginated',fetch)
    scanner._jp_dividend_warm(['1000'])
    assert fetch.call_count==1
    assert history.completed_codes(tmp_path/'jp_market_source_history.sqlite3',cutoff=AT,member_codes=['1000'])=={'1000'}
    scanner._jp_dividend_warm(['1000'])
    assert fetch.call_count==1


def test_failed_backfill_is_bounded_and_retries_without_falsifying_receipt(monkeypatch,tmp_path):
    import scanner
    from unittest.mock import Mock
    monkeypatch.setattr(scanner,'_JP_EARNINGS_BACKFILL_ATTEMPTS',{})
    monkeypatch.setattr(scanner,'_JP_DIVIDEND_STORE',dict(rows={},fetchedAt={str(1000+i):1000 for i in range(25)},closes=None,restoreAttempted=True,lastError=None,requestsLastWarm=0))
    monkeypatch.setattr(scanner,'_JP_EARNINGS_HISTORY_STATUS',{})
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:True)
    monkeypatch.setattr(scanner,'_DURABILITY_PATHS',{'root':str(tmp_path)})
    monkeypatch.setattr(scanner,'_JQUANTS_API_KEY','test')
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:AT)
    now=[1001];monkeypatch.setattr(scanner.time,'time',lambda:now[0])
    fetch=Mock(side_effect=RuntimeError('synthetic'));monkeypatch.setattr(scanner,'_jquants_paginated',fetch)
    codes=[str(1000+i) for i in range(25)]
    scanner._jp_dividend_warm(codes);assert fetch.call_count==20
    scanner._jp_dividend_warm(codes);assert fetch.call_count==25
    scanner._jp_dividend_warm(codes);assert fetch.call_count==25
    now[0]+=300;scanner._jp_dividend_warm(codes);assert fetch.call_count==45
    assert history.completed_codes(tmp_path/'jp_market_source_history.sqlite3',cutoff=AT,member_codes=codes)==set()


def test_missing_original_backfill_stops_at_existing_collection_budget(monkeypatch,tmp_path):
    import scanner
    from unittest.mock import Mock
    monkeypatch.setattr(scanner,'_JP_EARNINGS_BACKFILL_ATTEMPTS',{'9999':1})
    monkeypatch.setattr(scanner,'_JP_DIVIDEND_STORE',dict(rows={},fetchedAt={},closes=None,restoreAttempted=True,lastError=None,requestsLastWarm=0))
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:False)
    monkeypatch.setattr(scanner,'_JQUANTS_API_KEY','test')
    clock=iter([0,0,150]);monkeypatch.setattr(scanner.time,'monotonic',lambda:next(clock))
    fetch=Mock(side_effect=RuntimeError('synthetic'));monkeypatch.setattr(scanner,'_jquants_paginated',fetch)
    scanner._jp_dividend_warm(['1000','1001'])
    assert fetch.call_count==1
    assert '1001' not in scanner._JP_EARNINGS_BACKFILL_ATTEMPTS
    assert '9999' not in scanner._JP_EARNINGS_BACKFILL_ATTEMPTS

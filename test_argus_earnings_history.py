import json
from copy import deepcopy

import pytest

import argus_earnings_history as history
import jp_market_acquisition as sources

AT = '2026-10-06T10:00:00Z'
LATER = '2026-10-07T10:00:00Z'


def test_acquisition_universe_includes_former_members_but_not_future_changes():
    current = {str(1000+i) for i in range(225)}
    changes = {'schemaVersion':'nikkei225-constituent-changes-v1', 'rows':[
        {'effective':'2016-10-03','removed':['9000'],'added':['1000']},
        {'effective':'2026-10-01','removed':['9001'],'added':['1001']},
        {'effective':'2026-10-09','removed':['9002'],'added':['1002']} ]}
    before = deepcopy(changes)
    assert set(history.acquisition_members(current,changes,through='2026-10-07')) == current|{'9000','9001'}
    assert changes == before
    with pytest.raises(ValueError,match='membership_history'):
        history.acquisition_members(current,None,through='2026-10-07')
    changes['rows'][0]['removed']=['../owner']
    with pytest.raises(ValueError,match='membership_history'):
        history.acquisition_members(current,changes,through='2026-10-07')


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


def test_company_coverage_reads_original_identities_span_and_latest_receipt_without_writes(tmp_path):
    import hashlib
    path=tmp_path/'shared.sqlite3'
    records=[{**row(),'DiscDate':'2026-07-01','DiscNo':'old'},row()]
    history.retain(path,records,received_at=AT,member_codes=['1000'],query_code='1000')
    history.retain(path,records,received_at=LATER,member_codes=['1000'],query_code='1000')
    before=path.read_bytes()
    proof=history.read_company_coverage(path,cutoff=LATER,member_codes=['1000'])['1000']
    # Owner decision 2026-10-22: the same response received again keeps the first receipt.
    assert proof['receivedAt']==AT and proof['firstDisclosureDay']=='2026-07-01'
    assert proof['lastDisclosureDay']=='2026-10-06'
    actual=history.read(path,cutoff=LATER,member_codes=['1000'])
    assert set(proof['observationIds'])=={r['observationId'] for r in actual}
    assert path.read_bytes()==before
    assert history.read_company_coverage(path,cutoff=AT,member_codes=['1000'])['1000']['receivedAt']==AT
    assert history.read_company_coverage(tmp_path/'absent',cutoff=AT,member_codes=['1000'])=={}


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


def test_registered_non_index_companies_use_existing_bounded_lane_and_original_store(monkeypatch, tmp_path):
    import scanner
    registered = [str(9000+i) for i in range(25)]
    monkeypatch.setattr(scanner, '_layer2b_read_latest', lambda: {'members':
        [{'market': 'JP', 'symbol': code+'.T', 'name': 'must-not-retain'} for code in registered]
        + [{'market': 'US', 'symbol': 'TEST'}, {'market': 'JP', 'symbol': '../invalid'}]})
    monkeypatch.setattr(scanner, '_JP_EARNINGS_BACKFILL_ATTEMPTS', {})
    monkeypatch.setattr(scanner, '_JP_DIVIDEND_STORE', dict(rows={}, fetchedAt={}, closes=None,
        restoreAttempted=True, lastError=None, requestsLastWarm=0))
    monkeypatch.setattr(scanner, '_JP_EARNINGS_HISTORY_STATUS', {})
    monkeypatch.setattr(scanner, '_cost_policy_durable_enabled', lambda: True)
    monkeypatch.setattr(scanner, '_DURABILITY_PATHS', {'root': str(tmp_path)})
    monkeypatch.setattr(scanner, '_nikkei225_constituent_changes', lambda: {'rows': []})
    monkeypatch.setattr(scanner, '_JQUANTS_API_KEY', 'test')
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: AT)
    calls = []
    def fetch(route, params, **bounds):
        assert route == '/fins/summary' and bounds == {'max_pages': 3, 'request_timeout': 15}
        calls.append(params['code'])
        return [{**row(), 'Code': params['code']+'0', 'DocType': '1QFinancialStatements', 'OP': '100'}]
    monkeypatch.setattr(scanner, '_jquants_paginated', fetch)
    scanner._jp_dividend_warm(['1000'])
    assert calls == registered[:20]
    scanner._jp_dividend_warm(['1000'])
    assert calls == registered + ['1000']
    scanner._jp_dividend_warm(['1000'])
    assert len(calls) == 26
    path = tmp_path/'jp_market_source_history.sqlite3'
    assert history.completed_codes(path, cutoff=AT, member_codes=registered) == set(registered)
    stored = history.read(path, cutoff=AT, member_codes=['9000'])
    assert stored[0]['summary']['OP'] == '100' and 'name' not in stored[0]['summary']
    assert history.read_coverage(path, cutoff=AT) == {}  # Company fetch is not a dated 225-member proof.


def test_daily_disclosures_retain_registered_company_without_extra_fetch(monkeypatch, tmp_path):
    import scanner
    monkeypatch.setattr(scanner, '_layer2b_read_latest', lambda: {'members': [{'market': 'JP', 'symbol': '9000.T'}]})
    monkeypatch.setattr(scanner, '_cost_policy_durable_enabled', lambda: True)
    monkeypatch.setattr(scanner, '_DURABILITY_PATHS', {'root': str(tmp_path)})
    monkeypatch.setattr(scanner, '_JP_INDEX_PROXY', {'factors': {'factors': {'1000': 1}}})
    monkeypatch.setattr(scanner, '_nikkei225_constituent_changes', lambda: {'rows': []})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: AT)
    scanner._jp_earnings_history_retain([{**row(), 'Code': '90000'}], query_date='2026-10-06')
    path = tmp_path/'jp_market_source_history.sqlite3'
    assert len(history.read(path, cutoff=AT, member_codes=['9000'])) == 1
    assert not history.read_coverage(path, cutoff=AT)['2026-10-06']['complete']


def test_membership_failure_keeps_index_and_oversized_union_does_not_fetch(monkeypatch, tmp_path):
    import scanner
    from unittest.mock import Mock
    monkeypatch.setattr(scanner, '_layer2b_read_latest', Mock(side_effect=OSError('synthetic')))
    assert scanner._jp_asset_earnings_registered_codes() == set()
    monkeypatch.setattr(scanner, '_layer2b_read_latest', lambda: {'members':
        [{'market': 'JP', 'symbol': str(9000+i)} for i in range(401)]})
    monkeypatch.setattr(scanner, '_cost_policy_durable_enabled', lambda: True)
    monkeypatch.setattr(scanner, '_JP_EARNINGS_HISTORY_STATUS', {})
    fetch = Mock(); monkeypatch.setattr(scanner, '_jquants_paginated', fetch)
    scanner._jp_dividend_warm(['1000'])
    assert fetch.call_count == 0 and scanner._JP_EARNINGS_HISTORY_STATUS['status'] == 'PERSIST_FAILED'


def test_recent_dated_original_requires_fresh_complete_company_response(tmp_path):
    path = tmp_path/'shared.sqlite3'
    prior = {**row(), 'DiscDate':'2026-10-05', 'DiscNo':'previous'}
    current = row()
    history.retain(path, [prior], received_at=AT, member_codes=['1000'], query_code='1000')
    history.retain(path, [current], received_at=LATER, member_codes=['1000'], query_date='2026-10-06')
    assert history.completed_codes(path, cutoff=LATER, member_codes=['1000']) == {'1000'}
    assert history.completed_codes(path, cutoff=LATER, member_codes=['1000'],
        required_disclosure_days=['2026-10-06']) == set()
    history.retain(path, [prior,current], received_at=LATER, member_codes=['1000'], query_code='1000')
    assert history.completed_codes(path, cutoff=LATER, member_codes=['1000'],
        required_disclosure_days=['2026-10-06']) == {'1000'}


def test_recent_company_priority_uses_latest_revision_and_ignores_unrequired_dates(tmp_path):
    path = tmp_path/'shared.sqlite3'
    old = row(); corrected = {**old, 'FOP':'1100000000'}
    history.retain(path,[old],received_at=AT,member_codes=['1000'],query_date='2026-10-06')
    history.retain(path,[corrected],received_at=LATER,member_codes=['1000'],query_code='1000')
    assert history.completed_codes(path,cutoff=LATER,member_codes=['1000'],
        required_disclosure_days=['2026-10-06']) == {'1000'}
    assert history.completed_codes(path,cutoff=AT,member_codes=['1000'],
        required_disclosure_days=['2026-10-06']) == set()
    history.retain(path,[{**old,'DiscNo':'unrequired','DiscDate':'2026-10-05'}],
        received_at=LATER,member_codes=['1000'])
    assert history.completed_codes(path,cutoff=LATER,member_codes=['1000'],
        required_disclosure_days=['2026-10-06']) == {'1000'}
    for days in (['bad'], ['2026-10-06']*15, '2026-10-06'):
        with pytest.raises(ValueError):
            history.completed_codes(path,cutoff=LATER,member_codes=['1000'],required_disclosure_days=days)


def test_recent_proof_gap_uses_existing_company_lane_despite_fresh_dividend_cache(monkeypatch, tmp_path):
    import scanner
    import time
    path=tmp_path/'jp_market_source_history.sqlite3'
    prior={**row(),'DiscDate':'2026-10-05','DiscNo':'prior'}; current=row()
    history.retain(path,[prior],received_at=AT,member_codes=['1000'],query_code='1000')
    history.retain(path,[current],received_at=LATER,member_codes=['1000'],query_date='2026-10-06')
    now=time.time()
    monkeypatch.setattr(scanner,'_JP_DIVIDEND_STORE',dict(rows={},fetchedAt={'1000':now},closes=None,
        restoreAttempted=True,lastError=None,requestsLastWarm=0))
    monkeypatch.setattr(scanner,'_JP_EARNINGS_BACKFILL_ATTEMPTS',{})
    monkeypatch.setattr(scanner,'_JP_EARNINGS_HISTORY_STATUS',{})
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:True)
    monkeypatch.setattr(scanner,'_DURABILITY_PATHS',{'root':str(tmp_path)})
    monkeypatch.setattr(scanner,'_jp_asset_earnings_registered_codes',lambda:set())
    monkeypatch.setattr(scanner,'_jp_market_engine_statements_dates',lambda _:['2026-10-06'])
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:LATER)
    monkeypatch.setattr(scanner,'_JQUANTS_API_KEY','synthetic')
    monkeypatch.setattr(scanner,'_jp_dividend_persist',lambda:None)
    calls=[]
    def fetch(route,params,**bounds):
        calls.append((route,params,bounds));return [prior,current]
    monkeypatch.setattr(scanner,'_jquants_paginated',fetch)
    scanner._jp_dividend_warm(['1000'])
    assert calls==[('/fins/summary',{'code':'1000'},{'max_pages':3,'request_timeout':15})]
    assert scanner._JP_DIVIDEND_STORE['requestsLastWarm']==1
    scanner._jp_dividend_warm(['1000'])
    assert len(calls)==1
    assert history.completed_codes(path,cutoff=LATER,member_codes=['1000'],
        required_disclosure_days=['2026-10-06'])=={'1000'}


# ━━━ 2026-10-16: one verification per original, and a cheap store identity ━━━

def test_one_original_for_many_companies_is_read_once_with_the_same_checks(tmp_path, monkeypatch):
    path = tmp_path/'shared.sqlite3'
    rows = [{**row(), 'Code': str(1000+i)+'0'} for i in range(5)]
    history.retain(path, rows, received_at=AT, member_codes=[str(1000+i) for i in range(5)], query_date='2026-10-06')
    import hashlib as real_hashlib
    hashed = []
    class Counting:
        @staticmethod
        def sha256(data=b''):
            if isinstance(data, (bytes, bytearray)) and len(data) > 200:
                hashed.append(len(data))
            return real_hashlib.sha256(data)
    monkeypatch.setattr(history, 'hashlib', Counting)
    out = history.read(path, cutoff=LATER, member_codes=[str(1000+i) for i in range(5)])
    assert len(out) == 5 and len(hashed) == 1                   # the shared original, once
    # Owner decision 2026-10-16: verified once per process. A second read does
    # not fetch the original again; damage after it is found after a restart.
    hashed.clear()
    assert history.read(path, cutoff=LATER, member_codes=[str(1000+i) for i in range(5)]) == out
    assert hashed == []
    import sqlite3
    db = sqlite3.connect(path); db.execute("UPDATE raw_sources SET raw=CAST('{\"data\":[]}' AS BLOB)"); db.commit(); db.close()
    history.clear_verified_originals()                          # a restart
    with pytest.raises(ValueError, match='financial_observation_integrity'):
        history.read(path, cutoff=LATER, member_codes=['1000'])


def test_a_new_observation_is_always_checked_against_its_original(tmp_path):
    path = tmp_path/'shared.sqlite3'
    history.retain(path, [row()], received_at=AT, member_codes=['1000'], query_date='2026-10-06')
    history.read(path, cutoff=LATER, member_codes=['1000'])
    import sqlite3, json as _json
    db = sqlite3.connect(path)
    seq, body, raw_id = db.execute("SELECT seq, body, raw_id FROM observations WHERE source_id LIKE 'financial-summary:%'").fetchone()
    forged = _json.loads(body); forged['summary'] = {**forged['summary'], 'FOP': '999'}
    forged['observationId'] = __import__('hashlib').sha256(sources._json(history._compact(forged['summary'])).encode()).hexdigest()
    db.execute("INSERT INTO observations(source_id,session,raw_id,body) VALUES(?,?,?,?)",
               ('financial-summary:1000', 'x', raw_id, _json.dumps(forged)))
    db.commit(); db.close()
    with pytest.raises(ValueError, match='financial_observation_integrity'):
        history.read(path, cutoff=LATER, member_codes=['1000'])


def test_store_identity_changes_with_financial_receipts_not_with_other_sources(tmp_path):
    path = tmp_path/'shared.sqlite3'
    assert history.store_identity(path) is None
    history.retain(path, [row()], received_at=AT, member_codes=['1000'], query_date='2026-10-06')
    first = history.store_identity(path)
    db = sources.connect(path)
    with db:
        db.execute("INSERT INTO raw_sources VALUES('other','https://example.test','x','2026-10-07T00:00:00Z',X'00')")
        db.execute("INSERT INTO observations(source_id,session,raw_id,body) VALUES('vix','2026-10-07','other','{}')")
        db.execute("INSERT INTO metadata VALUES('other-source:1','{}')")
    db.close()
    assert history.store_identity(path) == first                  # unrelated writes
    history.retain(path, [{**row(), 'DiscNo': '101'}], received_at=LATER, member_codes=['1000'])
    assert history.store_identity(path) != first                  # a new financial observation


def test_interleaved_originals_are_each_read_once_and_the_order_is_kept(tmp_path, monkeypatch):
    path = tmp_path/'shared.sqlite3'
    codes = ['1000', '1001', '1002']
    day1 = [{**row(), 'Code': c + '0', 'DiscDate': '2026-10-05'} for c in codes]
    day2 = [{**row(), 'Code': c + '0', 'DiscDate': '2026-10-06', 'DiscNo': '200'} for c in reversed(codes)]
    history.retain(path, day1, received_at=AT, member_codes=codes, query_date='2026-10-05')
    history.retain(path, day2, received_at=LATER, member_codes=codes, query_date='2026-10-06')
    import hashlib as real_hashlib
    hashed = []
    class Counting:
        @staticmethod
        def sha256(data=b''):
            if isinstance(data, (bytes, bytearray)) and len(data) > 200:
                hashed.append(len(data))
            return real_hashlib.sha256(data)
    monkeypatch.setattr(history, 'hashlib', Counting)
    out = history.read(path, cutoff=LATER, member_codes=list(reversed(codes)))
    assert len(hashed) == 2                                   # two originals, once each
    assert [(r['summary']['Code'], r['summary']['DiscDate']) for r in out] == [
        (c, d) for c in codes for d in ('2026-10-05', '2026-10-06')]
    # Visibility still applies per observation.
    early = history.read(path, cutoff=AT, member_codes=codes)
    assert {r['summary']['DiscDate'] for r in early} == {'2026-10-05'}


def test_receipt_originals_are_verified_once_per_process(tmp_path, monkeypatch):
    path = tmp_path/'shared.sqlite3'
    history.retain(path, [row()], received_at=AT, member_codes=['1000'], query_code='1000')
    history.retain(path, [], received_at=AT, member_codes=['1000'], query_date='2026-10-06')
    first = (history.read_company_coverage(path, cutoff=LATER, member_codes=['1000']),
             history.read_coverage(path, cutoff=LATER))
    fetched = []
    import sqlite3
    real_connect = sqlite3.connect
    class Watching:
        def __init__(self, db): self.db = db
        def execute(self, sql, *a):
            if 'FROM raw_sources' in sql: fetched.append(sql)
            return self.db.execute(sql, *a)
        def close(self): self.db.close()
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: Watching(real_connect(*a, **k)))
    again = (history.read_company_coverage(path, cutoff=LATER, member_codes=['1000']),
             history.read_coverage(path, cutoff=LATER))
    assert again == first and fetched == []
    # The cutoff still applies to a reused receipt.
    assert history.read_company_coverage(path, cutoff='2026-10-01T00:00:00Z', member_codes=['1000']) == {}
    # A receipt edited in place still fails its own digest on every read.
    monkeypatch.setattr(sqlite3, 'connect', real_connect)
    db = real_connect(path)
    key, value = db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-code:%'").fetchone()
    import json as _json
    edited = _json.loads(value); edited['retainedRows'] = 99
    db.execute("UPDATE metadata SET value=? WHERE key=?", (_json.dumps(edited), key)); db.commit(); db.close()
    with pytest.raises(ValueError, match='financial_company_receipt_integrity'):
        history.read_company_coverage(path, cutoff=LATER, member_codes=['1000'])


# ── 2026-10-21: date receipts checked once per content ─────────────────────
# The checks are the same as before; only repeats of an identical content
# (the newest-date key and its revision) or of an identical stored text on a
# later read are not redone. The previous reader is kept here, without any
# remembered result, as the reference for results and rejections.

def _previous_read_coverage(path, *, cutoff):
    import hashlib, sqlite3
    limit = sources._time(cutoff); output = {}
    db = sqlite3.connect(path)
    try:
        for key, raw in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-date:%'"):
            row = json.loads(raw); digest = row.pop('coverageSha256', None)
            if digest is None:
                continue
            if hashlib.sha256(sources._json(row).encode()).hexdigest() != digest:
                raise ValueError('financial_coverage_integrity')
            source = db.execute('SELECT raw,sha256 FROM raw_sources WHERE id=?', (row.get('rawId'),)).fetchone()
            if not source or hashlib.sha256(source[0]).hexdigest() != source[1] or source[1] != row.get('sourceResponseSha256'):
                raise ValueError('financial_coverage_integrity')
            history.validate_composite_coverage(row, source[0])
            if sources._time(row['receivedAt']) <= limit and sources._time(row['knownAt']) <= limit:
                day = row.get('queryDate')
                if not day or key.split(':', 2)[1] != day:
                    raise ValueError('financial_coverage_integrity')
                old = output.get(day)
                if old is None or sources._time(row['knownAt']) > sources._time(old['knownAt']):
                    output[day] = {**row, 'coverageSha256': digest}
        return output
    finally:
        db.close()


COMPOSITE_AT = '2026-10-12T16:00:01+00:00'
DATE_REVISIONS = ('2026-10-07T01:00:00Z', '2026-10-07T07:00:00Z', '2026-10-08T01:00:00Z')


def _receipt_store(tmp_path):
    """A company receipt, one date queried three times (one original, three
    revisions) and one 225-company component set, as production keeps them."""
    import argus_earnings_scope as scope
    from test_argus_earnings_scope import fixture, bind, add_row
    path = tmp_path/'shared.sqlite3'
    history.retain(path, [row()], received_at=AT, member_codes=['1000'], query_code='1000')
    members = [str(n) for n in range(1000, 1225)]
    for index, at in enumerate(DATE_REVISIONS):
        # Each revision a different response (owner decision 2026-10-22: the
        # same response received again is not another revision).
        history.retain(path, [{**row(), 'FOP': str(100 + index)}], received_at=at, member_codes=members,
                       query_date='2026-10-06', complete_scope=members)
    inputs = fixture(); add_row(inputs); bind(inputs)
    proof, rows = scope.admit(**inputs)
    history.retain_composite(path, rows, receipt_proof=proof)
    return path


def _date_raws(path):
    import sqlite3
    db = sqlite3.connect(path)
    try:
        return {raw_id: bytes(raw) for raw_id, raw in db.execute(
            "SELECT id,raw FROM raw_sources WHERE id IN (SELECT json_extract(value,'$.rawId') FROM metadata "
            "WHERE key LIKE 'financial-summary-date:%')")}
    finally:
        db.close()


def _resign(path, key, mutate):
    import sqlite3
    db = sqlite3.connect(path)
    value = json.loads(db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()[0])
    value.pop('coverageSha256'); mutate(value)
    value['coverageSha256'] = __import__('hashlib').sha256(sources._json(value).encode()).hexdigest()
    db.execute('UPDATE metadata SET value=? WHERE key=?', (sources._json(value), key)); db.commit(); db.close()


def test_date_receipts_are_checked_once_per_content_with_unchanged_results(tmp_path, monkeypatch):
    import hashlib as real_hashlib
    import argus_earnings_scope as scope
    path = _receipt_store(tmp_path)
    cutoffs = ('2026-10-07T03:00:00Z', '2026-10-21T00:00:00Z', '2026-10-06T00:00:00Z')
    expected = {cutoff: _previous_read_coverage(path, cutoff=cutoff) for cutoff in cutoffs}
    assert len(expected['2026-10-21T00:00:00Z']) == 2
    originals = {raw: raw_id for raw_id, raw in _date_raws(path).items()}
    hashed, composite_checks = [], []
    class Counting:
        @staticmethod
        def sha256(data=b''):
            if bytes(data) in originals:
                hashed.append(originals[bytes(data)])
            return real_hashlib.sha256(data)
    real_validate = scope.validate
    monkeypatch.setattr(history, 'hashlib', Counting)
    monkeypatch.setattr(scope, 'validate', lambda *a: composite_checks.append(1) or real_validate(*a))
    for cutoff in cutoffs:
        result = history.read_coverage(path, cutoff=cutoff)
        # Same receipts, same order of keys as before.
        assert json.dumps(result) == json.dumps(expected[cutoff])
    # The component set: its revision and its newest-date key are one
    # content, checked once (before: twice, and again on every read). The
    # date queried three times: each revision is its own content and is
    # checked against the original's bytes (before: four times, the newest
    # key repeating one revision).
    composite_raw = next(raw_id for raw_id, raw in _date_raws(path).items() if b'receipt-1' in raw)
    assert composite_checks == [1]
    assert hashed.count(composite_raw) == 1
    assert len([h for h in hashed if h != composite_raw]) == len(DATE_REVISIONS)


@pytest.mark.parametrize('warm', [False, True], ids=['fresh', 'after-verified-read'])
@pytest.mark.parametrize('case', ['edited-not-resigned', 'resigned-nested-component', 'resigned-other-original',
                                  'replaced-original-new-revision', 'broken-original-new-revision',
                                  'observation-not-in-original'])
def test_rejections_are_unchanged_by_remembered_checks(tmp_path, warm, case):
    import sqlite3, hashlib
    path = _receipt_store(tmp_path)
    late = '2026-10-21T00:00:00Z'
    if warm:   # every reader has accepted the store once in this process
        history.read(path, cutoff=late, member_codes=['1000'])
        history.read_coverage(path, cutoff=late)
        history.read_company_coverage(path, cutoff=late, member_codes=['1000'])
    db = sqlite3.connect(path)
    plain = 'financial-summary-date:2017-05-12'
    date_raw = json.loads(db.execute("SELECT value FROM metadata WHERE key='financial-summary-date:2026-10-06'").fetchone()[0])['rawId']
    db.close()
    reader = lambda: history.read_coverage(path, cutoff=late)
    if case == 'edited-not-resigned':
        db = sqlite3.connect(path)
        value = json.loads(db.execute('SELECT value FROM metadata WHERE key=?', (plain,)).fetchone()[0])
        value['retainedRows'] = 7
        db.execute('UPDATE metadata SET value=? WHERE key=?', (sources._json(value), plain)); db.commit(); db.close()
    elif case == 'resigned-nested-component':
        # The newest-date key no longer equals its revision; the revision's
        # remembered check must not cover it.
        _resign(path, plain, lambda v: v['componentReceipt']['components'][0].update(selectedRowsSha256='a'*64))
    elif case == 'resigned-other-original':
        _resign(path, plain, lambda v: v.update(rawId=date_raw))
    elif case in ('replaced-original-new-revision', 'broken-original-new-revision'):
        db = sqlite3.connect(path)
        if case == 'replaced-original-new-revision':
            other = sources._json({'data': [history._compact({**row(), 'FOP': '1'})]}).encode()
            db.execute('UPDATE raw_sources SET raw=?, sha256=? WHERE id=?', (other, hashlib.sha256(other).hexdigest(), date_raw))
        else:
            broken = bytes(db.execute('SELECT raw FROM raw_sources WHERE id=?', (date_raw,)).fetchone()[0]) + b' '
            db.execute('UPDATE raw_sources SET raw=? WHERE id=?', (broken, date_raw))
        db.commit(); db.close()
        # A new collection of the same date names the same original: the new
        # receipt is checked against the stored bytes, as before.
        members = [str(n) for n in range(1000, 1225)]
        history.retain(path, [{**row(), 'FOP': str(100 + len(DATE_REVISIONS) - 1)}],
                       received_at='2026-10-09T01:00:00Z', member_codes=members,
                       query_date='2026-10-06', complete_scope=members)
    elif case == 'observation-not-in-original':
        db = sqlite3.connect(path)
        summary = history._compact({**row(), 'DiscNo': 'absent', 'FOP': '5'})
        raw_id, digest = db.execute("SELECT id,sha256 FROM raw_sources WHERE url=? LIMIT 1", (history.URL,)).fetchone()
        received = db.execute('SELECT received_at FROM raw_sources WHERE id=?', (raw_id,)).fetchone()[0]
        identity = hashlib.sha256(sources._json(summary).encode()).hexdigest()
        body = {'summary': summary, 'receivedAt': received, 'knownAt': received,
                'publishedAt': history._published(summary).isoformat(), 'historicalVintageVerified': False,
                'sourceRef': history.URL, 'sourceResponseSha256': digest, 'rawId': raw_id, 'observationId': identity}
        db.execute('INSERT INTO observations(source_id,session,raw_id,body) VALUES(?,?,?,?)',
                   ('financial-summary:1000', identity, raw_id, sources._json(body)))
        db.commit(); db.close()
        reader = lambda: history.read(path, cutoff=late, member_codes=['1000'])
    if case != 'observation-not-in-original':
        with pytest.raises(ValueError):              # the previous reader rejects it too
            _previous_read_coverage(path, cutoff=late)
    with pytest.raises(ValueError):
        reader()
    history.clear_verified_originals()                          # a restart
    with pytest.raises(ValueError):
        reader()


def test_private_snapshot_reuses_only_identical_checked_content(tmp_path):
    import argus_market_input_backup as backup
    path = _receipt_store(tmp_path)
    fresh = tmp_path/'fresh'; fresh.mkdir()
    before = backup.snapshot(path, fresh)
    history.clear_verified_originals()
    history.read_coverage(path, cutoff='2026-10-21T00:00:00Z')    # remembers each content
    warm = tmp_path/'warm'; warm.mkdir()
    assert backup.snapshot(path, warm) == before                  # same archive, byte for byte
    # A changed content is checked in the snapshot even when its date's
    # other receipts were remembered.
    _resign(path, 'financial-summary-date:2017-05-12',
            lambda v: v['componentReceipt']['components'][0].update(selectedRowsSha256='a'*64))
    again = tmp_path/'again'; again.mkdir()
    with pytest.raises(ValueError, match='COMPOSITE_HASH|COMPONENT_SELECTED_INPUT'):
        backup.snapshot(path, again)


def test_the_same_response_received_again_is_not_another_revision(tmp_path):
    # Owner decision 2026-10-22: 「同じ中身を受け取り直した分は残さない。重複を避ける」.
    import sqlite3
    path = tmp_path/'shared.sqlite3'
    members = [str(n) for n in range(1000, 1225)]
    for at in DATE_REVISIONS:
        history.retain(path, [row()], received_at=at, member_codes=members, query_date='2026-10-06',
                       complete_scope=members)
        history.retain(path, [row()], received_at=at, member_codes=['1000'], query_code='1000')
    history.retain(path, [{**row(), 'FOP': '9'}], received_at='2026-10-09T01:00:00Z', member_codes=members,
                   query_date='2026-10-06', complete_scope=members)
    db = sqlite3.connect(path)
    try:
        dates = db.execute("SELECT count(*) FROM metadata WHERE key LIKE 'financial-summary-date:2026-10-06:revision:%'").fetchone()[0]
        codes = db.execute("SELECT count(*) FROM metadata WHERE key LIKE 'financial-summary-code:1000:revision:%'").fetchone()[0]
        newest = json.loads(db.execute("SELECT value FROM metadata WHERE key='financial-summary-date:2026-10-06'").fetchone()[0])
    finally:
        db.close()
    assert dates == 2 and codes == 1            # the first receipt, then the changed response
    assert newest['receivedAt'] == '2026-10-09T01:00:00Z'
    coverage = history.read_coverage(path, cutoff='2026-10-08T00:00:00Z')['2026-10-06']
    assert coverage['receivedAt'] == DATE_REVISIONS[0]   # the first receipt is the proof kept

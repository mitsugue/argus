from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json

import argus_market_ledger as ledger
import argus_jp_fiscal_sources as sources
import argus_jp_fiscal_runtime as runtime

AT='2026-09-16T07:00:00Z'


def calendar():
    start=date(2026,9,1)
    return [{'Date':(start+timedelta(days=i)).isoformat(),
        'HolDiv':'0' if (start+timedelta(days=i)).weekday()>=5 else '1'} for i in range(30)]


class Reply:
    status_code=200
    headers={'ETag':'"edition-a"'}
    def __init__(self,content):self.content=content
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):yield self.content


def fixture(monkeypatch):
    table=deepcopy(sources.reviewed_table()); pdf=b'%PDF-fixture-annual-table'
    table['sourceSha256']=hashlib.sha256(pdf).hexdigest()
    monkeypatch.setattr(sources,'reviewed_table',lambda:deepcopy(table))
    csv=('国債金利情報\n基準日,10年,20年,30年,40年\n'+'\n'.join(
        f'R8.9.{day},{1+i/10:.3f},{2+i/10:.3f},{3+i/10:.3f},{4+i/10:.3f}'
        for i,day in enumerate((8,9,10,11,14,15)))).encode('cp932')
    bodies={runtime.CAO_INDEX:('<a href="'+table['sourceUrl']+'">資料</a>').encode(),
        table['sourceUrl']:pdf,sources.JGB_URL:csv}
    calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs)); assert kwargs['allow_redirects'] is False
        return Reply(bodies[url])
    return get,calls,bodies,table


def test_official_publication_clock_uses_following_business_day():
    assert runtime.expected_session(calendar(),'2026-09-16T00:29:00Z')=='2026-09-14'
    assert runtime.expected_session(calendar(),'2026-09-16T00:30:00Z')=='2026-09-15'
    assert runtime.expected_session(calendar(),'2026-09-20T07:00:00Z')=='2026-09-17'
    holidays=calendar()
    next(r for r in holidays if r['Date']=='2026-09-16')['HolDiv']='0'
    assert runtime.expected_session(holidays,AT)=='2026-09-14'


def test_real_ledger_registry_roundtrip_daily_reuse_and_revision_gate(monkeypatch):
    get,calls,bodies,table=fixture(monkeypatch)
    original=ledger.empty_state(); legacy_hash=ledger.state_hash(original)
    initial=runtime.refresh(original,now_iso=AT,calendar=calendar(),get=get)
    assert initial['status']=='AVAILABLE' and initial['requests']==len(calls)==3
    assert 'fiscalMonitor' not in original and ledger.state_hash(original)==legacy_hash
    saved=ledger.normalize_state(json.loads(json.dumps(initial['state'])))
    monitor=saved['fiscalMonitor']
    assert monitor['reportStatus']=='AVAILABLE'
    assert monitor['report']['cases']['baseline']['fiscal']['values']['spreadPoints']==1.8
    assert ledger.state_hash(saved)!=legacy_hash
    assert ledger.effective_observations(saved,AT)==[]
    repeat=runtime.refresh(saved,now_iso='2026-09-16T08:00:00Z',calendar=calendar(),get=get)
    assert repeat['status']=='NOT_DUE' and repeat['requests']==0 and len(calls)==3
    # Same document URL with changed bytes is a revision, not a trusted new table.
    bodies[table['sourceUrl']]=b'%PDF-unreviewed-change'
    revised=runtime.refresh(saved,now_iso='2026-09-17T07:01:00Z',calendar=calendar(),get=get)
    m=revised['state']['fiscalMonitor']
    assert m['fiscalAcquisitionStatus']=='UNREVIEWED_SOURCE_REVISION'
    assert revised['state']['observations']==saved['observations']
    assert all(v['previousWarningRetained'] and v['notificationCandidate'] is None for v in m['report']['cases'].values())
    restored=ledger.merge_restored_state(saved,revised['state'])
    assert restored['fiscalMonitor']==m


def test_new_publication_becomes_due_before_24_hours(monkeypatch):
    get,calls,_,_=fixture(monkeypatch)
    first=runtime.refresh(ledger.empty_state(),now_iso='2026-09-16T00:20:00Z',calendar=calendar(),get=get)
    later=runtime.refresh(first['state'],now_iso='2026-09-16T00:40:00Z',calendar=calendar(),get=get)
    assert later['changed'] and later['state']['fiscalMonitor']['expectedMarketSession']=='2026-09-15'


def test_failure_preserves_observations_warning_and_retry_backoff(monkeypatch):
    get,_,_,_=fixture(monkeypatch)
    first=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)
    def fail(*args,**kwargs):raise TimeoutError('fixture_timeout')
    failed=runtime.refresh(first['state'],now_iso='2026-09-17T07:00:01Z',calendar=calendar(),get=fail)
    m=failed['state']['fiscalMonitor']
    assert failed['status']=='INCOMPLETE' and m['marketAcquisitionStatus']=='FAILED'
    assert failed['state']['observations']==first['state']['observations']
    assert all(v['previousWarningRetained'] for v in m['report']['cases'].values())
    assert runtime.refresh(failed['state'],now_iso='2026-09-17T07:30:00Z',calendar=calendar(),get=fail)['requests']==0


def test_unknown_calendar_retains_prior_report_without_current_acceptance(monkeypatch):
    get,_,_,_=fixture(monkeypatch)
    first=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)
    missing=runtime.refresh(first['state'],now_iso='2026-09-17T07:00:01Z',calendar=[],get=get)
    assert missing['state']['fiscalMonitor']['reportStatus']=='CALENDAR_UNAVAILABLE'
    assert missing['state']['fiscalMonitor']['report']==first['state']['fiscalMonitor']['report']


def test_public_and_llm_projection_use_saved_numbers_and_same_evidence(monkeypatch):
    get,_,_,_=fixture(monkeypatch)
    result=runtime.refresh(ledger.empty_state(),now_iso=AT,calendar=calendar(),get=get)
    state=result['state']; before=deepcopy(state)
    public=runtime.public_document(state)
    facts=runtime.explanation_facts(public)
    assert len(facts)==4 and public['selectedCase'] is None
    assert '見通し' in facts[0]['text'] and '-3.09' in facts[0]['text']
    assert all(f['verification']=='UNCONFIRMED' for f in facts)
    assert public['automaticAiCalls']==public['fetchesDuringRead']==0
    assert public['notificationDelivery']=='NOT_CONNECTED'
    assert state==before
    assert runtime.explanation_facts(runtime.public_document(ledger.empty_state()))==[]

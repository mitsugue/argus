"""Contract tests: source authority, receipts/revisions, failures, costs, backup."""
from copy import deepcopy
import json
import sqlite3
from hashlib import sha256
import pytest
import argus_credit_conditions as credit
import jp_market_acquisition as store
import argus_market_input_backup as backup
from test_argus_market_input_backup import Remote

AT='2026-10-08T01:00:00+00:00'
LATER='2026-10-09T01:00:00+00:00'

def api(group='cost', change=0):
    meta=credit.GROUPS[group];periods=['202601','202602'] if group=='stance' else ['202607','202608']
    return store._json({'STATUS':200,'NEXTPOSITION':None,'RESULTSET':[{'SERIES_CODE':code,
        'NAME_OF_TIME_SERIES':'公式の系列','UNIT':fields[1],'FREQUENCY':meta['frequency'],'LAST_UPDATE':'20261005',
        'VALUES':{'SURVEY_DATES':periods,'VALUES':[1,2+change]}} for code,fields in meta['metrics'].items()]}).encode()

def retained(tmp_path,group='cost',change=0,at=AT,path=None):
    path=path or tmp_path/'source.sqlite3';db=store.connect(path);raw=api(group,change);url=credit.api_url(group,AT)
    try:credit.retain(db,raw,url=url,rows=credit.parse_api(raw,group=group,source_url=url,received_at=at),received_at=at)
    finally:db.close()
    return path

def test_receipt_not_provider_update_or_observation_and_revisions_coexist(tmp_path):
    path=retained(tmp_path);first=credit.read(path,cutoff=AT)
    assert credit.read(path,cutoff='2026-10-07T01:00:00Z')['evidence']==[]
    assert all(r['publicationAt'] is None and r['knownAt']==AT and r['dataAsOf']<AT[:10] for r in first['evidence'])
    retained(tmp_path,change=1,at=LATER,path=path)
    assert credit.read(path,cutoff=AT)['snapshotId']==first['snapshotId']
    latest=credit.read(path,cutoff=LATER)
    revised=[r for r in latest['evidence'] if r['revision']]
    assert len(revised)==2 and all(r['supersedes'] for r in revised)
    db=sqlite3.connect(path);assert db.execute('SELECT count(*) FROM observations').fetchone()[0]==6
    db.close()

@pytest.mark.parametrize('mutation',[
    lambda p:p.update(STATUS=400), lambda p:p.update(NEXTPOSITION=3),lambda p:p.update(OwnerRecord='forbidden'),
    lambda p:p['RESULTSET'][0].update(UNIT='yen'),lambda p:p['RESULTSET'][0]['VALUES']['VALUES'].__setitem__(0,True),
    lambda p:p['RESULTSET'][0]['VALUES']['VALUES'].__setitem__(0,float('inf')),
    lambda p:p['RESULTSET'][0]['VALUES']['SURVEY_DATES'].__setitem__(0,'202608'),
    lambda p:p['RESULTSET'][0].update(SERIES_CODE='invented'),
])
def test_official_structure_rejects_wrong_or_ambiguous_numbers(mutation):
    payload=json.loads(api());mutation(payload)
    with pytest.raises((ValueError,TypeError)):credit.parse_api(json.dumps(payload).encode(),group='cost',source_url=credit.api_url('cost',AT),received_at=AT)

def test_quarter_dates_and_unchanged_receipt_do_not_create_revisions(tmp_path):
    path=retained(tmp_path,group='stance');doc=credit.read(path,cutoff=AT)
    assert doc['dimensions']['lendingStance']['direction']=='EASING'
    retained(tmp_path,group='stance',at=LATER,path=path)
    assert len(credit.read(path,cutoff=LATER)['evidence'])==6
    assert 'endDate=202604' in credit.api_url('stance',AT)

def test_missing_period_not_zero_or_consecutive_comparison(tmp_path):
    path=tmp_path/'source.sqlite3';db=store.connect(path);raw=json.loads(api())
    for series in raw['RESULTSET']:series['VALUES']['VALUES'][0]=None
    raw=json.dumps(raw).encode();url=credit.api_url('cost',AT)
    credit.retain(db,raw,url=url,rows=credit.parse_api(raw,group='cost',source_url=url,received_at=AT),received_at=AT)
    assert credit.document(db,cutoff=AT)['dimensions']['borrowingCost']['status']=='INSUFFICIENT_DATA'
    db.close()

def test_stale_saved_cache_and_research_never_become_live_forecasts(tmp_path):
    doc=credit.read(retained(tmp_path),cutoff=AT)
    aged=credit.current_projection(doc,cutoff='2027-10-08T01:00:00Z')
    assert aged['dimensions']['borrowingCost']['status']=='INSUFFICIENT_DATA'
    assert aged['sourceHealth'][0]['status']=='STALE'
    assert aged['futureMapResearch']['liveForecastChanged'] is False and doc['futureMapResearch']['validation']=='UNVALIDATED'
    assert aged['automaticAiCalls']==0 and aged['actionAuthority'] is False

def test_bank_and_nonbank_conditional_impacts_share_verified_refs(tmp_path):
    doc=credit.read(retained(tmp_path),cutoff=AT)
    for sector in ('7050','8050'):
        impact=credit.asset_impact(doc,sector_code=sector)
        assert impact['evidenceIds'] and impact['sources'] and impact['kind']=='ARGUS_HYPOTHESIS' and impact['actionAuthority'] is False
    assert credit.asset_impact(doc,sector_code='unknown') is None
    assert len(credit.context_reference(doc)['evidence'])<=12

def test_pdf_unknown_revision_cannot_inherit_review_or_fabricate_numbers(tmp_path):
    raw=b'%PDF-1.7\nchanged official document\n%%EOF'
    url=next(iter(credit.REVIEWED.values()))['sourceUrl']
    row=credit.document_row(raw,url=url,received_at=AT,source_id='fsa_notes')
    assert row['validationStatus']=='UNVERIFIED' and row['value'] is None and row['statementJa'] is None
    with pytest.raises(ValueError):credit.document_row(raw,url=url,received_at=AT,source_id='boj_fsr')

def test_failure_is_bounded_and_screen_read_uses_only_saved_values(tmp_path):
    path=retained(tmp_path);calls=[]
    def failed(url,**kw):calls.append(url);raise TimeoutError('do not retain exception text')
    doc=credit.refresh(path,now_iso=LATER,get=failed,clock=lambda:LATER)
    assert len(calls)==6 and doc['collectionReceipt']['automaticAiCalls']==0
    assert doc['sourceHealth'][0]['lastFetchStatus']=='FAILED' and doc['dimensions']['borrowingCost']['value']==2
    assert 'do not retain' not in json.dumps(doc)
    later=credit.refresh(path,now_iso=LATER,get=failed,clock=lambda:LATER)
    assert later['collectionReceipt']['requests']==0 and len(calls)==6
    assert credit.read(path,cutoff=LATER)['snapshotId']==doc['snapshotId']

def test_private_backup_restores_all_credit_revisions_without_owner_fields(tmp_path):
    path=retained(tmp_path);retained(tmp_path,change=1,at=LATER,path=path)
    remote=Remote();result=backup.synchronize(path,remote)
    assert result['status']=='VERIFIED' and result['counts']['creditConditions']==2
    manifest=json.loads(remote.files[backup.PREFIX+'/manifests/'+result['manifestSha256']+'.json'])
    content=b''.join(remote.files[backup.PREFIX+'/chunks/'+r['sha256']+'.bin'] for r in manifest['chunks'])
    entries=[json.loads(r) for r in content.splitlines()];restored=tmp_path/'restored.sqlite3';db=store.connect(restored)
    import base64
    for row in entries:
        if row.get('kind')=='raw':db.execute('INSERT INTO raw_sources VALUES(?,?,?,?,?)',(row['id'],row['url'],row['sha256'],row['receivedAt'],base64.b64decode(row['dataBase64'])))
        if row.get('kind')=='observation':db.execute('INSERT INTO observations(source_id,session,raw_id,body) VALUES(?,?,?,?)',(row['sourceId'],row['session'],row['rawId'],store._json(row['body'])))
    db.commit();db.close()
    assert credit.read(restored,cutoff=AT)['evidence']==credit.read(path,cutoff=AT)['evidence']
    assert credit.read(restored,cutoff=LATER)['snapshotId']==credit.read(path,cutoff=LATER)['snapshotId']
    writes=remote.writes;assert backup.synchronize(path,remote)==result and remote.writes==writes

def test_live_routes_read_saved_projection_without_external_acquisition(monkeypatch,tmp_path):
    import scanner
    doc=credit.read(retained(tmp_path),cutoff=AT)
    monkeypatch.setattr(scanner,'_CREDIT_CONDITIONS_CACHE',{'document':doc,'restoreAttempted':True,'status':'SAVED','errorClass':None})
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:AT)
    def forbidden(*args,**kwargs):raise AssertionError('screen cannot collect')
    monkeypatch.setattr(credit,'refresh',forbidden)
    monkeypatch.setattr(scanner.requests,'get',forbidden)
    monkeypatch.setattr(scanner,'_INTEL_STORE',[])
    monkeypatch.setattr(scanner,'_news_ja_restore_once',lambda:None)
    monkeypatch.setattr(scanner,'_JQ_MASTER_CACHE',{'data':[{'code4':'1001','sector33Code':'7050','effectiveDate':'2026-10-08','receivedAt':AT},
        {'code4':'1002','sector33Code':'8050','effectiveDate':'2026-10-08','receivedAt':AT}]})
    client=scanner.app.test_client()
    for _ in range(2):assert client.get('/api/argus/credit-conditions').get_json()['snapshotId']==doc['snapshotId']
    for symbol in ('1001','1002'):
        body=client.get('/api/argus/events/'+symbol+'/institutional-intelligence').get_json()
        assert body['creditImpact']['sources'] and body['creditImpact']['actionAuthority'] is False
    assert client.get('/api/argus/events/UNCLASSIFIED/institutional-intelligence').get_json()['creditImpact'] is None


def test_brief_numbers_remain_verified_and_context_is_small(tmp_path):
    import argus_market_brief as brief
    doc=credit.read(retained(tmp_path),cutoff=AT)
    facts=credit.explanation_facts(doc)
    context=brief.unified_context({'facts':facts,'creditConditions':credit.context_reference(doc)})
    assert all(f['verification']=='VERIFIED' for f in context['facts'])
    assert context['creditConditions']['snapshotId']==doc['snapshotId']
    assert 'evidence' not in context['creditConditions'] and 'sourceHealth' not in context['creditConditions']


def npl_xlsx(*, ratio=1.0, label="全国銀行", formula=False):
    from io import BytesIO
    import zipfile
    from xml.sax.saxutils import escape
    stream=BytesIO();ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    texts=[label,'総与信(億円)','金融再生法開示債権（億円）','不良債権比率(％)','2025年3月期','2025年9月期']
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}"><sheets><sheet name="表"/></sheets></workbook>')
        z.writestr('xl/sharedStrings.xml',f'<sst xmlns="{ns}">'+''.join(f'<si><t>{escape(t)}</t><rPh><t>IGNORED_PHONETIC</t></rPh></si>' for t in texts)+'</sst>')
        labels={'A79':0,'C79':1,'C80':2,'C85':3,'V3':4,'W3':5}
        cells=''.join(f'<c r="{r}" t="s"><v>{v}</v></c>' for r,v in labels.items())
        values={'V79':10000,'V80':110,'V85':1.1,'W79':10000,'W80':100,'W85':ratio}
        cells+=''.join(f'<c r="{r}">'+('<f>UNREVIEWED()</f>' if formula and r=='W85' else '')+f'<v>{v}</v></c>' for r,v in values.items())
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{ns}"><sheetData>{cells}</sheetData></worksheet>')
    return stream.getvalue()

NPL_URL='https://www.fsa.go.jp/status/npl/20260227/01.xlsx'

def test_npl_point_ratio_reconciles_and_stale_quality_is_not_current(tmp_path):
    raw=npl_xlsx();rows=credit.parse_npl(raw,source_url=NPL_URL,received_at=AT)
    assert len(rows)==6 and rows[-1]['dataAsOf']=='2025-09-30' and rows[-1]['publicationDate']=='2026-02-27'
    assert rows[-1]['value']==1.0 and rows[-1]['historicalVintageVerified'] is False
    path=tmp_path/'npl.sqlite3';db=store.connect(path)
    credit.retain(db,raw,url=NPL_URL,rows=rows,received_at=AT);doc=credit.document(db,cutoff=AT);db.close()
    q=doc['dimensions']['creditQuality']
    assert q['status']=='INSUFFICIENT_DATA' and q['reason']=='STALE' and q['direction']=='IMPROVING' and q['evidenceIds']
    assert credit.read(path,cutoff='2026-02-28T00:00:00Z')['evidence']==[]
    assert backup.synchronize(path,Remote())['status']=='VERIFIED'
    assert all('古い観測' in f['text'] for f in credit.explanation_facts(doc))

@pytest.mark.parametrize('kw',[{'ratio':4.0},{'ratio':float('nan')},{'label':'別の集計'},{'formula':True}])
def test_npl_ambiguous_layout_units_formula_or_ratio_fail_closed(kw):
    with pytest.raises(ValueError):credit.parse_npl(npl_xlsx(**kw),source_url=NPL_URL,received_at=AT)

def test_stale_projection_has_new_identity_and_cannot_drive_asset_impact(tmp_path):
    doc=credit.read(retained(tmp_path),cutoff=AT)
    aged=credit.current_projection(doc,cutoff='2027-10-08T01:00:00Z')
    assert aged['snapshotId']!=doc['snapshotId'] and aged['futureMapResearch']['snapshotId']==aged['snapshotId']
    assert credit.asset_impact(aged,sector_code='7050') is None


def test_source_url_cannot_hide_extra_fields_or_repeated_parameters():
    url=credit.api_url('cost',AT)
    assert credit.approved_url(url)
    assert not credit.approved_url(url+'&startDate=202501')
    assert not credit.approved_url(url+'&ownerRecord=not-allowed')
    assert not credit.approved_url(url+'&endDate='+('1'*2100))


def test_check_clock_alone_reuses_ai_but_changed_credit_input_does_not(monkeypatch,tmp_path):
    import scanner
    monkeypatch.setattr(scanner,'_backend_exact_sha',lambda:'1'*40)
    doc=credit.context_reference(credit.read(retained(tmp_path),cutoff=AT))
    brief={'generatedAt':AT,'facts':credit.explanation_facts(credit.read(retained(tmp_path),cutoff=AT)),'creditConditions':doc}
    before=scanner._market_brief_generation_input_digest(brief,{})
    assert before
    changed=deepcopy(brief);changed['generatedAt']=LATER
    changed['creditConditions']['futureMapResearch']['knowledgeCutoff']=LATER
    for h in changed['creditConditions']['sourceHealth']:
        h.update(lastAttemptAt=LATER,lastSuccessAt=LATER,lastSuccessfulParseAt=LATER,nextCheckAt=LATER)
    assert scanner._market_brief_generation_input_digest(changed,{})==before
    assert brief['creditConditions']['futureMapResearch']['knowledgeCutoff']==AT
    changed['creditConditions']['dimensions']['borrowingCost']['value']=3
    assert scanner._market_brief_generation_input_digest(changed,{})!=before

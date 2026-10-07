"""Official credit evidence in the existing source store. No trading/LLM authority.

API LAST_UPDATE is metadata, never an invented publication/knowledge timestamp.
Documents retain their originals; unreviewed PDF numbers stay UNVERIFIED.
"""
from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sqlite3
from io import BytesIO
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import jp_market_acquisition as store
from argus_jp_fiscal_runtime import _read

VERSION = 'credit-conditions-v1'
KEY = 'credit-conditions-control-v1'
API = 'https://www.stat-search.boj.or.jp/api/v1/getDataCode'
FSA_INDEX = 'https://www.fsa.go.jp/common/about/kaikaku/fsaanalyticalnotes/index.html'
FSR_INDEX = 'https://www.boj.or.jp/research/brp/fsr/'
NPL_INDEX = 'https://www.fsa.go.jp/status/npl/index.html'
MAX_BYTES = 8_000_000
ACCESS_STATUSES = {'NOT_PUBLIC', 'ANNOUNCED', 'ACCESS_RULES_PUBLISHED',
    'RESEARCH_ACCESS_ONLY', 'DOWNLOAD_AVAILABLE', 'API_AVAILABLE',
    'LICENSE_RESTRICTED', 'ARGUS_ELIGIBLE', 'ARGUS_NOT_ELIGIBLE'}
GROUPS = {
    'cost': {'db':'IR04', 'frequency':'MONTHLY', 'staleDays':100,
        'metrics':{'DLLR2CIDBNL1':('new_loan_rate','Percent per annum','PERCENT','DOMESTIC_BANKS'),
                   'DLLR2CIDBST2':('stock_short_loan_rate','Percent per annum','PERCENT','DOMESTIC_BANKS')},
        'definition':'https://www.boj.or.jp/statistics/outline/exp/exyaku.htm'},
    'growth': {'db':'MD13', 'frequency':'MONTHLY', 'staleDays':70,
        'metrics':{'FAAPOBAL1':('loan_balance','100 million yen','100_MILLION_JPY','MAJOR_AND_REGIONAL_BANKS'),
                   'FAAPOBAL1@':('loan_growth_yoy','%','PERCENT','MAJOR_AND_REGIONAL_BANKS')},
        'definition':'https://www.boj.or.jp/statistics/outline/exp/exkasi.htm'},
    'stance': {'db':'CO', 'frequency':'QUARTERLY', 'staleDays':140,
        'metrics':{'TK99F0000612GCQ01000':('lending_attitude_large','% points','DI_POINTS','LARGE_ENTERPRISES'),
                   'TK99F0000612GCQ02000':('lending_attitude_medium','% points','DI_POINTS','MEDIUM_ENTERPRISES'),
                   'TK99F0000612GCQ03000':('lending_attitude_small','% points','DI_POINTS','SMALL_ENTERPRISES')},
        'definition':'https://www.stat-search.boj.or.jp/info/nme_Mdframe.html'},
}
# Short, reviewed paraphrases only; no table or full report redistribution.
# A new hash cannot inherit this review. PDFs not in this map remain unverified.
REVIEWED = {
    'b69f3fea957a003fdcb14297409d65959f9f11d5484fe4ae59a578d342d61c55': {
        'sourceUrl':'https://www.fsa.go.jp/common/about/kaikaku/fsaanalyticalnotes/20260731/01.pdf',
        'publicationDate':'2026-07-31', 'publicationAt':None, 'dataAsOf':'2025-03-31',
        'title':'FSA Analytical Notes 2026年7月 vol.2', 'publisher':'金融庁',
        'statementJa':'貸出金利と企業の信用リスクの関係を分析した試行研究です。個社の貸出明細や確定した予測モデルが公開されたものではありません。',
        'tablePageFigureRef':'PDF page 13・企業デフォルト率推計モデルの要旨'},
    '61cf6042c553e530c426ffaee66c5eec809ddd897472271832f639d171f79e72': {
        'sourceUrl':'https://www.boj.or.jp/research/brp/fsr/data/fsr260421a.pdf',
        'publicationDate':'2026-04-21', 'publicationAt':'2026-04-21T15:00:00+09:00',
        'dataAsOf':'2026-03-31', 'title':'金融システムレポート2026年4月号', 'publisher':'日本銀行',
        'statementJa':'銀行の収益と信用リスクを、貸出金利・借り手の財務・市場環境の両面から点検する資料です。金利上昇だけで銀行株の有利不利は決まりません。',
        'tablePageFigureRef':'PDF page 2・情報の基準日、page 25・貸出動向'},
}


def digest(value):
    return sha256(store._json(value).encode()).hexdigest()


def registry():
    return [*({'sourceId':'boj_credit_'+group, 'publisher':'日本銀行',
        'sourceUrl':API, 'cadence':meta['frequency'], 'accessStatus':'API_AVAILABLE',
        'eligibilityStatus':'ARGUS_ELIGIBLE', 'rights':'INTERNAL_ANALYSIS_SOURCE_ATTRIBUTION',
        'definitionUrl':meta['definition']} for group,meta in GROUPS.items()),
        {'sourceId':'fsa_notes','publisher':'金融庁','sourceUrl':FSA_INDEX,
         'cadence':'EVENT_DRIVEN','accessStatus':'DOWNLOAD_AVAILABLE',
         'eligibilityStatus':'ARGUS_ELIGIBLE','rights':'INTERNAL_ONLY_NO_FULLTEXT_REDISTRIBUTION'},
        {'sourceId':'boj_fsr','publisher':'日本銀行','sourceUrl':FSR_INDEX,
         'cadence':'SEMIANNUAL','accessStatus':'DOWNLOAD_AVAILABLE',
         'eligibilityStatus':'ARGUS_ELIGIBLE','rights':'COMMERCIAL_REPRODUCTION_CONSULTATION_REQUIRED'},
        {'sourceId':'fsa_npl','publisher':'金融庁','sourceUrl':NPL_INDEX,
         'cadence':'SEMIANNUAL','accessStatus':'DOWNLOAD_AVAILABLE',
         'eligibilityStatus':'ARGUS_ELIGIBLE','rights':'INTERNAL_ANALYSIS_SOURCE_ATTRIBUTION'},
        {'sourceId':'joint_data_platform','publisher':'金融庁・日本銀行',
         'sourceUrl':'https://www.fsa.go.jp/news/r7/sonota/20250801/20250801.html',
         'cadence':'EVENT_DRIVEN','accessStatus':'NOT_PUBLIC','announcementStatus':'ANNOUNCED',
         'eligibilityStatus':'ARGUS_NOT_ELIGIBLE','manualDependency':'OFFICIAL_ACCESS_RULES_AND_ELIGIBILITY',
         'noteJa':'当局のデータ収集開始の公表であり、ARGUS向け明細APIは確認できていません。'}]


def api_url(group, now_iso):
    now=store._time(now_iso);meta=GROUPS[group]
    # Quarter request dates use YYYYQQ, not calendar month 10.
    end=now.year*100+((now.month-1)//3+1 if group=='stance' else now.month)
    start=(now.year-2)*100+(end%100)
    return API+'?'+urlencode({'format':'json','lang':'en','db':meta['db'],
        'code':','.join(meta['metrics']), 'startDate':start,'endDate':end})


def approved_url(url):
    if not isinstance(url,str) or len(url)>2048:return False
    parsed=urlparse(url)
    if parsed.username or parsed.password or parsed.fragment or parsed.scheme!='https':return False
    if parsed.netloc=='www.stat-search.boj.or.jp' and parsed.path=='/api/v1/getDataCode':
        q=parse_qs(parsed.query)
        return (set(q)=={'format','lang','db','code','startDate','endDate'} and all(len(v)==1 for v in q.values()) and
            q['format']==['json'] and q['lang']==['en'] and
            any(q['db']==[m['db']] and q['code']==[','.join(m['metrics'])] for m in GROUPS.values()) and
            all(re.fullmatch(r'\d{6}',q[k][0]) for k in ('startDate','endDate')))
    return (not parsed.query and ((parsed.netloc=='www.fsa.go.jp' and
        (re.fullmatch(r'/common/about/kaikaku/fsaanalyticalnotes/\d{8}/(?:\d{8}\.html|0[1-4]\.pdf)',parsed.path) or
         re.fullmatch(r'/status/npl/(?:\d{8}\.html|\d{8}/01\.xlsx)',parsed.path))) or
        (parsed.netloc=='www.boj.or.jp' and
        re.fullmatch(r'/research/brp/fsr/(?:fsr\d{6}\.htm|data/fsr\d{6}[ab]\.pdf)',parsed.path))))


def validate_original(url, raw):
    if not approved_url(url) or not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise ValueError('credit_original_scope')
    if url.endswith('.pdf'):
        if not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-2048:]:
            raise ValueError('credit_pdf_incomplete')
    elif url.endswith('.xlsx'):
        parse_npl(raw,source_url=url,received_at='9999-12-31T00:00:00Z')
    elif url.startswith(API):
        group=next(g for g in GROUPS if parse_qs(urlparse(url).query)['db']==[GROUPS[g]['db']])
        parse_api(raw,group=group,source_url=url,received_at='9999-12-31T00:00:00Z')
    elif b'<html' not in raw.lower():raise ValueError('credit_document_html')


def parse_api(raw, *, group, source_url, received_at):
    meta=GROUPS[group];receipt=store._time(received_at)
    if not approved_url(source_url) or parse_qs(urlparse(source_url).query)['db']!=[meta['db']]:
        raise ValueError('credit_series_source')
    if not isinstance(raw,bytes) or not 0<len(raw)<=256_000:raise ValueError('credit_api_bound')
    payload=json.loads(raw);items=payload.get('RESULTSET')
    if set(payload)-{'STATUS','MESSAGEID','MESSAGE','DATE','PARAMETER','NEXTPOSITION','RESULTSET'}:
        raise ValueError('credit_api_unknown_fields')
    if payload.get('STATUS')!=200 or payload.get('NEXTPOSITION') is not None or not isinstance(items,list):
        raise ValueError('credit_api_incomplete')
    if {r.get('SERIES_CODE') for r in items}!=set(meta['metrics']) or len(items)!=len(meta['metrics']):
        raise ValueError('credit_api_series')
    result=[];checksum=sha256(raw).hexdigest()
    for item in items:
        if set(item)-{'SERIES_CODE','NAME_OF_TIME_SERIES','UNIT','FREQUENCY','CATEGORY','LAST_UPDATE','VALUES'}:
            raise ValueError('credit_api_unknown_fields')
        code=item['SERIES_CODE'];metric,unit,normalized_unit,segment=meta['metrics'][code]
        if item.get('FREQUENCY')!=meta['frequency'] or item.get('UNIT')!=unit:
            raise ValueError('credit_api_definition')
        values=item.get('VALUES') or {}
        if set(values)!={'SURVEY_DATES','VALUES'}:raise ValueError('credit_api_unknown_fields')
        periods=values.get('SURVEY_DATES');numbers=values.get('VALUES')
        if not isinstance(periods,list) or not isinstance(numbers,list) or not 1<=len(periods)==len(numbers)<=28:
            raise ValueError('credit_api_history_bound')
        seen=set();previous=None
        for position,(period,value) in enumerate(zip(periods,numbers)):
            text=str(period)
            if not re.fullmatch(r'\d{6}',text):raise ValueError('credit_period')
            year,part=int(text[:4]),int(text[4:]);month=part*3 if group=='stance' else part
            if group=='stance' and not 1<=part<=4:raise ValueError('credit_quarter')
            end=date(year,month,monthrange(year,month)[1])
            if text in seen or (previous and text<=previous):raise ValueError('credit_period_order')
            seen.add(text);previous=text
            if value is None:continue
            # Tankan can publish its December survey before quarter end. The
            # API quarter is a period label, not an observed day or knowledge
            # timestamp. Require its survey month to have started instead.
            eligible_period=date(year,month,1) if group=='stance' else end
            if eligible_period>receipt.date():raise ValueError('credit_future_period')
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('credit_number')
            bounds=(0,10**9) if metric=='loan_balance' else (-100,100) if group=='stance' else (-30,30)
            if not bounds[0]<=value<=bounds[1]:raise ValueError('credit_value_range')
            result.append({'sourceId':'boj_credit_'+group,'sourceUrl':source_url,'publisher':'日本銀行',
                'title':item.get('NAME_OF_TIME_SERIES'),'publicationAt':None,'publicationDate':None,
                'observationPeriod':text,'dataAsOf':end.isoformat(),
                'dataAsOfBasis':'QUARTER_END_LABEL' if group=='stance' else 'MONTH_END_LABEL','retrievedAt':received_at,
                'knownAt':received_at,'metric':metric,'value':value,'unit':normalized_unit,
                'segment':segment,'geography':'JP','tablePageFigureRef':f'RESULTSET/{code}/VALUES/{position}',
                'providerLastUpdate':item.get('LAST_UPDATE'),'seriesCode':code,'definitionUrl':meta['definition'],
                'revisionStatus':'ORIGINAL_RECEIPT','extractionMethod':'DETERMINISTIC_OFFICIAL_API',
                'validationStatus':'VERIFIED','sourceHash':checksum,'historicalVintageVerified':False})
    if not result:raise ValueError('credit_api_empty')
    return result


def parse_npl(raw, *, source_url, received_at):
    """National-bank point observations only; half/full-year losses are not mixed.

    A changed workbook layout fails closed. Phonetic annotations are not labels.
    Current retrospective columns do not prove their historical receipt vintages.
    """
    if not approved_url(source_url) or not re.fullmatch(r'https://www.fsa.go.jp/status/npl/\d{8}/01.xlsx',source_url):
        raise ValueError('credit_npl_source')
    publication=date.fromisoformat(re.search(r'/npl/(\d{4})(\d{2})(\d{2})/',source_url).expand(r'\1-\2-\3'))
    if publication>store._time(received_at).date():raise ValueError('credit_npl_future_publication')
    if not isinstance(raw,bytes) or not 0<len(raw)<=1_000_000:raise ValueError('credit_npl_bound')
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        if len(archive.infolist())>40 or sum(i.file_size for i in archive.infolist())>5_000_000:
            raise ValueError('credit_npl_archive_bound')
        def xml(name):
            body=archive.read(name)
            if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():raise ValueError('credit_npl_xml')
            return ET.fromstring(body)
        sheets=xml('xl/workbook.xml').findall('s:sheets/s:sheet',ns)
        if len(sheets)!=1:raise ValueError('credit_npl_sheet')
        strings=[''.join(t.text or '' for t in si.findall('s:t',ns)+si.findall('s:r/s:t',ns))
            for si in xml('xl/sharedStrings.xml').findall('s:si',ns)]
        cells={}
        for cell in xml('xl/worksheets/sheet1.xml').findall('.//s:c',ns):
            ref=cell.get('r');value=cell.find('s:v',ns)
            if ref in cells:raise ValueError('credit_npl_duplicate_cell')
            cells[ref]=(strings[int(value.text)] if cell.get('t')=='s' and value is not None else
                float(value.text) if cell.get('t') in (None,'n') and value is not None else None,
                cell.find('s:f',ns) is not None)
    if any(cells.get(ref,(None,))[0]!=label for ref,label in
        {'A79':'全国銀行','C79':'総与信(億円)','C80':'金融再生法開示債権（億円）','C85':'不良債権比率(％)'}.items()):
        raise ValueError('credit_npl_definition')
    columns=[]
    for ref,(value,_) in cells.items():
        if not re.fullmatch(r'[A-Z]+3',str(ref)) or not isinstance(value,str):continue
        match=re.fullmatch(r'(\d{4})年([39])月期',value)
        if not match:continue
        year,month=map(int,match.groups());end=date(year,month,monthrange(year,month)[1])
        if end>publication:raise ValueError('credit_npl_future_period')
        columns.append((end,ref[:-1]))
    columns.sort()
    if not 2<=len(columns)<=20 or len({d for d,_ in columns})!=len(columns):raise ValueError('credit_npl_periods')
    result=[];checksum=sha256(raw).hexdigest()
    for end,column in columns:
        values=[]
        for row in (79,80,85):
            value,formula=cells.get(column+str(row),(None,False))
            if formula or type(value) not in (int,float) or not math.isfinite(value) or value<0:
                raise ValueError('credit_npl_number')
            values.append(value)
        total,problem,ratio=values
        if total<=0 or problem>total or not 0<=ratio<=100 or abs(problem/total*100-ratio)>0.06:
            raise ValueError('credit_npl_ratio_reconciliation')
        for row,metric,value,unit in ((79,'total_credit',total,'100_MILLION_JPY'),
            (80,'problem_exposure',problem,'100_MILLION_JPY'),(85,'npl_ratio',ratio,'PERCENT')):
            result.append({'sourceId':'fsa_npl','sourceUrl':source_url,'publisher':'金融庁',
                'title':'金融再生法開示債権・全国銀行','publicationAt':None,'publicationDate':publication.isoformat(),
                'observationPeriod':end.isoformat(),'dataAsOf':end.isoformat(),'retrievedAt':received_at,'knownAt':received_at,
                'metric':metric,'value':value,'unit':unit,'segment':'NATIONAL_BANKS','geography':'JP',
                'tablePageFigureRef':f'worksheet 1/{column}{row}・全国銀行',
                'revisionStatus':'ORIGINAL_RECEIPT','extractionMethod':'DETERMINISTIC_OFFICIAL_XLSX',
                'validationStatus':'VERIFIED','sourceHash':checksum,'historicalVintageVerified':False})
    return result


class Links(HTMLParser):
    def __init__(self,raw,base):
        super().__init__();self.urls=set();self.base=base
        self.feed(raw.decode('utf-8-sig'))
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.urls.add(urljoin(self.base,dict(attrs).get('href','')))


def document_row(raw, *, url, received_at, source_id):
    validate_original(url,raw)
    expected_id='fsa_notes' if urlparse(url).netloc=='www.fsa.go.jp' else 'boj_fsr'
    if source_id!=expected_id:raise ValueError('credit_document_source_id')
    review=REVIEWED.get(sha256(raw).hexdigest())
    if review and review['sourceUrl']!=url:raise ValueError('credit_review_url')
    pub=(review or {}).get('publicationAt')
    if pub and store._time(pub)>store._time(received_at):raise ValueError('credit_future_publication')
    return {'sourceId':source_id,'sourceUrl':url,'publisher':(review or {}).get('publisher'),
        'title':(review or {}).get('title') or '公式資料・抽出確認待ち',
        'publicationDate':(review or {}).get('publicationDate'),'publicationAt':pub,
        'observationPeriod':None,'dataAsOf':(review or {}).get('dataAsOf'),
        'retrievedAt':received_at,'knownAt':received_at,'metric':'published_analysis',
        'value':None,'unit':None,'segment':None,'geography':'JP',
        'tablePageFigureRef':(review or {}).get('tablePageFigureRef'),
        'statementJa':(review or {}).get('statementJa'), 'sourceHash':sha256(raw).hexdigest(),
        'revisionStatus':'ORIGINAL_RECEIPT','extractionMethod':'REVIEWED_PARAPHRASE_HASH_BOUND' if review else 'RAW_ONLY',
        'validationStatus':'VERIFIED_STATEMENT' if review else 'UNVERIFIED',
        'historicalVintageVerified':False,'manualVerificationRequired':not bool(review)}


def retain(db, raw, *, url, rows, received_at):
    validate_original(url,raw);store._time(received_at);checksum=sha256(raw).hexdigest()
    raw_id=sha256((url+':'+checksum).encode()).hexdigest();count=0
    with db:
        db.execute('INSERT OR IGNORE INTO raw_sources VALUES(?,?,?,?,?)',(raw_id,url,checksum,received_at,raw))
        for row in rows:
            if row['sourceUrl']!=url or row['sourceHash']!=checksum or row['retrievedAt']!=received_at:
                raise ValueError('credit_receipt_binding')
            session=row['metric']+':'+str(row['observationPeriod'] or url)
            old=db.execute('SELECT body FROM observations WHERE source_id=? AND session=? ORDER BY seq DESC LIMIT 1',
                ('credit-conditions:'+row['sourceId'],session)).fetchone()
            prior=json.loads(old[0]) if old else None
            if prior and prior['rawId']==raw_id:continue
            # API response time changes do not create economic revisions.
            if prior and all(prior.get(k)==row.get(k) for k in ('value','unit','segment','dataAsOf','statementJa','validationStatus','providerLastUpdate')):
                continue
            if prior and store._time(received_at)<=store._time(prior['knownAt']):raise ValueError('credit_revision_order')
            revision=prior['revision']+1 if prior else 0
            body={**row,'rawId':raw_id,'revision':revision,'supersedes':prior['observationId'] if prior else None}
            body['revisionStatus']='REVISED' if prior else 'ORIGINAL_RECEIPT'
            body['observationId']=digest(body)
            db.execute('INSERT INTO observations(source_id,session,raw_id,body) VALUES(?,?,?,?)',
                ('credit-conditions:'+row['sourceId'],session,raw_id,store._json(body)));count+=1
    return count


def saved_rows(db, *, cutoff):
    at=store._time(cutoff);by={};all_rows=[]
    for source_id,session,encoded in db.execute("SELECT source_id,session,body FROM observations WHERE source_id LIKE 'credit-conditions:%' ORDER BY seq"):
        row=json.loads(encoded)
        if store._time(row['knownAt'])>at or (row.get('publicationAt') and store._time(row['publicationAt'])>at):continue
        by[(source_id,session)]=row;all_rows.append(row)
    successors={r['supersedes']:r['observationId'] for r in all_rows if r.get('supersedes')}
    return [{**r,'supersededBy':successors.get(r['observationId'])} for r in by.values()]


def snapshot_id(doc):
    return digest({k:doc[k] for k in ('schemaVersion','dimensions','overallState','evidence',
        'actionAuthority','automaticAiCalls','bojTransmission','noteJa')})


def document(db, *, cutoff):
    rows=saved_rows(db,cutoff=cutoff);at=store._time(cutoff);metrics={}
    for row in rows:
        if row.get('value') is not None:metrics.setdefault(row['metric'],[]).append(row)
    for values in metrics.values():values.sort(key=lambda r:r['dataAsOf'])
    control_row=db.execute('SELECT value FROM metadata WHERE key=?',(KEY,)).fetchone()
    control=json.loads(control_row[0]) if control_row else {}
    health=[]
    for source in registry():
        group=source['sourceId'].removeprefix('boj_credit_');items=[r for r in rows if r['sourceId']==source['sourceId']]
        latest=max(items,key=lambda r:str(r.get('dataAsOf') or r.get('publicationDate') or ''),default=None)
        freshness=((latest or {}).get('dataAsOf') if group in GROUPS else (latest or {}).get('publicationDate'))
        stale=bool(latest and freshness and (at.date()-date.fromisoformat(freshness)).days>GROUPS.get(group,{}).get('staleDays',220))
        state=control.get(source['sourceId'],{})
        if state.get('lastAttemptAt') and store._time(state['lastAttemptAt'])>at:state={}
        health.append({**source,'status':'STALE' if stale else 'DEGRADED' if state.get('status')=='FAILED' else 'AVAILABLE' if latest else 'NOT_ACQUIRED',
            'latestPublicationAt':latest.get('publicationAt') if latest else None,
            'latestPublicationDate':latest.get('publicationDate') if latest else None,
            'latestObservationPeriod':latest.get('observationPeriod') if latest else None,
            'dataAsOf':latest.get('dataAsOf') if latest else None,'retrievedAt':latest.get('retrievedAt') if latest else None,
            'validationStatus':latest.get('validationStatus') if latest else 'UNVERIFIED',
            'stale':stale,'count':len(items),'lastFetchStatus':state.get('status','NOT_RUN'),
            'lastAttemptAt':state.get('lastAttemptAt'),'lastSuccessAt':state.get('lastSuccessAt'),
            'errorClass':state.get('errorClass'),'failure':state.get('failure'),'nextCheckAt':state.get('nextCheckAt'),
            'lastSuccessfulParseAt':state.get('lastSuccessfulParseAt'),'staleThresholdDays':GROUPS.get(group,{}).get('staleDays',220),
            'originalByteLimit':MAX_BYTES,'manualDependency':source.get('manualDependency') or ('NEW_DOCUMENT_REVIEW' if latest and latest.get('manualVerificationRequired') else None)})
    def dimension(metric, labels, growth=False):
        values=metrics.get(metric,[]);source=next((h for h in health if values and h['sourceId']==values[-1]['sourceId']),{})
        if not values or (not growth and len(values)<2):return {'status':'INSUFFICIENT_DATA','evidenceIds':[]}
        row=values[-1];previous=values[-2] if len(values)>1 else None
        if not growth:
            months=(date.fromisoformat(row['dataAsOf']).year-date.fromisoformat(previous['dataAsOf']).year)*12+date.fromisoformat(row['dataAsOf']).month-date.fromisoformat(previous['dataAsOf']).month
            if months!=(6 if metric=='npl_ratio' else 3 if metric.startswith('lending_attitude') else 1):return {'status':'INSUFFICIENT_DATA','reason':'NON_CONSECUTIVE_PERIODS','evidenceIds':[]}
        change=float(row['value']) if growth else round(float(row['value'])-float(previous['value']),6)
        return {'status':'INSUFFICIENT_DATA' if source.get('stale') else 'OBSERVED',
            'reason':'STALE' if source.get('stale') else None,
            'direction':labels[0] if change>0 else labels[1] if change==0 else labels[2],
            'value':row['value'],'change':change,'unit':row['unit'],'dataAsOf':row['dataAsOf'],
            'dataAsOfBasis':row.get('dataAsOfBasis'),'observationPeriod':row['observationPeriod'],
            'basis':'PUBLISHED_YEAR_ON_YEAR' if growth else 'PREVIOUS_PUBLISHED_PERIOD_CHANGE',
            'evidenceIds':[r['observationId'] for r in (row,previous) if r],
            'predictiveValidation':'UNVALIDATED'}
    dims={'borrowingCost':dimension('new_loan_rate',('RISING','STABLE','FALLING')),
          'creditGrowth':dimension('loan_growth_yoy',('EXPANDING','STABLE','CONTRACTING'),True),
          'creditQuality':dimension('npl_ratio',('DETERIORATING','STABLE','IMPROVING')),
          'lendingStance':dimension('lending_attitude_small',('EASING','NEUTRAL','TIGHTENING'))}
    references=sorted(rows,key=lambda r:(str(r.get('dataAsOf') or ''),r['knownAt']),reverse=True)
    result={'schemaVersion':VERSION,'asOf':cutoff,'dimensions':dims,
        'overallState':'UNCLASSIFIED' if all(d['status']=='OBSERVED' for d in dims.values()) else 'INSUFFICIENT_DATA',
        'evidence':references,'sourceHealth':health,'actionAuthority':False,'automaticAiCalls':0,
        'bojTransmission':{'status':'OBSERVED_ONLY','policyFreedomClassification':None,'causalValidation':'UNVALIDATED',
            'evidenceIds':[i for d in dims.values() for i in d.get('evidenceIds',[])],
            'missing':['DATED_OFFICIAL_POLICY_CHANGE_COMPARISON','CAUSAL_TRANSMISSION_VALIDATION'],
            'noteJa':'貸出金利と借り手の貸出態度を政策伝達の観測として読みます。日銀が利上げできる余地の強弱や次の決定は判定していません。'},
        'futureMapResearch':{'status':'RESEARCH_ONLY','liveForecastChanged':False,'validation':'UNVALIDATED',
            'knowledgeCutoff':cutoff,'snapshotVersion':VERSION,'featureIds':[r['observationId'] for r in references],
            'targets':['1579','1360'],'horizons':[1,3,5],
            'missing':['HISTORICAL_RECEIPT_VINTAGES','OUT_OF_SAMPLE_COMPARISON'],
            'requiredComparisons':['CURRENT','CURRENT_PLUS_CREDIT','SIMPLE_BASELINE'],
            'requiredMetrics':['direction','firstMove','upperLowerHits','hitOrder','MAE','MFE','pathSimilarity']},
        'noteJa':'月次・四半期の信用環境です。日々の売買タイミングや暴落確率ではありません。'}
    result['snapshotId']=snapshot_id(result)
    result['futureMapResearch']['snapshotId']=result['snapshotId']
    newest=max((r['knownAt'] for r in rows),default=None)
    result['showToday']=bool(newest and 0<=(at-store._time(newest)).total_seconds()<7*86400)
    return result


class CreditStoreError(RuntimeError):
    """Fixed diagnostics only; never copy SQLite messages, SQL or source bodies."""
    def __init__(self, stage, exc):
        super().__init__('credit_store_failed')
        self.diagnostic = failure_diagnostic(exc, stage=stage)


def failure_diagnostic(exc, *, stage):
    code = getattr(exc, 'sqlite_errorcode', None)
    return {'stage': stage,
            'sqliteCode': code if type(code) is int else None,
            'kind': {5:'BUSY', 6:'LOCKED', 8:'READ_ONLY', 10:'IO_ERROR',
                     11:'CORRUPT', 13:'FULL', 14:'CANNOT_OPEN'}.get(
                         code & 255 if type(code) is int else None, 'OTHER')}


def refresh(path, *, now_iso, get, clock):
    try:
        return _refresh(path, now_iso=now_iso, get=get, clock=clock)
    except sqlite3.Error as exc:
        raise CreditStoreError('CONTROL_OR_PROJECTION', exc) from None


def _refresh(path, *, now_iso, get, clock):
    """Existing collect caller, bounded official requests; screen reads never call it."""
    try:
        db=store.connect(path)
    except sqlite3.Error as exc:
        raise CreditStoreError('OPEN_STORE', exc) from None
    at=store._time(now_iso);requests=0;new=0
    try:
        saved=db.execute('SELECT value FROM metadata WHERE key=?',(KEY,)).fetchone()
        control=json.loads(saved[0]) if saved else {}
        for source in registry():
            sid=source['sourceId'];old=control.get(sid,{})
            if source['eligibilityStatus']!='ARGUS_ELIGIBLE':continue
            if old.get('nextCheckAt') and store._time(old['nextCheckAt'])>at:continue
            state={**old,'lastAttemptAt':now_iso,'errorClass':None,'failure':None};control[sid]=state
            try:
                group=sid.removeprefix('boj_credit_')
                if group in GROUPS:
                    url=api_url(group,now_iso);requests+=1;raw,_=_read(get,url,256_000)
                    received=clock();rows=parse_api(raw,group=group,source_url=url,received_at=received)
                    new+=retain(db,raw,url=url,rows=rows,received_at=received)
                    state['lastSuccessfulParseAt']=received
                else:
                    requests+=1;index,_=_read(get,source['sourceUrl'],256_000)
                    links=Links(index,source['sourceUrl'])
                    prefix='/status/npl/' if sid=='fsa_npl' else '/common/about/kaikaku/fsaanalyticalnotes/' if sid=='fsa_notes' else '/research/brp/fsr/'
                    pages=sorted(u for u in links.urls if approved_url(u) and urlparse(u).path.startswith(prefix) and u.endswith(('.html','.htm')))
                    if not pages:raise ValueError('credit_official_document_not_listed')
                    page=pages[-1];requests+=1;html,_=_read(get,page,256_000)
                    links=Links(html,page);extension='.xlsx' if sid=='fsa_npl' else '.pdf'
                    pdfs=sorted(u for u in links.urls if approved_url(u) and urlparse(u).path.startswith(prefix) and u.endswith(extension))
                    if not pdfs:raise ValueError('credit_official_pdf_not_listed')
                    url=pdfs[0];headers={'If-None-Match':old['etag']} if old.get('url')==url and old.get('etag') else {}
                    requests+=1;raw,receipt=_read(get,url,MAX_BYTES,headers=headers)
                    if raw is not None:
                        received=clock();rows=parse_npl(raw,source_url=url,received_at=received) if sid=='fsa_npl' else [document_row(raw,url=url,received_at=received,source_id=sid)]
                        new+=retain(db,raw,url=url,rows=rows,received_at=received)
                        state['sourceHash']=sha256(raw).hexdigest()
                        if all(r['validationStatus']!='UNVERIFIED' for r in rows):state['lastSuccessfulParseAt']=received
                        else:state['lastSuccessfulParseAt']=None
                    state.update(url=url,etag=receipt.get('ETag') or old.get('etag'))
                state.update(status='AVAILABLE',lastSuccessAt=clock())
            except Exception as exc:
                state.update(status='FAILED',errorClass=type(exc).__name__,
                    failure=failure_diagnostic(exc,stage='SOURCE_ACQUISITION_OR_SAVE'))
            # Daily checks only near the regular release window, never hourly.
            window=group in GROUPS and ((group=='cost' and (at.day<=10 or at.day>=25)) or
                (group=='growth' and at.day<=10) or (group=='stance' and at.month in (1,4,7,10) and at.day<=10))
            days=1 if state['status']=='FAILED' or window else 7
            state['nextCheckAt']=(at+timedelta(days=days)).isoformat()
        with db:db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(KEY,store._json(control)))
        result=document(db,cutoff=clock())
        result['collectionReceipt']={'requests':requests,'newObservations':new,'automaticAiCalls':0}
        return result
    finally:db.close()


def read(path, *, cutoff):
    if not Path(path).is_file():return None
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:return document(db,cutoff=cutoff)
    finally:db.close()


def current_projection(saved, *, cutoff):
    """Age the saved cache on each read without another SQLite/provider read."""
    if not saved:return None
    doc=deepcopy(saved);at=store._time(cutoff);doc['asOf']=cutoff
    for health in doc['sourceHealth']:
        group=health['sourceId'].removeprefix('boj_credit_')
        age_date=health.get('dataAsOf') if group in GROUPS else health.get('latestPublicationDate')
        if age_date and (at.date()-date.fromisoformat(age_date)).days>GROUPS.get(group,{}).get('staleDays',220):
            health.update(stale=True,status='STALE')
            dim={'cost':'borrowingCost','growth':'creditGrowth','stance':'lendingStance','fsa_npl':'creditQuality'}.get(group)
            if dim:doc['dimensions'][dim]={**doc['dimensions'][dim],'status':'INSUFFICIENT_DATA','reason':'STALE'}
    if any(d['status']!='OBSERVED' for d in doc['dimensions'].values()):doc['overallState']='INSUFFICIENT_DATA'
    newest=max((r['knownAt'] for r in doc['evidence']),default=None)
    doc['showToday']=bool(newest and 0<=(at-store._time(newest)).total_seconds()<7*86400)
    doc['snapshotId']=snapshot_id(doc)
    doc['futureMapResearch']['snapshotId']=doc['snapshotId']
    return doc


def verify_observation(row, raw, *, url, first_received):
    """Private export admits only deterministically reconstructed fields."""
    validate_original(url,raw)
    if type(row.get('revision')) is not int or row['revision']<0:raise ValueError('credit_backup_revision')
    if (row['revision']==0 and row.get('supersedes') is not None) or (row['revision']>0 and not re.fullmatch(r'[0-9a-f]{64}',str(row.get('supersedes')))):raise ValueError('credit_backup_supersedes')
    if store._time(first_received)>store._time(row['retrievedAt']):raise ValueError('credit_backup_receipt')
    if url.startswith(API):
        group=next(g for g in GROUPS if parse_qs(urlparse(url).query)['db']==[GROUPS[g]['db']])
        expected=next((r for r in parse_api(raw,group=group,source_url=url,received_at=row['retrievedAt'])
            if r['metric']==row['metric'] and r['observationPeriod']==row['observationPeriod']),None)
    elif url.endswith('.xlsx'):
        expected=next((r for r in parse_npl(raw,source_url=url,received_at=row['retrievedAt'])
            if r['metric']==row['metric'] and r['observationPeriod']==row['observationPeriod']),None)
    else:expected=document_row(raw,url=url,received_at=row['retrievedAt'],source_id=row['sourceId'])
    if not expected:raise ValueError('credit_backup_source_row')
    body={**expected,'rawId':sha256((url+':'+sha256(raw).hexdigest()).encode()).hexdigest(),
        'revision':row['revision'],'supersedes':row.get('supersedes')}
    body['revisionStatus']='REVISED' if body['revision'] else 'ORIGINAL_RECEIPT'
    body['observationId']=digest(body)
    if body!=row:raise ValueError('credit_backup_observation_fields')


def explanation_facts(doc):
    if not doc:return []
    selected=[]
    ids={i for d in doc['dimensions'].values() for i in d.get('evidenceIds',[])}
    for row in doc['evidence']:
        if row['observationId'] not in ids and not row.get('statementJa'):continue
        stale=any(h['sourceId']==row['sourceId'] and h['stale'] for h in doc['sourceHealth'])
        period=f"{row['observationPeriod'][:4]}年第{row['observationPeriod'][-1]}四半期（期末区分 {row['dataAsOf']}、実際の調査日は不明）" if row.get('dataAsOfBasis')=='QUARTER_END_LABEL' else row['dataAsOf']
        text=row.get('statementJa') or f"{'古い観測・現在の状態には使用不可。' if stale else ''}{row['title']}：{row['value']} {row['unit']}、対象 {period}。公表日 {row.get('publicationDate') or '未確認'}、公表時刻未確認、受領 {row['retrievedAt']}。"
        selected.append({'text':text[:500],'source':'credit_conditions','priority':'P2' if row.get('statementJa') else 'P1',
            'verification':'VERIFIED','provenance':{'scope':'published_metadata_snapshot',
                'eventId':row['observationId'],'revision':row['revision'],'sourceLabel':row['publisher'],
                'publishedAt':row.get('publicationAt'),'receivedAt':row['retrievedAt'],
                'observedAt':None,'url':row['sourceUrl'],'sourceResponseSha256':row['sourceHash']}})
    return selected[:10]


def asset_impact(doc, *, sector_code):
    if not doc or doc['dimensions']['borrowingCost']['status']!='OBSERVED' or not doc['dimensions']['borrowingCost'].get('evidenceIds'):return None
    # Official JP sector33 codes, not symbol/name guesses or owner holdings.
    notes={'7050':'銀行の利息収益には貸出金利の転嫁が影響します。一方、資金調達費用と借り手の信用損失も必要な確認点です。',
        '8050':'不動産では借り換え金利と資金調達条件が確認点です。個社の負債・返済期日は、この統計だけでは分かりません。'}
    if str(sector_code) not in notes:return None
    return {'kind':'ARGUS_HYPOTHESIS','textJa':notes[str(sector_code)],
        'evidenceIds':doc['dimensions']['borrowingCost']['evidenceIds'],
        'snapshotId':doc['snapshotId'],'actionAuthority':False,'predictiveValidation':'UNVALIDATED',
        'sources':[{k:r[k] for k in ('sourceUrl','publisher','dataAsOf','retrievedAt','observationId')}
            for r in doc['evidence'] if r['observationId'] in doc['dimensions']['borrowingCost']['evidenceIds']]}


def context_reference(doc):
    """Compact saved state for the existing brief/history, never historical PDFs."""
    ids={i for d in doc['dimensions'].values() for i in d.get('evidenceIds',[])}
    selected=[r for r in doc['evidence'] if r['observationId'] in ids or r['metric']=='published_analysis'][:12]
    result={k:deepcopy(doc[k]) for k in ('schemaVersion','snapshotId','dimensions','overallState','sourceHealth','bojTransmission','actionAuthority','showToday','noteJa')}
    result['evidence']=selected
    result['futureMapResearch']={**doc['futureMapResearch'],'featureIds':[r['observationId'] for r in selected]}
    return result

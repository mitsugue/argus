"""Scheduled bounded acquisition into the existing market ledger; no LLM calls."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import argus_market_ledger as ledger
import argus_jp_fiscal_sources as sources
from argus_jp_fiscal_monitor import instant

CAO_INDEX = 'https://www5.cao.go.jp/keizai2/keizai-syakai/shisan.html'
JST = ZoneInfo('Asia/Tokyo')


def ledger_slice(state):
    """Only this monitor's observations; unrelated histories are never copied."""
    series = sources.ledger_series()
    rows = [deepcopy(row) for row in state.get('observations', ())
            if row.get('seriesId') in series]
    imports = {row.get('importId') for row in rows}
    result = ledger.empty_state()
    result.update(observations=rows,
        imports=[deepcopy(row) for row in state.get('imports', ()) if row.get('importId') in imports],
        rolledBackImports=[key for key in state.get('rolledBackImports', ()) if key in imports],
        lastUpdatedAt=state.get('lastUpdatedAt'))
    if state.get('fiscalMonitor'):
        result['fiscalMonitor'] = deepcopy(state['fiscalMonitor'])
    return result


def expected_session(calendar, now_iso):
    """MOF publishes a session on the following JP business day around 09:30."""
    now = instant(now_iso).astimezone(JST)
    by = {r['Date']: str(r['HolDiv']) for r in calendar}
    recent = [(now.date()-timedelta(days=i)).isoformat() for i in range(15)]
    if any(day not in by or by[day] not in ('0','1','2','3') for day in recent):
        raise ValueError('official_calendar_incomplete')
    sessions = sorted(day for day in recent if by[day] == '1')
    due = [a for a,b in zip(sessions,sessions[1:])
        if datetime.fromisoformat(b+'T09:30:00').replace(tzinfo=JST) <= now]
    if not due:
        raise ValueError('official_publication_session_unknown')
    return due[-1]


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.documents = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            url = urljoin(CAO_INDEX, dict(attrs).get('href',''))
            if url.startswith('https://www5.cao.go.jp/keizai2/keizai-syakai/shisan/') and url.endswith('hontai.pdf'):
                self.documents.add(url)


def _read(get, url, limit, *, headers=None):
    with get(url, timeout=(5,15), stream=True, allow_redirects=False, headers=headers or {}) as response:
        if response.status_code == 304:
            return None, dict(response.headers)
        if response.status_code != 200:
            raise ValueError('official_source_http_'+str(response.status_code))
        chunks=[]; size=0
        for chunk in response.iter_content(32768):
            size += len(chunk)
            if size > limit:
                raise ValueError('official_source_size')
            chunks.append(chunk)
        return b''.join(chunks), dict(response.headers)


def refresh(state, *, now_iso, calendar, get, fx_rows=()):
    """At most three fixed official reads per day; failed acquisition retries hourly.

    Source hash changes wait for a reviewed table edition. Old observations and
    warnings survive failure. The returned ledger uses the caller's existing
    durable checkpoint, and screen reads never call this function.
    """
    now = instant(now_iso); previous = state.get('fiscalMonitor') or {}
    session=None; calendar_error=None
    try:
        session=expected_session(calendar,now_iso)
    except ValueError as exc:
        calendar_error=str(exc)
    last = previous.get('lastAttemptAt')
    healthy = previous.get('acquisitionStatus') == 'AVAILABLE'
    wait = 86400 if healthy else 3600
    newly_due = healthy and session and session != previous.get('expectedMarketSession')
    if last and not newly_due and 0 <= (now-instant(last)).total_seconds() < wait:
        return {'changed':False,'status':'NOT_DUE','state':state,'requests':0}
    control = deepcopy(previous)
    control.update(schemaVersion='jp-fiscal-monitor-state-v1', lastAttemptAt=now_iso,
                   updatedAt=now_iso, sourceUrl=CAO_INDEX, requests=0)
    candidates=[]; table=sources.reviewed_table(); errors={}
    fiscal_status='FAILED'; market_status='FAILED'
    if calendar_error:
        errors['calendar']=calendar_error
    control['expectedMarketSession']=session
    try:
        control['requests'] += 1
        raw,_ = _read(get,CAO_INDEX,256_000)
        links=_Links(); links.feed(raw.decode('utf-8-sig'))
        if links.documents != {table['sourceUrl']}:
            fiscal_status='UNREVIEWED_SOURCE_EDITION'
        else:
            headers={}
            if control.get('verifiedSourceHash')==table['sourceSha256'] and control.get('etag'):
                headers['If-None-Match']=control['etag']
            control['requests'] += 1
            pdf, receipt = _read(get,table['sourceUrl'],2_000_000,headers=headers)
            observed = sha256(pdf).hexdigest() if pdf is not None else control.get('verifiedSourceHash')
            if observed != table['sourceSha256']:
                fiscal_status='UNREVIEWED_SOURCE_REVISION'
            else:
                fiscal_status='AVAILABLE'
                control.update(verifiedSourceHash=observed, sourceVerifiedAt=now_iso,
                    etag=receipt.get('ETag') or control.get('etag'))
                candidates += sources.missing_ledger_candidates(state,
                    sources.annual_ledger_candidates(table,acquired_at=now_iso))
    except Exception as exc:
        errors['fiscal']=type(exc).__name__+':'+str(exc)[:120]
    try:
        control['requests'] += 1
        raw,_ = _read(get,sources.JGB_URL,512_000)
        rates=sources.parse_jgb_csv(raw,acquired_at=now_iso)
        candidates += sources.missing_market_candidates(state,sources.market_ledger_candidates(rates))
        market_status='AVAILABLE'
        control['marketLastSuccessAt']=now_iso
    except Exception as exc:
        errors['market']=type(exc).__name__+':'+str(exc)[:120]
    updated=state
    if candidates:
        result=ledger.import_rows(state,candidates,now_iso=now_iso,dry_run=False,rebuild_after_commit=False)
        if not result['ok']:
            raise ValueError('fiscal_ledger_import_failed')
        updated=result['state']
    control.update(fiscalAcquisitionStatus=fiscal_status,marketAcquisitionStatus=market_status,
        acquisitionStatus='AVAILABLE' if fiscal_status==market_status=='AVAILABLE' and session else 'INCOMPLETE',
        errors=errors, importedRows=len(candidates), automaticAiCalls=0)
    if session:
        year=now.astimezone(JST).year-(now.astimezone(JST).month<4)
        control['report']=sources.ledger_environment_report(updated,fiscal_year=year,
            expected_session=session,as_of=now_iso,fx_rows=fx_rows,
            previous=previous.get('report'),market_acquisition=market_status,
            fiscal_acquisition=fiscal_status)
    else:
        # A missing official calendar is not a new calculation or an all-clear.
        control['reportStatus']='CALENDAR_UNAVAILABLE'
    if session:
        control['reportStatus']='AVAILABLE'
    return {'changed':True,'status':control['acquisitionStatus'],
        'state':{**updated,'fiscalMonitor':control},'requests':control['requests']}


def public_document(state):
    """Bounded saved projection; no acquisition or current-state recalculation."""
    stored=state.get('fiscalMonitor') or {}; report=stored.get('report') or {}
    cases={}
    for case,row in report.get('cases',{}).items():
        fiscal=row.get('fiscal') or {}
        inputs=fiscal.get('inputs') or {}
        cases[case]={k:deepcopy(row.get(k)) for k in ('id','warningLevel','dataCompleteness',
            'currentReasons','releaseConditions','previousWarningRetained','ruleVersion','ruleValidation')}
        cases[case]['fiscal']={k:deepcopy(fiscal.get(k)) for k in
            ('id','status','values','definition','comparison','uncertainty','missing','limitations')}
        cases[case]['sources']=[{k:deepcopy(v.get(k)) for k in ('id','metric','year',
            'sourceUrl','sourceRevision','sourceHash','publishedDate','publishedAt','knownAt')}
            for v in inputs.values()]
    first=next(iter(report.get('cases',{}).values()),{})
    return {'schemaVersion':'jp-fiscal-public-v1','id':report.get('id'),
        'status':stored.get('reportStatus','NOT_RUN'),
        'acquisitionStatus':stored.get('acquisitionStatus','NOT_RUN'),
        'fiscalAcquisitionStatus':stored.get('fiscalAcquisitionStatus','NOT_RUN'),
        'marketAcquisitionStatus':stored.get('marketAcquisitionStatus','NOT_RUN'),
        'calculatedAt':report.get('asOf'),'sourceVerifiedAt':stored.get('sourceVerifiedAt'),
        'lastMarketSuccessAt':stored.get('marketLastSuccessAt'),
        'expectedMarketSession':report.get('expectedMarketSession'),
        'selectedCase':None,'cases':cases,'market':deepcopy(first.get('market')),
        'actionAuthority':False,'predictivePerformance':'UNVALIDATED',
        'automaticAiCalls':0,'fetchesDuringRead':0,'notificationDelivery':'NOT_CONNECTED',
        'persistenceMechanism':'SHARED_LEDGER_CHECKPOINT'}


def explanation_facts(document):
    """Measured fiscal inputs and market yields remain separately attributable."""
    if not document.get('id'):
        return []
    facts=[]
    labels={'baseline':'現状投影','growth_1':'成長戦略実現①','growth_2':'成長戦略実現②'}
    if document.get('acquisitionStatus')!='AVAILABLE':
        facts.append({'text':'日本の財政・金利環境は更新確認が未完了。保存した警戒を取得障害だけで解除しません。',
            'priority':'P1','source':'jp_fiscal_environment','verification':'UNCONFIRMED',
            'provenance':{'eventId':document['id']+':acquisition','asOf':document.get('lastMarketSuccessAt')}})
    for case,row in document.get('cases',{}).items():
        fiscal=row['fiscal']; values=fiscal.get('values') or {}; definition=fiscal.get('definition') or {}
        if fiscal.get('status')!='AVAILABLE':
            continue
        kind={'ACTUAL':'実績','ESTIMATE':'推計','FORECAST':'見通し'}.get(definition.get('estimateType'),'未確認')
        facts.append({'text':f"日本・国地方・{definition.get('year')}年度{kind}・{labels[case]}："
            f"名目成長率{values['growthPct']:g}%、政府実効金利{values['effectiveRatePct']:g}%、"
            f"PB{values['primarySurplusPct']:g}%GDP。機械的債務比率圧力{values['pressurePoints']:+.2f}ポイント。"
            '株価確率・財政危機の判定ではありません。',
            'priority':'P1' if row.get('warningLevel') in ('WATCH','WARNING') else 'P2',
            'source':'jp_fiscal_environment','verification':'UNCONFIRMED',
            'provenance':{'eventId':row['id'],'asOf':(row['sources'][0] if row['sources'] else {}).get('knownAt'),
                'sourceLabelJa':'内閣府・定義をそろえた財政計算',
                'url':(row['sources'][0] if row['sources'] else {}).get('sourceUrl')}})
    market=document.get('market') or {}
    adverse=market.get('adverseGroups') or []
    if adverse:
        facts.append({'text':'日本の市場監視：'+('長期・超長期国債金利' if 'JGB' in adverse else '')+
            ('・ドル円' if 'FX' in adverse else '')+'に継続的な変化。既存政府債務の実効金利とは別系列。財政不安が原因とは未確認。',
            'priority':'P1','source':'jp_fiscal_environment','verification':'UNCONFIRMED',
            'provenance':{'eventId':market.get('id'),'asOf':document.get('expectedMarketSession'),
                'sourceLabelJa':'財務省・国債市場金利','url':sources.JGB_URL}})
    # Use the existing browser/brief provenance contract, not a parallel shape.
    for fact in facts:
        original = fact['provenance']
        at = original.get('asOf')
        fact['provenance'] = {'scope':'published_metadata_snapshot',
            'eventId':original.get('eventId'),'revision':None,'publishedAt':None,
            'receivedAt':at if isinstance(at,str) and len(at)>10 else None,
            'observedAt':at,'url':original.get('url'),
            'sourceLabel':original.get('sourceLabelJa')}
    return facts


def context_reference(document):
    """Small immutable calculation snapshot, with receipt-only times excluded.

    This is explanatory context, never a replacement for the stock/index
    forecast. Stable observations do not become new AI work on each poll.
    """
    if not document.get('id'):
        return None
    reference = {key:deepcopy(document.get(key)) for key in (
        'id','status','fiscalAcquisitionStatus','marketAcquisitionStatus',
        'expectedMarketSession','selectedCase','actionAuthority',
        'predictivePerformance')}
    reference['cases'] = {}
    source_documents = {}
    for case,row in document.get('cases',{}).items():
        # IDs bind back to the saved ledger; repeated source metadata is sent once.
        fiscal = row['fiscal']
        reference['cases'][case] = {key:deepcopy(row.get(key)) for key in (
            'id','warningLevel','dataCompleteness','currentReasons','releaseConditions',
            'previousWarningRetained','ruleVersion','ruleValidation')}
        reference['cases'][case]['fiscal'] = {key:deepcopy(fiscal.get(key)) for key in (
            'id','status','values','definition','comparison','uncertainty','missing','limitations')}
        for source in row.get('sources',()):
            identity = source.get('sourceHash') or source.get('sourceUrl')
            source_documents[identity] = {key:deepcopy(source.get(key)) for key in (
                'sourceHash','sourceUrl','sourceRevision','publishedDate','publishedAt','knownAt')}
    reference['sources'] = list(source_documents.values())
    market = document.get('market') or {}
    reference['market'] = {key:deepcopy(market.get(key)) for key in (
        'id','status','warningLevel','adverseGroups','groups','auctionStatus','rule','causalityConfirmed')}
    reference['market']['series'] = {sid:{key:deepcopy(row.get(key)) for key in (
        'status','adverse','latestValue','change','comparisonFrom','comparisonTo',
        'comparisonSessions','confirmationSessions','threshold','sourceUrl','observedAt')}
        for sid,row in market.get('series',{}).items()}
    reference['interpretation'] = {
        'explanationOrder':['change','meaning','facts_and_assumptions','conditional_transmission',
                            'owner_asset_evidence','next_checks_and_release_conditions'],
        'marketYieldIsEffectiveGovernmentRate':False,
        'fiscalStatisticsAlonePredictStockDirection':False,
        'companySpecificEffectsRequireCompanyEvidence':True,
        'stockProbabilityCalculationAllowed':False,
        'scenarioMustRemainSeparate':True}
    import json
    if len(json.dumps(reference,ensure_ascii=False,allow_nan=False).encode()) > 16_000:
        raise ValueError('fiscal_explanation_context_bound')
    return reference

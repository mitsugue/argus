"""Synthetic receipts only: no live source, AI call or original result mutation."""
import copy
import json

import pytest
import argus_macro_material as material
import argus_market_brief as brief
import scanner

NOW = '2026-10-15T02:30:00Z'

def row(code='CPI'):
    return {'eventId': 'fixture-'+code, 'eventCode': code, 'eventDate': '2026-10-14',
        'eventTimeUtc': '2026-10-14T12:30:00Z', 'displayImpact': 'high',
        'actualRevisionId': 'fixture-original',
        'actual': {'available': True, 'referenceMatched': True,
            'receivedAt': '2026-10-14T12:32:00Z', 'availableFrom': '2026-10-14T12:32:00Z',
            'releasedAt': None, 'source': 'BLS', 'headline': '消費者物価指数 総合CPI 前月比+0.6% / 前年比+3.7%',
            'metrics': {'headlineCpiYoY': 3.7}, 'previousMetrics': {'headlineCpiYoY': 3.4},
            'sourceUrl': 'https://www.bls.gov/news.release/cpi.nr0.htm'}}

def selected(r=None, now=NOW):
    return material.released_materials([r or row()], now_iso=now)


def test_result_is_material_without_news_or_causal_confirmation_and_keeps_original():
    r=row(); original=copy.deepcopy(r); result=selected(r)[0]
    assert result['materialOrigin']=='OFFICIAL_MACRO_RESULT' and result['severity']=='HIGH'
    assert result['confirmationState']=='MARKET_CONFIRMATION_PENDING'
    assert result['sourcePublishedAt'] is None and result['consensusEvidence'] is None
    assert result['marketReadings']==[] and result['sdaAuthority'] is False
    assert result['alertEligible'] is False
    assert '拡大' in result['whyJa'] and 'なり得ます' in result['whyJa']
    assert '未確認' in result['japanImpactJa']
    assert r==original


@pytest.mark.parametrize('field,value', [
    ('receivedAt',None),('availableFrom',None),('receivedAt','2026-10-16T12:00:00Z'),
    ('availableFrom','2026-10-16T12:00:00Z'),('receivedAt','2026-10-14T12:00:00Z'),
    ('available',False),('referenceMatched',False),('headline',''),
    ('sourceUrl','https://example.com/news'),('sourceUrl','http://www.bls.gov/news'),
    ('sourceUrl','https://user@www.bls.gov/news'),('metrics',{'value': float('nan')}),
    ('metrics',{'value':True}),('metrics',{}),
])
def test_missing_future_unofficial_or_invalid_result_is_not_fabricated(field,value):
    r=row();r['actual'][field]=value
    assert not selected(r)


def test_schedule_48_hours_cannot_be_extended_by_later_receipt_or_correction():
    r=row();assert selected(r, '2026-10-16T12:30:00Z')
    assert not selected(r,'2026-10-16T12:30:01Z')
    r['actual']['receivedAt']=r['actual']['availableFrom']='2026-10-16T12:29:00Z'
    assert not selected(r,'2026-10-16T12:30:01Z')
    assert material.released_materials([r],now_iso='2026-10-17T00:00:00Z',history=True)[0]['staleness']=='STALE'
    assert not material.released_materials([r],now_iso='2026-10-22T12:30:01Z',history=True)
    r=row();r['eventTimeUtc']='2026-10-16T12:30:00Z';assert not selected(r)


@pytest.mark.parametrize('code',['PPI','PCE','NFP','GDP','JOLTS','FOMC','BOJ'])
def test_same_result_path_for_other_important_events(code):
    assert selected(row(code))[0]['eventCode']==code


def test_revision_changes_hash_not_identity_and_selects_latest_without_mutating_original():
    old=row();new=copy.deepcopy(old)
    new['actual']['receivedAt']=new['actual']['availableFrom']='2026-10-15T01:00:00Z'
    new['actual']['metrics']['headlineCpiYoY']=3.8
    a=selected(old)[0];b=selected(new)[0]
    assert a['eventId']==b['eventId'] and a['sourceRowSha256']!=b['sourceRowSha256']
    assert material.released_materials([new,old],now_iso=NOW)==[b]


def test_result_gets_brief_slot_even_with_two_mail_headlines_and_upcoming_event():
    news=[{'severity':'HIGH','headlineJa':'別の重要発表'+str(i)} for i in range(2)]
    b=brief.compose_brief(now_iso=NOW,news_events=news,released_events=selected(),
        imminent_events=[{'title':'米PPI','countdown':'D','eventTimeUtc':'2026-10-15T12:30:00Z'}])
    assert '米CPI' in b['now'] and '米PPI' in b['now']
    f=b['facts'][0];assert f['priority']=='P0' and f['source']=='official_macro_result'
    assert f['verification']=='VERIFIED' and f['provenance']['publishedAt'] is None
    context=brief.unified_context(b);ref=context['facts'][0]['evidenceId']
    diag={};assert material.checked_coverage({'sections':{}},context,diag) is None
    assert diag['reason']=='important_macro_result_omitted'
    for key in ('view','reasons'):
        summary={'sections':{key:{'textJa':'CPIの影響は未確認。','evidenceIds':[ref]}}}
        assert material.checked_coverage(summary,context,{})==summary
    assert [f['priority'] for f in b['facts']]==sorted(f['priority'] for f in b['facts'])


def test_exact_result_changes_bypass_coalescing_but_check_clock_does_not():
    a=brief.compose_brief(now_iso=NOW,released_events=selected())
    b=brief.compose_brief(now_iso='2026-10-15T02:40:00Z',released_events=selected())
    assert scanner._market_brief_urgent_signature(a)==scanner._market_brief_urgent_signature(b)
    r=row();r['actual']['metrics']['headlineCpiYoY']=3.8
    c=brief.compose_brief(now_iso=NOW,released_events=selected(r))
    assert scanner._market_brief_urgent_signature(a)!=scanner._market_brief_urgent_signature(c)


def test_cached_news_route_projects_result_without_fetch_ai_or_store_write(monkeypatch):
    def forbidden(*args,**kw):raise AssertionError('unexpected operation')
    from datetime import datetime
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:NOW)
    # The route reads the wall clock; the fixture's result is recent only at NOW
    # (this started failing on 2026-10-17, two days after the fixture's time).
    monkeypatch.setattr(scanner.time,'time',lambda:datetime.fromisoformat(NOW.replace('Z','+00:00')).timestamp())
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS',{'fixture':row()})
    monkeypatch.setattr(scanner,'_news_intel_ensure_loaded',lambda:None)
    monkeypatch.setattr(scanner,'_NEWS_INTEL',{'events':{},'order':[],'health':{'status':'HEALTHY'}})
    monkeypatch.setattr(scanner,'_macro_analysis_restore_once',forbidden)
    monkeypatch.setattr(scanner,'_openai_prose',forbidden)
    monkeypatch.setattr(scanner.requests,'get',forbidden)
    monkeypatch.setattr(scanner,'_macro_analysis_persist',forbidden)
    old=copy.deepcopy(scanner._MACRO_ANALYSIS)
    with scanner.app.test_request_context('/api/argus/news-intelligence'):
        doc=scanner.api_argus_news_intelligence().get_json()
    assert doc['eventCount']==1 and doc['events'][0]['materialOrigin']=='OFFICIAL_MACRO_RESULT'
    assert scanner._MACRO_ANALYSIS==old
    assert 'sourceHttpReceipt' not in json.dumps(doc)


def test_news_cutoff_excludes_later_macro_receipt_even_with_newer_composer_clock(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: NOW)
    monkeypatch.setattr(scanner.time, 'time', lambda: datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS', {'fixture':row()})
    monkeypatch.setattr(scanner, '_news_intel_ensure_loaded', lambda:None)
    monkeypatch.setattr(scanner, '_NEWS_INTEL', {'events':{},'order':[],'health':{'status':'HEALTHY'}})
    with scanner.app.test_request_context('/api/argus/news-intelligence'):
        assert scanner.api_argus_news_intelligence().get_json()['events']==[]


def test_official_result_uses_existing_news_response_slot_without_deleting_article(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: NOW)
    monkeypatch.setattr(scanner.time, 'time', lambda: datetime.fromisoformat(NOW.replace('Z','+00:00')).timestamp())
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS', {'fixture':row()})
    monkeypatch.setattr(scanner, '_news_intel_ensure_loaded', lambda:None)
    article={'eventId':'article-fixture','source':'米財務省','sourceFamily':'US_TREASURY',
        'sourceReceivedAt':'2026-10-15T01:00:00Z','headlineJa':'合成の別の記事',
        'titleOriginal':'合成の別の記事','severity':'HIGH','analysisState':'DETERMINISTIC_ONLY'}
    store={'events':{'article-fixture':article},'order':['article-fixture'],'health':{'status':'HEALTHY'}}
    monkeypatch.setattr(scanner, '_NEWS_INTEL', store)
    monkeypatch.setattr(scanner, '_NEWS_EVENT_CAP', 1)
    monkeypatch.setattr(scanner, '_causal_memory_summary', lambda *a:None)
    monkeypatch.setattr(scanner, '_news_decorate', lambda *a:{'displayTitleJa':'合成の別の記事','translationStatus':'not_needed'})
    original=copy.deepcopy(store)
    with scanner.app.test_request_context('/api/argus/news-intelligence'):
        result=scanner.api_argus_news_intelligence().get_json()
    assert result['eventCount']==result['retainedEventLimit']==1
    assert result['events'][0]['materialOrigin']=='OFFICIAL_MACRO_RESULT'
    assert store==original


def test_news_worker_restores_saved_result_before_blocking_intake(monkeypatch):
    calls=[]
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS',{})
    def restore():
        calls.append('restore')
        scanner._MACRO_ANALYSIS['fixture']=row()
    def intake():
        calls.append('intake')
        assert scanner._macro_material_cached(now_iso=NOW)[0]['eventCode']=='CPI'
    class EndCycle(BaseException):pass
    def stop(_):raise EndCycle()
    monkeypatch.setattr(scanner,'_macro_analysis_restore_once',restore)
    monkeypatch.setattr(scanner,'_news_intake_cycle',intake)
    monkeypatch.setattr(scanner.time,'sleep',stop)
    with pytest.raises(EndCycle):scanner._news_intake_loop()
    assert calls==['restore','intake']


def test_brief_worker_restores_macro_before_composing_without_mail_worker(monkeypatch):
    import threading
    calls=[]
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS',{})
    monkeypatch.setattr(scanner,'_MARKET_BRIEF_WORKER',{'lastAttemptMonotonic':None,'status':'NOT_RUN'})
    monkeypatch.setattr(scanner,'_MARKET_BRIEF_WORKER_LOCK',threading.Lock())
    monkeypatch.setattr(scanner,'_MARKET_BRIEF',{'historyRestoreAttempted':True})
    monkeypatch.setattr(scanner._OWNER_DIALOGUE_RECOVERY,'tick',lambda:None)
    for name in ('_market_brief_history_outcomes','_market_brief_history_sync'):
        monkeypatch.setattr(scanner,name,lambda:None)
    def restore():
        calls.append('restore');scanner._MACRO_ANALYSIS['fixture']=row()
    def refresh(**kwargs):
        calls.append('compose')
        assert kwargs=={'allow_ai':True}
        assert scanner._macro_material_cached(now_iso=NOW)[0]['eventCode']=='CPI'
        return {'unifiedStatus':'GENERATED'}
    monkeypatch.setattr(scanner,'_macro_analysis_restore_once',restore)
    monkeypatch.setattr(scanner,'_market_brief_refresh',refresh)
    assert scanner._market_brief_worker_tick()['status']=='GENERATED'
    assert scanner._market_brief_worker_tick()['status']=='NOT_DUE'
    assert calls==['restore','compose']


def test_existing_snapshot_restore_then_news_needs_no_event_panel_or_new_result(monkeypatch,tmp_path):
    import requests
    r=row();snapshot=scanner.argus_macro_event_store.serialize_snapshot([r],as_of=NOW)
    path=tmp_path/'macro.json';path.write_text(json.dumps({'items':{'fixture':r},'state':{}}))
    original=path.read_bytes();requests_seen=[]
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS',{})
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS_STATE',{'restored':False})
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS_FILE',str(path))
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:NOW)
    class Reply:
        status_code=200
        text=json.dumps(snapshot)
    def ledger(url,**kwargs):
        assert '/macro-events/analysis/latest.json?' in url and kwargs=={'timeout':6}
        requests_seen.append(url);return Reply()
    monkeypatch.setattr(requests,'get',ledger)
    scanner._macro_analysis_restore_once()
    scanner._macro_analysis_restore_once()
    assert len(requests_seen)==1
    assert scanner._macro_material_cached(now_iso=NOW)[0]['sourceReceivedAt']==r['actual']['receivedAt']
    assert path.read_bytes()==original
    monkeypatch.setattr(requests,'get',lambda *a,**k:pytest.fail('GET must not restore again'))
    assert scanner._macro_material_cached(now_iso=NOW)[0]['eventCode']=='CPI'


def test_concurrent_background_restore_waits_for_cache_population(monkeypatch,tmp_path):
    import threading
    first_entered=threading.Event();release=threading.Event();second_started=threading.Event();second_done=threading.Event()
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS',{})
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS_STATE',{'restored':False})
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS_FILE',str(tmp_path/'absent.json'))
    monkeypatch.setattr(scanner,'_MACRO_RESTORE_LOCK',threading.Lock())
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:NOW)
    snapshot=scanner.argus_macro_event_store.serialize_snapshot([row()],as_of=NOW)
    calls=[]
    class Reply:
        status_code=200
        text=json.dumps(snapshot)
    def ledger(*args,**kwargs):
        calls.append(1);first_entered.set();assert release.wait(2);return Reply()
    monkeypatch.setattr(scanner.requests,'get',ledger)
    first=threading.Thread(target=scanner._macro_analysis_restore_once)
    def second_read():
        second_started.set();scanner._macro_analysis_restore_once();second_done.set()
    second=threading.Thread(target=second_read)
    first.start();assert first_entered.wait(2);second.start();assert second_started.wait(2)
    try:assert not second_done.wait(.05)
    finally:
        release.set();first.join(2);second.join(2)
    assert not first.is_alive() and not second.is_alive() and second_done.is_set()
    assert calls==[1] and scanner._macro_material_cached(now_iso=NOW)[0]['eventCode']=='CPI'


def article():
    return {'eventId':'synthetic-news-cpi','source':'合成の報道元','sourceTier':'trusted_subscription',
        'sourceReceivedAt':'2026-10-15T01:00:00Z','sourcePublishedAt':'2026-10-15T00:50:00Z',
        'headlineJa':'米CPIの上振れで株安',
        'facts':['ガソリン高がCPIを押し上げたとの報道。','市場予想を上回るコアCPIを受け利上げ警戒が強まり株安との報道。'],
        'consensusEvidence':{'comparisonDirection':'ABOVE_CONSENSUS'}}


def test_event_news_reports_story_and_comparison_without_claiming_causality_or_actual_yield_rise():
    a=article();r=row();old=copy.deepcopy((r,a))
    c=material.news_context(r,[a],now_iso=NOW)
    assert c['storyStatus']=='REPORTED_CONTEXT_PRESENT' and c['requestedCpiStoryAudit']['allLinksReported']
    assert c['reportedComparison']=='ABOVE_CONSENSUS' and '一部項目' in c['comparisonJa']
    assert c['quantitativeSurpriseVerified'] is c['causalAttributionVerified'] is False
    assert c['articles'][0]['source']=='合成の報道元'
    assert (r,a)==old
    assert material.news_context(r,[a],now_iso='2026-10-15T03:00:00Z')['sourceDigest']==c['sourceDigest']


@pytest.mark.parametrize('change',[
    {'sourceTier':'unknown'},{'sourceReceivedAt':'2026-10-14T12:00:00Z'},
    {'sourceReceivedAt':'2026-10-16T12:00:00Z'},
    {'sourcePublishedAt':'2026-10-14T11:00:00Z'},
    {'headlineJa':'PPIの報道','facts':['生産者物価が上昇']},
    {'materialOrigin':'OFFICIAL_MACRO_RESULT'},
])
def test_event_news_rejects_untrusted_wrong_release_future_or_pre_release_report(change):
    a={**article(),**change};c=material.news_context(row(),[a],now_iso=NOW)
    assert c['articles']==[] and c['reportedComparison']=='UNAVAILABLE'


def test_missing_story_links_are_visible_and_no_comparison_is_derived_from_actual_or_previous_value():
    a=article();a.update(headlineJa='米CPI公式結果の報道',facts=['米CPIの公式結果が掲載された。'],consensusEvidence=None)
    c=material.news_context(row(),[a],now_iso=NOW)
    assert c['storyStatus']=='ARTICLE_EVIDENCE_INCOMPLETE' and not any(c['storyCoverage'].values())
    assert c['reportedComparison']=='UNAVAILABLE' and '未受領' in c['comparisonJa']
    a['facts']=['米10年金利が実際には低下した。']
    assert material.news_context(row(),[a],now_iso=NOW)['storyCoverage']['rateExpectations'] is False


def test_public_metadata_only_has_own_published_and_receipt_times_and_never_claims_article_read():
    rss={'sourceId':'cnbc_public','title':'CPI hotter than expected; stocks fall on rate hike fears',
        'publishedAt':'2026-10-14T13:00:00Z','firstDetectedAt':'2026-10-14T13:05:00Z',
        'canonicalUrl':'https://www.cnbc.com/synthetic-cpi.html','fullText':'must not survive'}
    c=material.news_context(row(),[],now_iso=NOW,intel_items=[rss])
    assert c['articles'][0]['scope']=='PUBLIC_HEADLINE_ONLY' and c['articles'][0]['facts']==[]
    assert 'fullText' not in json.dumps(c) and 'must not survive' not in json.dumps(c)
    assert c['reportedComparison']=='ABOVE_CONSENSUS'
    assert not material.news_context(row(),[],now_iso=NOW,intel_items=[{**rss,'firstDetectedAt':None}])['articles']
    assert not material.news_context(row(),[],now_iso=NOW,intel_items=[{**rss,'sourceId':'unregistered'}])['articles']


def test_source_correction_changes_news_digest_and_actual_or_original_are_not_modified():
    a=article();before=copy.deepcopy(a);c=material.news_context(row(),[a],now_iso=NOW)
    a['facts']=['訂正：CPIの予想比較は未確定。'];a['consensusEvidence']=None
    assert material.news_context(row(),[a],now_iso=NOW)['sourceDigest']!=c['sourceDigest']
    assert before['facts'][0].startswith('ガソリン')


def test_important_released_event_leads_for_48_hours_then_returns_to_existing_order():
    import argus_important_events as events
    from datetime import datetime
    now=datetime.fromisoformat(NOW.replace('Z','+00:00')).timestamp()
    def key(age, tier='NOW'):
        return events.canonical_rank_key(tier=tier,importance='high',owner_relevance='normal',
            event_epoch=now-age,now_epoch=now,result_available=True,event_id='synthetic')
    assert key(24*3600)<key(-3600) and key(48*3600,'RECENT')<key(-3600)
    assert key(-3600)<key(48*3600+1,'RECENT')


def test_rfc_publication_metadata_is_admitted_but_unknown_timezone_or_query_link_is_not_exported():
    rss={'sourceId':'cnbc_public','title':'CPI hotter than expected',
        'publishedAt':'Wed, 14 Oct 2026 13:00:00 +0000','firstDetectedAt':'2026-10-14T13:05:00Z',
        'canonicalUrl':'https://www.cnbc.com/synthetic-cpi.html?token=not-for-export'}
    c=material.news_context(row(),[],now_iso=NOW,intel_items=[rss])
    assert len(c['articles'])==1 and c['articles'][0]['sourceUrl'] is None
    assert 'not-for-export' not in json.dumps(c)
    rss['publishedAt']='Wed, 14 Oct 2026 13:00:00'
    assert material.news_context(row(),[],now_iso=NOW,intel_items=[rss])['articles']==[]


def test_explicit_wrong_reference_month_is_not_attached_to_current_release():
    r=row();r['actual']['metrics']['referenceMonth']='2026-09'
    a=article();a.update(headlineJa='8月の米CPIの報道',facts=[])
    assert material.news_context(r,[a],now_iso=NOW)['articles']==[]


def test_real_event_projection_and_existing_natural_post_path_share_received_news_without_extra_generation(monkeypatch):
    import argus_macro_event_analysis as analysis
    r=row();r.update(pre={'argusScenarioJa':'合成の事前シナリオ','generatedAt':'2026-10-14T10:00:00Z'},
        post={'verdict':'partial','generatedAt':'2026-10-14T13:00:00Z','answerCheckJa':'以前の説明'})
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS',{r['eventId']:copy.deepcopy(r)})
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS_STATE',{'restored':True})
    monkeypatch.setattr(scanner,'_INTEL_STORE',[])
    monkeypatch.setattr(scanner,'_NEWS_INTEL',{'events':{'news':article()}})
    monkeypatch.setattr(scanner,'_macro_analysis_restore_once',lambda:None)
    monkeypatch.setattr(scanner,'_macro_analysis_persist',lambda:None)
    monkeypatch.setattr(scanner,'_macro_important_events',lambda limit:[r])
    monkeypatch.setattr(scanner,'_macro_market_context_ja',lambda:'')
    monkeypatch.setattr(scanner,'_next_fomc_after',lambda day:None)
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:NOW)
    calls=[]
    def prose(prompt,**kwargs):
        calls.append(prompt)
        assert '受領した関連報道' in prompt and '利上げ警戒' in prompt
        assert '長期金利上昇と区別' in prompt and '下落の引き金の実証ではない' in prompt
        return {'verdict':'partial','answerCheckJa':'合成の照合','marketReadingJa':'報道では利上げ警戒による株安。','generatedAt':NOW}
    monkeypatch.setattr(scanner,'_openai_prose',prose)
    result=scanner._generate_macro_event_analysis_locked()
    assert result['post']==1 and len(calls)==1
    saved=scanner._MACRO_ANALYSIS[r['eventId']]
    context=scanner._event_news_context_cached(r,now_iso=NOW)
    assert saved['post']['newsContextSha256']==context['sourceDigest']
    assert saved['post']['newsContext']==context
    assert any(x['analysis'].get('answerCheckJa')=='以前の説明' for x in saved['analysisRevisions'])
    assert scanner._generate_macro_event_analysis_locked()['post']==0 and len(calls)==1
    projected=scanner._macro_event_display_record(saved)
    assert projected['newsContext']['reportedComparison']=='ABOVE_CONSENSUS'
    assert projected['newsContext']['storyStatus']=='REPORTED_CONTEXT_PRESENT'


def test_opposite_reported_story_does_not_inherit_the_requested_oil_hike_selloff_scenario():
    a=article();a.update(headlineJa='米CPI下振れで株高',facts=['CPI鈍化で利下げ観測が強まり株価上昇との報道。'],
        consensusEvidence={'comparisonDirection':'BELOW_CONSENSUS'})
    c=material.news_context(row(),[a],now_iso=NOW)
    assert c['storyStatus']=='REPORTED_CONTEXT_PRESENT' and c['reportedComparison']=='BELOW_CONSENSUS'
    assert c['requestedCpiStoryAudit']['allLinksReported'] is False
    assert c['causalAttributionVerified'] is False


def test_other_events_have_reported_context_without_an_oil_or_cpi_requirement():
    a=article();a.update(headlineJa='米雇用統計で利下げ観測が後退',facts=['米雇用統計後に株価下落との報道。'])
    c=material.news_context(row('NFP'),[a],now_iso=NOW)
    assert c['storyStatus']=='REPORTED_CONTEXT_PRESENT' and c['requestedCpiStoryAudit'] is None


def test_another_countrys_release_is_not_joined_to_the_us_cpi():
    a=article();a.update(headlineJa='日本のCPIが上昇',facts=['日本の消費者物価指数の公表'])
    assert material.news_context(row(),[a],now_iso=NOW)['articles']==[]


@pytest.mark.parametrize('code,title',[('ISM','米ISM後に株安'),('RETAIL_SALES','米小売売上を受け株高'),('TREASURY_AUCTION','米国債入札後に株安')])
def test_other_scheduled_event_families_share_the_news_reading_path(code,title):
    a=article();a.update(headlineJa=title,facts=[title],consensusEvidence=None)
    c=material.news_context(row(code),[a],now_iso=NOW)
    assert c['articles'] and c['storyStatus']=='REPORTED_CONTEXT_PRESENT'
    assert c['requestedCpiStoryAudit'] is None and c['reportedComparison']=='UNAVAILABLE'


def test_article_order_uses_instants_not_offset_text_and_preserves_original_receipt():
    a=article();a.update(eventId='newer',source='新しい報道',sourceReceivedAt='2026-10-15T00:30:00Z',sourcePublishedAt='2026-10-14T23:00:00Z')
    b={**a,'eventId':'older','source':'古い報道','sourceReceivedAt':'2026-10-15T09:00:00+09:00'}
    c=material.news_context(row(),[b,a],now_iso=NOW)
    assert c['articles'][0]['source']=='新しい報道'
    assert c['articles'][1]['receivedAt']=='2026-10-15T09:00:00+09:00'


def test_future_processed_analysis_is_not_borrowed_at_earlier_cutoff():
    a=article();a['processedAt']='2026-10-15T03:00:00Z'
    assert material.news_context(row(),[a],now_iso=NOW)['articles']==[]


def test_same_month_of_wrong_year_is_not_reused_but_current_and_previous_month_comparison_is_allowed():
    r=row();r['actual']['metrics']['referenceMonth']='2026-09'
    a=article();a.update(headlineJa='2025年9月の米CPI報道',facts=[])
    assert material.news_context(r,[a],now_iso=NOW)['articles']==[]
    a['headlineJa']='2026年9月の米CPIと8月の米CPIを比較'
    assert len(material.news_context(r,[a],now_iso=NOW)['articles'])==1



@pytest.mark.parametrize('response',[None,{}, {'verdict':'hit'}])
def test_new_article_with_failed_ai_keeps_saved_explanation_and_its_original_input(monkeypatch,response):
    r=row();r.update(pre={'argusScenarioJa':'合成の事前記録'},post={'verdict':'partial',
        'generatedAt':'2026-10-14T13:00:00Z','answerCheckJa':'保存済みの説明','newsContextSha256':'prior-input'})
    original=copy.deepcopy(r)
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS',{r['eventId']:r})
    monkeypatch.setattr(scanner,'_MACRO_ANALYSIS_STATE',{'restored':True})
    monkeypatch.setattr(scanner,'_macro_analysis_restore_once',lambda:None)
    monkeypatch.setattr(scanner,'_macro_analysis_persist',lambda:None)
    monkeypatch.setattr(scanner,'_macro_important_events',lambda limit:[r])
    monkeypatch.setattr(scanner,'_macro_market_context_ja',lambda:'')
    monkeypatch.setattr(scanner,'_event_news_context_cached',lambda *a,**k:{'articles':[article()],'sourceDigest':'new-input'})
    monkeypatch.setattr(scanner,'_next_fomc_after',lambda day:None)
    monkeypatch.setattr(scanner,'_ai_now_iso',lambda:NOW)
    monkeypatch.setattr(scanner,'_openai_prose',lambda *a,**k:response)
    result=scanner._generate_macro_event_analysis_locked()
    assert result['post']==0 and scanner._MACRO_ANALYSIS[r['eventId']]==original
    assert result['events'][r['eventId']]['outcome']=='kept_previous_post'
    assert result['events'][r['eventId']]['reason']=='empty_post_response'



def test_result_and_received_news_reach_same_position_and_unified_facts_without_old_reaction_masking():
    import argus_market_position_memory as m
    record=row();context=material.news_context(record,[article()],now_iso=NOW)
    materials=selected(record);contexts={materials[0]['eventId']:context}
    facts=material.context_facts(materials,contexts)
    assert facts and all(f['source']=='macro_release_news' and f['verification']=='CORROBORATED' for f in facts)
    assert all(f['provenance']['causalAttributionVerified'] is False for f in facts)
    memory=m.empty()
    m.append(memory,m._entry('US_POLICY_RATE','RELEASE_REACTION','2026-10-01T12:35:00Z','前の材料の反応',
        ref={'sourceTimeValidation':'source-time-v2','hasComparableMoves':True}))
    original=copy.deepcopy((record,context))
    added=m.ingest_macro_materials(memory,materials,contexts)
    assert added==2 and m.ingest_macro_materials(memory,materials,contexts)==0
    position=m.snapshot(memory,now_iso=NOW)
    theme=position['themes'][0]
    assert theme['recent'][0]['kind']=='NEWS_CONTEXT'
    assert '前の材料の反応' not in m.explanation_facts(position)[0]['text']
    assert context['articles'][0]['headline'] in m.explanation_facts(position)[0]['text']
    assert m.explanation_facts(position)[0]['verification']=='CORROBORATED'
    assert (record,context)==original
    composed=brief.compose_brief(now_iso=NOW,released_events=materials);composed['facts'].extend(facts)
    changed=copy.deepcopy(composed);changed['facts'][-1]['text']+='訂正'
    assert scanner._market_brief_urgent_signature(composed)!=scanner._market_brief_urgent_signature(changed)



def test_unified_ai_may_disagree_with_story_but_cannot_ignore_received_reporting():
    context={'facts':[{'evidenceId':'official','source':'official_macro_result','priority':'P0'},
        {'evidenceId':'report','source':'macro_release_news','priority':'P0'}]}
    summary={'sections':{'reasons':{'textJa':'CPIは重要です。','evidenceIds':['official']}}}
    diagnostic={};assert material.checked_coverage(summary,context,diagnostic) is None
    assert diagnostic['reason']=='important_macro_reporting_omitted'
    summary['sections']['reasons']={'textJa':'CPIと報道を照合しましたが、株安の主因かは未確認です。',
        'evidenceIds':['official','report']}
    assert material.checked_coverage(summary,context,{})==summary



def test_same_code_and_receipt_do_not_join_news_to_another_months_event():
    current=row();older=copy.deepcopy(current);older['eventId']='other-month'
    older['eventTimeUtc']='2026-09-11T12:30:00Z';older['eventDate']='2026-09-11'
    materials=selected(current)
    assert material.source_record(materials[0],[older,current]) is current
    assert material.source_record(materials[0],[older]) is None
    assert current['actual']['receivedAt']==older['actual']['receivedAt']


def test_one_article_stays_one_entry_when_another_joins_the_release():
    """Audit 2026-10-17: the entry carried the digest of the whole context, so
    a second article rewrote the first one as a new entry."""
    import argus_market_position_memory as m
    record=row();context=material.news_context(record,[article()],now_iso=NOW)
    materials=selected(record);eid=materials[0]['eventId']
    memory=m.empty()
    assert m.ingest_macro_materials(memory,materials,{eid:context})==2
    grown={**context,'articles':[*context['articles'],{**context['articles'][0],'headline':'別の記事',
        'sourceRefSha256':'b'*64}],'sourceDigest':'changed'}
    assert m.ingest_macro_materials(memory,materials,{eid:grown})==1
    texts=[r['textJa'] for r in memory['entries'] if r['kind']=='NEWS_CONTEXT']
    assert len(texts)==len(set(texts))==2
    # An entry written before the per-article identity is not written again.
    legacy=m.empty()
    old=m._entry(m.theme_for_event_code('CPI'),'NEWS_CONTEXT',context['articles'][0]['receivedAt'],
        context['articles'][0]['source']+': '+' / '.join([context['articles'][0]['headline'],*context['articles'][0].get('facts',[])]),
        severity='HIGH',ref={'source':'macro_release_news','eventId':eid,'scope':context['articles'][0]['scope'],
            'sourceRowSha256':context['sourceDigest'],'url':context['articles'][0].get('sourceUrl')})
    m.append(legacy,old)
    m.ingest_macro_materials(legacy,materials,{eid:context})
    assert sum(1 for r in legacy['entries'] if r['kind']=='NEWS_CONTEXT')==1


def test_a_row_without_a_readable_time_does_not_stop_the_snapshot():
    import argus_market_position_memory as m
    memory=m.empty()
    m.append(memory,m._entry('US_POLICY_RATE','NEWS','2026-10-01T12:35:00Z','読める行',ref={'eventId':'a'}))
    memory['entries'].append({**memory['entries'][0],'entryId':'mpm-broken','at':None})
    position=m.snapshot(memory,now_iso=NOW)
    assert position['themes']

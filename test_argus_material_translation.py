"""Paid translation is selected by server evidence, not views or refill traffic."""
import ast
from pathlib import Path
from types import SimpleNamespace
import re
import time
import argus_news_i18n as i18n
import argus_news_intelligence as intel


def host():
    source = ast.parse(Path(__file__).with_name('scanner.py').read_text())
    names = {'_intel_translate_titles', '_news_visible_pool', '_translate_pending_headlines', 'get_market_news'}
    nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    calls = []
    ns = dict(time=time, argus_news_i18n=i18n, argus_news_intelligence=intel,
        _NEWS_INTEL={'events':{}}, _NEWS_JA_CACHE={}, _NEWS_JA_FAILED={}, _NEWS_JA_VQUEUE={},
        _NEWS_JA_VQUEUE_STATE={}, _NEWS_JA_STATE={}, _NEWS_JA_SEEN=['Browser-only headline'],
        _INTEL_STORE=[], _FINN_CACHE={}, _MARKET_NEWS_CACHE={'data':None,'expires':0},
        _news_ja_restore_once=lambda:None, _news_ja_persist=lambda:None,
        _ai_now_iso=lambda:'2026-09-19T05:00:00Z',
        _decision_news_row=lambda row, **kw:row if row.get('fresh', True) else None,
        _translate_headlines_ja=lambda rows:(calls.append(rows), {i:'重要な市場材料' for i in range(len(rows))})[1])
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<translation-lanes>', 'exec'), ns)
    return ns, calls


def test_browser_queue_cannot_purchase_unselected_translation_and_cache_reused():
    ns, calls = host()
    now = time.time()
    from datetime import datetime, timezone
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
    ns['_NEWS_INTEL']['events'] = {
        'important':{'severity':'HIGH','sourceReceivedAt':stamp,'titleOriginal':'Central bank raises interest rates'},
        'routine':{'severity':'INFO','sourceReceivedAt':stamp,'titleOriginal':'Routine corporate roundup'},
        'undated':{'severity':'CRITICAL','titleOriginal':'Unknown publication time'},
        'old':{'severity':'HIGH','sourceReceivedAt':'2020-01-01T00:00:00Z','titleOriginal':'Old policy decision'}}
    i18n.visible_queue_add(ns['_NEWS_JA_VQUEUE'], [{'titleOriginal':'Browser-only headline',
        'severity':'CRITICAL','source':'browser'}], {}, context='today', now_iso=stamp)
    first = ns['_translate_pending_headlines'](queue_first=True)
    assert calls == [['Central bank raises interest rates']]
    assert first['translated']==1 and first['fromQueue']==0
    ns['_translate_pending_headlines'](queue_first=True)
    assert len(calls)==1
    assert ns['_NEWS_INTEL']['events']['routine']['severity']=='INFO'


def test_market_priority_requires_freshness_and_relevance():
    ns, calls = host()
    ns['_MARKET_NEWS_CACHE']['data']={'items':[
        {'headline':'Rate decision moves bonds','major':True,'relevant':True},
        {'headline':'Old rate decision','major':True,'relevant':True,'fresh':False},
        {'headline':'Routine earnings report','major':False,'relevant':True},
        {'headline':'Unrelated conflict report','major':True,'relevant':False}]}
    ns['_translate_pending_headlines']()
    assert calls == [['Rate decision moves bonds']]


def test_institutional_collection_reuses_cache_without_paid_calls():
    ns, calls = host()
    ns['_INTEL_STORE']=[{'institutionId':'official','title':'Published policy decision'},
                        {'institutionId':'official','title':'Unselected English report'}]
    ns['_NEWS_JA_CACHE'][i18n.text_hash('Published policy decision')]={'ja':'公表済みの政策決定','at':'2026-09-19T05:00:00Z'}
    ns['_intel_translate_titles']()
    assert not calls
    assert ns['_INTEL_STORE'][0]['titleJa']=='公表済みの政策決定'
    assert 'titleJa' not in ns['_INTEL_STORE'][1]


def test_market_refill_never_calls_translation_provider():
    ns, calls=host()
    title='Central bank raises interest rates'
    ns.update(FINNHUB_API_KEY='test-key', _MARKET_NEWS_TTL=600,
        _NEWS_MAJOR_RE=re.compile('rates'), _news_source_tier=lambda source:'wire',
        _news_relevant=lambda *a:True, _intel_link_assets=lambda *a:[],
        _annotate_news_corroboration=lambda rows:None,
        _market_news_snapshot_reaged=lambda snapshot, **kw:snapshot,
        requests=SimpleNamespace(get=lambda *a,**kw:SimpleNamespace(
            raise_for_status=lambda:None,json=lambda:[{'headline':title,'source':'wire','datetime':time.time()}])))
    ns['_NEWS_JA_CACHE'][i18n.text_hash(title)]={'ja':'中央銀行が利上げ','at':'2026-09-19T05:00:00Z'}
    for _ in range(2):
        ns['_MARKET_NEWS_CACHE']['expires']=0
        result=ns['get_market_news']()
        assert result['items'][0]['headlineJa']=='中央銀行が利上げ'
    assert not calls

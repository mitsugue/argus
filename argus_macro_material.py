"""Cache-only official results shared by the brief and news presentation.

These are result records, not received articles or proof of market causality.
The original result/revision store remains the only source of persistence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from urllib.parse import urlsplit

import argus_macro_results

_CODES = {
    'CPI': ('米CPI', 'INFLATION_RATES'), 'PPI': ('米PPI', 'INFLATION_RATES'),
    'PCE': ('米PCE物価', 'INFLATION_RATES'), 'NFP': ('米雇用統計', 'LABOR_MARKET'),
    'JOLTS': ('米求人統計', 'LABOR_MARKET'), 'GDP': ('米GDP', 'GROWTH'),
    'FOMC': ('米金融政策', 'MONETARY_POLICY'), 'BOJ': ('日銀金融政策', 'MONETARY_POLICY'),
}
_HOSTS = {'www.bls.gov', 'bls.gov', 'www.bea.gov', 'bea.gov',
          'www.federalreserve.gov', 'federalreserve.gov', 'fred.stlouisfed.org',
          'www.boj.or.jp', 'boj.or.jp'}


def _at(value):
    try:
        out = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return out if out.tzinfo else None
    except ValueError:
        return None


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _impact(code, actual):
    """A qualified transmission channel, never an observed price attribution."""
    if code == 'CPI':
        current = (actual.get('metrics') or {}).get('headlineCpiYoY')
        previous = (actual.get('previousMetrics') or {}).get('headlineCpiYoY')
        if _finite(current) and _finite(previous):
            if current > previous:
                return '総合の前年比は前回より拡大。金融引締め警戒は高PER株の重荷になり得ます。'
            if current < previous:
                return '総合の前年比は前回より鈍化。金利低下期待は株式の支えになり得ます。'
    return '株式への波及は、結果と政策金利見通し・為替の変化を合わせて確認します。'


def material_id(source_event_id):
    return 'macro-result-' + hashlib.sha256(str(source_event_id).encode()).hexdigest()[:32]


def source_record(material, records):
    """The originating event identity, never code/receipt coincidence."""
    return next((r for r in records if material_id(r.get('eventId')) == material.get('eventId')), None)


def released_materials(records, *, now_iso, history=False):
    """Eligible received results, bounded by schedule AND receipt, not fetch-now.

    Recent results stay prominent for 48 hours; the existing history reader may
    show seven days. Future, unreceived, unknown-source or missing results never
    acquire importance through a title alone. Corrections retain their identity
    and bind new content to a new digest; no original row is modified.
    """
    now = _at(now_iso)
    if now is None:
        return []
    selected = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('eventId'), str):
            continue
        code = record.get('eventCode')
        if code not in _CODES or record.get('displayImpact') not in ('high', 'critical'):
            continue
        raw_actual = record.get('actual') or {}
        raw_receipt, raw_available = _at(raw_actual.get('receivedAt')), _at(raw_actual.get('availableFrom'))
        if raw_receipt is None or raw_available is None or not raw_receipt <= raw_available <= now:
            continue
        actual = argus_macro_results.project_series_timing(raw_actual)
        actual['availableFrom'] = raw_actual['availableFrom']
        event_at, receipt = _at(record.get('eventTimeUtc')), _at(actual.get('receivedAt'))
        available = _at(actual.get('availableFrom'))
        if (actual.get('available') is not True or event_at is None or receipt is None
                or available is None or not event_at <= receipt <= available <= now):
            continue
        if (now - event_at).total_seconds() > (7 * 86400 if history else 48 * 3600):
            continue
        if code == 'CPI' and actual.get('referenceMatched') is not True:
            continue
        url = actual.get('sourceUrl')
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.hostname not in _HOSTS
                    or parsed.username or parsed.password):
                continue
        except (TypeError, ValueError):
            continue
        headline = actual.get('headline')
        metrics = actual.get('metrics') or {}
        if not isinstance(headline, str) or not headline.strip() or not any(_finite(v) for v in metrics.values()):
            continue
        label, family = _CODES[code]
        result = headline.replace('消費者物価指数 ', '').replace('（季節調整済み）', '').replace('（季節調整なし）', '')
        content = {'eventId': record.get('eventId'), 'actual': actual,
                   'actualRevisionId': record.get('actualRevisionId')}
        try:
            digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        except (ValueError, TypeError):
            continue
        event_id = material_id(record.get('eventId'))
        row = {
            'schemaVersion': 'argus-news-event-v1', 'eventId': event_id, 'revision': 1,
            'eventCode': code, 'materialOrigin': 'OFFICIAL_MACRO_RESULT',
            'source': {'BLS': '米労働統計局', 'FRED/BEA': '米経済分析局/FRED', 'FRED/Fed': 'FRB/FRED'}.get(actual.get('source'), actual.get('source')),
            'sourceLabelJa': actual.get('source'),
            'sourceFamily': 'OFFICIAL_MACRO', 'sourceTier': 'official',
            'sourceReceivedAt': actual['receivedAt'], 'sourcePublishedAt': None,
            'processedAt': actual['availableFrom'], 'sourceUrl': url,
            'sourceFingerprint': digest, 'sourceRowSha256': digest,
            'headlineJa': f'{label} 結果: {result}'[:160], 'titleOriginal': f'{label} 結果: {result}'[:160],
            'displayTitleJa': f'{label} 結果: {result}'[:160], 'translationStatus': 'not_needed',
            'eventType': family, 'themeTags': [family], 'facts': [result[:160]],
            'staleness': 'STALE' if (now - event_at).total_seconds() > 48 * 3600 else 'RECENT',
            'severity': 'HIGH', 'severityReasons': ['RECEIVED_IMPORTANT_OFFICIAL_RESULT'],
            'confirmationState': 'MARKET_CONFIRMATION_PENDING', 'consensusEvidence': None,
            'whyJa': _impact(code, actual),
            'japanImpactJa': '市場予想との差と日経下落への寄与は未確認。結果の重要性と、値動きの原因は分けて判断します。',
            'marketReadings': [], 'analysisState': 'OFFICIAL_RESULT_RECEIVED',
            'analysisInputScope': 'OFFICIAL_RESULT_ONLY', 'alertEligible': False,
            'backfill': False, 'eventMemory': None, 'sdaAuthority': False,
            'authority': 'NEWS_RISK_EVIDENCE',
        }
        identity = (code, record.get('eventDate') or event_at.date().isoformat())
        prior = selected.get(identity)
        if prior is None or available > _at(prior['processedAt']):
            selected[identity] = row
    return sorted(selected.values(), key=lambda row: row['sourceReceivedAt'], reverse=True)[:8]


def checked_coverage(summary, context, diagnostic):
    """Reject a new edition that silently skips its leading official result.

    Retained editions keep their original text and timestamp. No assertion about
    market direction is required; an explicitly unknown effect is a valid result.
    """
    if not summary:
        return summary
    required = [f for f in context.get('facts', []) if f.get('source') == 'official_macro_result'
                and f.get('priority') == 'P0'][:1]
    sections = (summary.get('sections') or {})
    cited = {ref for key in ('view', 'reasons') for ref in (sections.get(key) or {}).get('evidenceIds', [])}
    if any(f.get('evidenceId') not in cited for f in required):
        diagnostic.update(status='REJECTED', reason='important_macro_result_omitted', section='reasons')
        return None
    reporting = [f for f in context.get('facts', []) if f.get('source') == 'macro_release_news'
                 and f.get('priority') == 'P0']
    if reporting and not any(f.get('evidenceId') in cited for f in reporting):
        diagnostic.update(status='REJECTED', reason='important_macro_reporting_omitted', section='reasons')
        return None
    return summary


_EVENT_TERMS = {
    'CPI': r'(?<![A-Za-z])CPI(?![A-Za-z])|消費者物価|consumer price',
    'PPI': r'(?<![A-Za-z])PPI(?![A-Za-z])|生産者物価|producer price',
    'PCE': r'(?<![A-Za-z])PCE(?![A-Za-z])|個人消費支出',
    'NFP': r'雇用統計|nonfarm|payrolls|employment situation',
    'JOLTS': r'JOLTS|求人件数|job openings', 'GDP': r'(?<![A-Za-z])GDP(?![A-Za-z])',
    'FOMC': r'FOMC|米連邦公開市場|Fed rate decision', 'BOJ': r'日銀|日本銀行|Bank of Japan',
    'ISM': r'(?<![A-Za-z])ISM(?![A-Za-z])|供給管理協会',
    'RETAIL_SALES': r'小売売上|retail sales',
    'TREASURY_AUCTION': r'米国債入札|米国債の入札|Treasury auction',
    'AUCTION': r'米国債入札|米国債の入札|Treasury auction',
}
_COMPARE = {'ABOVE_CONSENSUS': r'市場予想を上回|予想上回|above (?:expectations|consensus)|hotter than expected',
            'BELOW_CONSENSUS': r'市場予想を下回|予想下回|below (?:expectations|consensus)|cooler than expected',
            'IN_LINE': r'市場予想(?:通り|どおり)|in line with (?:expectations|consensus)'}


def _matches_event(code, text):
    if not re.search(_EVENT_TERMS[code],text,re.I):return False
    # A different country's release is not the US event merely because both
    # headlines contain CPI/NFP. Mixed-country comparison needs a finer join.
    if code in ('CPI','PPI','PCE','NFP','JOLTS','GDP') and re.search(
            r'(?:日本|中国|英国|欧州|ユーロ圏).{0,8}(?:CPI|PPI|GDP|消費者物価|生産者物価|雇用統計)',text,re.I):
        return False
    return True


def _news_at(value):
    parsed = _at(value)
    if parsed is not None:return parsed
    from email.utils import parsedate_to_datetime
    try:
        parsed = parsedate_to_datetime(str(value))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):return None


def _article_url(value):
    try:
        parsed=urlsplit(value)
        return value if parsed.scheme=='https' and parsed.hostname and '.' in parsed.hostname and not (
            parsed.query or parsed.fragment or parsed.username or parsed.password) else None
    except (ValueError, TypeError):return None


def news_context(record, news_events, *, now_iso, intel_items=(), headline_translations=None):
    """Read existing, time-bounded news, without turning reporting into causality.

    Mail contributes its already validated short facts. Public RSS contributes
    permitted headline metadata only. No article body, new lookup or model call.
    A same-day topic match is a release-window association, not historical PIT.
    """
    import argus_research_mesh as mesh
    import argus_news_i18n as i18n
    translations=headline_translations or {}
    code=record.get('eventCode');at=_at(record.get('eventTimeUtc'));now=_at(now_iso)
    empty={'schemaVersion':'macro-news-context-v1','articles':[], 'comparisonJa':'市場予想と比べる記事根拠は未受領',
           'reportedComparison':'UNAVAILABLE','storyCoverage':{},'causalAttributionVerified':False}
    if code not in _EVENT_TERMS or at is None or now is None or not 0 <= (now-at).total_seconds() <= 48*3600:
        return empty
    candidates=[]
    for row in news_events:
        if row.get('materialOrigin')=='OFFICIAL_MACRO_RESULT' or row.get('sourceTier')!='trusted_subscription':
            continue
        received=_at(row.get('sourceReceivedAt'));published=_at(row.get('sourcePublishedAt'));processed=_at(row.get('processedAt'))
        if received is None or not at <= received <= now or (published and not at <= published <= now):
            continue
        if row.get('processedAt') and (processed is None or not received<=processed<=now):continue
        headline=str(row.get('headlineJa') or row.get('titleOriginal') or '')[:160]
        facts=[v for v in (row.get('facts') or []) if isinstance(v,str) and 0<len(v)<=200][:3]
        if not _matches_event(code,headline+' '+ ' '.join(facts)):continue
        candidates.append({'source':str(row.get('source') or row.get('sourceFamily') or '')[:40],
            'headline':headline,'facts':facts,'receivedAt':row['sourceReceivedAt'],
            'publishedAt':row.get('sourcePublishedAt'),'scope':'RECEIVED_NEWS_ANALYSIS',
            'identity':str(row.get('eventId') or row.get('sourceFingerprint') or ''),
            'comparison':(row.get('consensusEvidence') or {}).get('comparisonDirection'),
            'sourceUrl':_article_url(row.get('sourceUrl'))})
    for row in intel_items:
        source_id=row.get('sourceId');rights=mesh.SOURCE_RIGHTS.get(source_id) or {}
        if rights.get('accessClass')!='PUBLIC_METADATA' or rights.get('kind')!='news':continue
        pub=_news_at(row.get('publishedAt'));received=_news_at(row.get('firstDetectedAt') or row.get('fetchedAt'))
        if pub is None or received is None or not at<=pub<=received<=now:continue
        headline=str(row.get('titleJa') or (translations.get(i18n.text_hash(str(row.get('title') or ''))) or {}).get('ja') or row.get('title') or '')[:160]
        if not _matches_event(code,headline):continue
        comparisons=[key for key,pat in _COMPARE.items() if re.search(pat,headline,re.I)]
        candidates.append({'source':{'bloomberg_public':'Bloomberg','cnbc_public':'CNBC','nikkei_web':'日本経済新聞','marketwatch_public':'MarketWatch','nasdaq_public':'Nasdaq','nhk_business':'NHK'}.get(source_id,str(source_id))[:40],'headline':headline,'facts':[],
            'receivedAt':received.isoformat(),'publishedAt':pub.isoformat(),'scope':'PUBLIC_HEADLINE_ONLY',
            'identity':str(row.get('itemId') or row.get('canonicalUrl') or headline),
            'comparison':comparisons[0] if len(comparisons)==1 else None,
            'sourceUrl':_article_url(row.get('canonicalUrl'))})
    candidates.sort(key=lambda row:_news_at(row['receivedAt']).timestamp(),reverse=True)
    articles=[];seen=set()
    for row in candidates:
        text=row['headline']+' '+' '.join(row['facts'])
        # An explicitly different reference month cannot be joined by receipt day.
        expected=((record.get('actual') or {}).get('metrics') or {}).get('referenceMonth')
        months=re.findall(r'(?<![0-9])([1-9]|1[0-2])月(?:の)?(?:米|米国)?(?:CPI|消費者物価)',text,re.I)
        if expected and (not isinstance(expected,str) or not re.fullmatch(r'[0-9]{4}-(?:0[1-9]|1[0-2])',expected)):continue
        years_months=re.findall(r'([12][0-9]{3})年(0?[1-9]|1[0-2])月(?:の)?(?:米|米国)?(?:CPI|消費者物価)',text,re.I)
        if expected and years_months and expected not in {f'{y}-{int(m):02d}' for y,m in years_months}:continue
        if expected and months and int(expected[5:7]) not in {int(m) for m in months}:continue
        identity=hashlib.sha256(row.pop('identity').encode()).hexdigest()
        if identity in seen:continue
        seen.add(identity);row['sourceRefSha256']=identity
        if row['scope']=='PUBLIC_HEADLINE_ONLY' and not re.search(r'[ぁ-んァ-ヶ一-龯]',row['headline']):
            row['titleOriginal']=row['headline']
            row['headline']=_CODES.get(code,(code,None))[0]+'の公開見出し（日本語訳は未受領）'
        row['claims']={
            'energyInflation':bool(re.search(r'原油|ガソリン|エネルギー|oil|gasoline',text,re.I)
                and re.search(r'物価|インフレ|inflation|CPI',text,re.I)
                and re.search(r'押し上げ|押上げ|寄与|背景|driv|boost|fuel',text,re.I)),
            'rateExpectations':bool(re.search(r'利上げ(?:観測|警戒|懸念|確率)|(?:利上げ|金利上昇).{0,12}(?:観測|警戒|懸念)|rate.hike.{0,12}(?:fear|bet|expect)',text,re.I)),
            'equitySelling':bool(re.search(r'株安|株.{0,15}下落|売り優勢|stocks.{0,15}(?:fell|fall|drop)',text,re.I)),
            'marketExplanation':bool(re.search(r'株(?:高|安)|株.{0,15}(?:上昇|下落)|(?:利上げ|利下げ|金利).{0,15}(?:観測|懸念|警戒|後退)|ドル円.{0,15}(?:上昇|下落)|stocks.{0,15}(?:fell|fall|drop|rise|rally)|rate.(?:hike|cut).{0,12}(?:fear|bet|expect)',text,re.I)),
        }
        articles.append(row)
        if len(articles)==3:break
    directions={r['comparison'] for r in articles if r['comparison'] in _COMPARE}
    direction=next(iter(directions)) if len(directions)==1 else ('MIXED' if directions else 'UNAVAILABLE')
    label={'ABOVE_CONSENSUS':'一部項目は市場予想上振れとの報道', 'BELOW_CONSENSUS':'一部項目は市場予想下振れとの報道',
           'IN_LINE':'市場予想並みとの報道', 'MIXED':'予想比較の方向が混在・項目別に確認が必要'}.get(direction,empty['comparisonJa'])
    if directions:label+='（項目別の予想値・数値差は未照合）'
    coverage={key:any(r['claims'][key] for r in articles) for key in ('energyInflation','rateExpectations','equitySelling')}
    out={**empty,'articles':articles,'comparisonJa':label,'reportedComparison':direction,'storyCoverage':coverage,
         'associationBasis':'SAME_RELEASE_WINDOW_REPORTING','quantitativeSurpriseVerified':False,
         'storyStatus':'REPORTED_CONTEXT_PRESENT' if any(r['claims']['marketExplanation'] for r in articles) else 'ARTICLE_EVIDENCE_INCOMPLETE',
         'requestedCpiStoryAudit':({'energyInflation':coverage['energyInflation'],'rateExpectations':coverage['rateExpectations'],
             'equitySelling':coverage['equitySelling'],'allLinksReported':all(coverage.values())} if code=='CPI' else None)}
    out['sourceDigest']=hashlib.sha256(json.dumps(out,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return out



def context_facts(materials, contexts):
    """Bounded received reporting for the same result, never a causal verdict."""
    facts=[]
    for material in materials[:1]:
        context=contexts.get(material['eventId']) or {}
        for article in (context.get('articles') or [])[:3]:
            text=' / '.join([article['headline'], *article.get('facts',[])])[:300]
            facts.append({'text':f"{material['eventCode']}関連報道: {text}",
                'priority':'P0','source':'macro_release_news','verification':'CORROBORATED',
                'provenance':{'scope':'published_metadata_snapshot','reportScope':article['scope'],'sourceLabel':article['source'],
                    'eventId':material['eventId'],'revision':None,'publishedAt':article.get('publishedAt'),
                    'receivedAt':article['receivedAt'],'observedAt':None,'url':article.get('sourceUrl'),
                    'sourceRowSha256':context.get('sourceDigest'),
                    'quantitativeSurpriseVerified':False,'causalAttributionVerified':False}})
    return facts

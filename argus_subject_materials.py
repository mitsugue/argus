"""Bounded cached company evidence, without collection or model calls."""
from datetime import timedelta
from urllib.parse import urlsplit
import hashlib
import json
from datetime import datetime
from datetime import date
from zoneinfo import ZoneInfo
import math
from decimal import Decimal
import argus_research_mesh
from argus_product_naming import require_allowed


def _instant(value):
    result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('timezone_required')
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def news_facts(items, *, symbol, cutoff, limit=4):
    """Association is a search candidate, not verified company impact or cause."""
    now=_instant(cutoff);selected={}
    for item in items[:2000]:
        if (not isinstance(item,dict) or not isinstance(item.get('linkedAssets'),list)
                or symbol not in item['linkedAssets'] or not isinstance(item.get('sourceId'),str)):continue
        rights=argus_research_mesh.source_rights(item.get('sourceId'))
        if not rights['canSendToLLM'] or not rights['canRetain']:continue
        try:
            received=_instant(item['fetchedAt'])
            if not now-timedelta(days=30)<=received<=now:continue
            published=item.get('publishedAt')
            if published and not now-timedelta(days=30)<=_instant(published)<=received:continue
            url=item.get('canonicalUrl');parsed=urlsplit(url or '')
            if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password:continue
            title=item.get('title')
            if not isinstance(title,str) or not title.strip() or len(title)>500:continue
            snippet=item.get('publicSnippet') if rights['canDisplayExcerpt'] else None
            if not isinstance(snippet,str):snippet=None
            selected_input={'symbol':symbol,'sourceId':item['sourceId'],'url':url,'title':title,
                'publicSnippet':snippet[:700] if snippet else None,'publishedAt':published,'receivedAt':item['fetchedAt'],
                'updatedAt':item.get('updatedAt'),'accessClass':rights['accessClass'],
                'associationBasis':'EXISTING_COLLECTOR_LINKED_ASSET','companyImpactVerified':False,
                'fullArticleVerified':False,'officialResultVerified':False}
            require_allowed(selected_input)
            record={'text':f"{symbol}への関連候補として取得した報道見出し: {title}。"
                +(f"公開抜粋: {selected_input['publicSnippet']}。" if selected_input['publicSnippet'] else '')
                +f"出典: {item['sourceId']}。公表: {published or '不明'}。取得: {item['fetchedAt']}。",
                'source':'subject_news_metadata','priority':'P1','verification':'UNCONFIRMED','evidenceKind':'REPORTED',
                'provenance':{'scope':'cached_public_metadata','url':url,'publishedAt':published,
                    'receivedAt':item['fetchedAt'],'sourceLabel':item['sourceId'],'sourceRowSha256':_digest(selected_input)},
                'materialInput':selected_input}
            record['evidenceId']='subject-material-'+_digest(record)
            prior=selected.get(url)
            if prior is None or received>prior[0]:selected[url]=(received,record)
        except (KeyError,ValueError,TypeError):continue
    if type(limit) is not int or not 1<=limit<=4:raise ValueError('subject_news_bound')
    records=[row[1] for row in sorted(selected.values(),key=lambda row:(row[0],row[1]['evidenceId']),reverse=True)[:limit]]
    coverage={'text':f'関連報道は直近30日・最大{limit}記事の保存見出しと公開抜粋。関連付けだけでは株価変動の原因は未確定。',
        'source':'subject_material_coverage','priority':'P1','verification':'UNCONFIRMED','evidenceKind':'UNKNOWN'}
    if not records:coverage['text']='関連報道の保存材料なし。'
    coverage['evidenceId']='subject-material-'+_digest(coverage)
    return records+[coverage]


def _number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _currency(value):
    return isinstance(value,str) and len(value)==3 and value.isascii() and value.isupper() and value.isalpha()


def _number_text(value):
    # Preserve the cache's canonical decimal value; :g silently rounds at six
    # significant digits and scientific notation is unsuitable for this prose.
    number=Decimal(str(value))
    if number.is_zero():return '0'
    text=format(number,'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _yen_text(value):
    text=_number_text(value)+'円'
    number=Decimal(str(value))
    if abs(number)>=100000000:
        parts=number.as_tuple()
        scaled=Decimal((parts.sign,parts.digits,parts.exponent-8))
        text+='（'+_number_text(scaled)+'億円）'
    return text


def _day(value, *, latest):
    try:return isinstance(value,str) and date.fromisoformat(value).isoformat()==value and value<=latest
    except ValueError:return False


def earnings_facts(earnings, *, symbol, market, cutoff):
    """Use only the existing display projection, with separate actual/plan clocks.

    The selected-payload digest is not an original statement hash. Neither a
    company plan nor a vendor consensus proves the cause of a price movement.
    """
    if (market not in ('JP','US') or not isinstance(earnings,dict)
            or (earnings.get('symbol'),earnings.get('market'))!=(symbol,market)):return []
    now=_instant(cutoff)
    today=now.astimezone(ZoneInfo('Asia/Tokyo' if market=='JP' else 'America/New_York')).date().isoformat()
    selected={'symbol':symbol,'market':market,'projectionOnly':True,'priceMoveCauseVerified':False,
        'numericTextVersion':'EXACT_DECIMAL_YEN_UNITS_V1'}
    parts=[];receipts=[]
    company=earnings.get('company')
    if (market=='JP' and isinstance(company,dict) and company.get('source')=='J-Quants 決算短信'
            and company.get('currency')=='JPY' and type(company.get('consolidated')) is bool
            and _number(company.get('operatingProfit'))):
        try:
            received=_instant(company['receivedAt'])
            if received>now:raise ValueError('future_actual')
            disclosed=company.get('disclosedDate');period=company.get('periodEnd')
            receipt_day=received.astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat()
            if not (_day(disclosed,latest=receipt_day) and _day(period,latest=disclosed)):raise ValueError('actual_date')
            actual={k:company[k] for k in ('source','currency','consolidated','disclosedDate','periodEnd','operatingProfit','receivedAt')}
            scope='連結' if company['consolidated'] else '単体'
            parts.append(f"{disclosed}公表、{period}期末の{scope}累計営業利益{_yen_text(company['operatingProfit'])}。")
            fiscal=company.get('fiscalYearEnd')
            forecast=company.get('forecastOperatingProfit')
            try:
                plan_received=_instant(company['forecastReceivedAt'])
                plan_day=plan_received.astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat()
                plan_disclosed=company.get('forecastDisclosedDate')
                if (not _number(forecast) or plan_received>now or plan_received<received
                        or not _day(fiscal,latest=(now.date()+timedelta(days=370)).isoformat())
                        or fiscal<period or not _day(plan_disclosed,latest=plan_day) or plan_disclosed<disclosed):
                    raise ValueError('plan_date')
                actual.update({k:company[k] for k in ('fiscalYearEnd','forecastOperatingProfit','forecastDisclosedDate','forecastReceivedAt')})
                parts.append(f"{plan_disclosed}公表の{fiscal}期通期会社予想は営業利益{_yen_text(forecast)}。")
                receipts.append(company['forecastReceivedAt'])
            except (KeyError,ValueError,TypeError):pass
            selected['company']=actual;receipts.append(company['receivedAt'])
        except (KeyError,ValueError,TypeError):pass
    # Yahoo's accounting period end is never relabelled an announcement date.
    if earnings.get('source')=='Yahoo Finance':
        try:
            received=_instant(earnings['fetchedAt'])
            if not now-timedelta(days=30)<=received<=now:raise ValueError('vendor_time')
            vendor={};previous=earnings.get('previous');estimate=earnings.get('estimate')
            if (isinstance(previous,dict) and _day(previous.get('periodEnd'),latest=today)
                    and _number(previous.get('epsActual')) and _currency(previous.get('currency'))):
                row={k:previous[k] for k in ('periodEnd','epsActual','currency')}
                sentence=f"{row['periodEnd']}期末の実績EPS{_number_text(row['epsActual'])}{row['currency']}"
                if _number(previous.get('epsEstimate')):
                    row['epsEstimate']=previous['epsEstimate'];sentence+=f"、同期間の市場予想EPS{_number_text(row['epsEstimate'])}{row['currency']}"
                vendor['previous']=row;parts.append(sentence+'。')
            count=estimate.get('analysts') if isinstance(estimate,dict) else None
            if (isinstance(estimate,dict) and _day(estimate.get('periodEnd'),latest=(now.date()+timedelta(days=370)).isoformat())
                    and _number(estimate.get('eps')) and _currency(estimate.get('epsCurrency'))
                    and type(count) is int and 1<=count<=1000):
                row={k:estimate[k] for k in ('periodEnd','eps','epsCurrency','analysts')}
                sentence=f"{row['periodEnd']}期末の市場予想EPS{_number_text(row['eps'])}{row['epsCurrency']}、{count}人"
                if (_number(estimate.get('epsLow')) and _number(estimate.get('epsHigh'))
                        and estimate['epsLow']<=estimate['eps']<=estimate['epsHigh']):
                    row.update({k:estimate[k] for k in ('epsLow','epsHigh')});sentence+=f"、予想幅{_number_text(row['epsLow'])}〜{_number_text(row['epsHigh'])}{row['epsCurrency']}"
                if _number(estimate.get('eps30DaysAgo')):
                    row['eps30DaysAgo']=estimate['eps30DaysAgo'];sentence+=f"、30日前の予想EPS{_number_text(row['eps30DaysAgo'])}{row['epsCurrency']}"
                vendor['estimate']=row;parts.append(sentence+'。')
            if vendor:
                vendor.update(source='Yahoo Finance',receivedAt=earnings['fetchedAt']);selected['vendor']=vendor;receipts.append(earnings['fetchedAt'])
        except (KeyError,ValueError,TypeError):pass
    if not parts:return []
    require_allowed(selected)
    labels=[label for key,label in (('company','J-Quants 決算短信'),('vendor','Yahoo Finance')) if key in selected]
    record={'text':f"{market}:{symbol}の保存決算。"+''.join(parts)+'出典: '+' / '.join(labels)+'。取得: '+' / '.join(dict.fromkeys(receipts))+'。',
        'source':'subject_saved_earnings','priority':'P1','verification':'UNCONFIRMED','evidenceKind':'REPORTED',
        'provenance':{'scope':'cached_earnings_projection','receivedAt':max(receipts,key=_instant),
            'sourceLabel':' / '.join(labels),'sourceRowSha256':_digest(selected)},'materialInput':selected}
    record['evidenceId']='subject-material-'+_digest(record)
    return [record]


def saved_facts(items, *, earnings, symbol, market, cutoff):
    financial=earnings_facts(earnings,symbol=symbol,market=market,cutoff=cutoff)
    return financial+news_facts(items,symbol=symbol,cutoff=cutoff,limit=3 if financial else 4)

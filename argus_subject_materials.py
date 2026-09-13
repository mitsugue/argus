"""Bounded cached news evidence for a requested subject, without new collection."""
from datetime import timedelta
from urllib.parse import urlsplit
import hashlib
import json
from datetime import datetime
import argus_research_mesh
from argus_product_naming import require_allowed


def _instant(value):
    result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('timezone_required')
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def news_facts(items, *, symbol, cutoff):
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
                +f"出典: {item['sourceId']}。公表: {published or '不明'}。取得: {item['fetchedAt']}。"
                +'関連付けは企業への影響・価格変動の原因を確認したものではありません。記事全文・公式結果は未確認です。',
                'source':'subject_news_metadata','priority':'P1','verification':'UNCONFIRMED','evidenceKind':'REPORTED',
                'provenance':{'scope':'cached_public_metadata','url':url,'publishedAt':published,
                    'receivedAt':item['fetchedAt'],'sourceLabel':item['sourceId'],'sourceRowSha256':_digest(selected_input)},
                'materialInput':selected_input}
            record['evidenceId']='subject-material-'+_digest(record)
            prior=selected.get(url)
            if prior is None or received>prior[0]:selected[url]=(received,record)
        except (KeyError,ValueError,TypeError):continue
    records=[row[1] for row in sorted(selected.values(),key=lambda row:(row[0],row[1]['evidenceId']),reverse=True)[:4]]
    coverage={'text':'この銘柄に関連付けられた取得済みの報道を、直近30日・最大4記事の範囲で確認します。'
        +'全報道の網羅、決算予想と公式結果の照合、発表直後の価格反応はこの材料だけでは確認できません。',
        'source':'subject_material_coverage','priority':'P1','verification':'UNCONFIRMED','evidenceKind':'UNKNOWN'}
    if not records:coverage['text']='この銘柄に関連する、取得時点と利用範囲を確認できる報道は未取得です。材料がないという意味ではありません。'
    coverage['evidenceId']='subject-material-'+_digest(coverage)
    return records+[coverage]

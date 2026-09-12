"""Comparable-session market, sector-proxy and asset returns without trade authority."""
import hashlib
import json
import math
from datetime import datetime

SCHEMA = 'jp-market-internals-v1'
# Current sector classification and ETF mapping are disclosed, not historical membership.
# Official mapping: https://www.jpx.co.jp/equities/products/etfs/issues/01-03.html
SECTORS = {str(i): {'symbol': str(1616+i), 'nameJa': name} for i,name in enumerate((
    '食品','エネルギー資源','建設・資材','素材・化学','医薬品','自動車・輸送機','鉄鋼・非鉄','機械',
    '電機・精密','情報通信・サービスその他','電力・ガス','運輸・物流','商社・卸売','小売','銀行','金融（除く銀行）','不動産'),1)}


def _instant(value):
    result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('time_zone_required')
    return result


def _positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


def _hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def period_return(snapshot, *, start, end, cutoff, instrument_id, kind='EQUITY'):
    missing={'status':'UNAVAILABLE','instrumentId':instrument_id,'instrumentKind':kind,
             'startDate':start,'endDate':end,'returnPct':None}
    if not isinstance(snapshot,dict):return {**missing,'reason':'history_missing'}
    try:
        received=snapshot['receivedAt']; known=_instant(received)
        if known>_instant(cutoff):return {**missing,'reason':'received_after_cutoff'}
        if snapshot.get('instrumentId')!=instrument_id or snapshot.get('instrumentKind')!=kind:
            return {**missing,'reason':'instrument_mismatch'}
        basis=snapshot.get('priceBasis')
        expected='CASH_INDEX_CLOSE' if kind=='INDEX' else 'JQUANTS_ADJUSTED_CLOSE'
        if basis!=expected:return {**missing,'reason':'price_basis_unverified'}
        rows=snapshot['rows']
        if not isinstance(rows,list) or len(rows)>400:return {**missing,'reason':'history_bound'}
        ends=[]
        for day in (start,end):
            matches=[r for r in rows if isinstance(r,dict) and r.get('date')==day]
            if len(matches)!=1:return {**missing,'reason':'exact_session_missing_or_duplicated'}
            r=matches[0]
            if not _positive(r.get('close')) or r.get('completed') is not True:
                return {**missing,'reason':'completed_close_missing'}
            if kind!='INDEX' and (r.get('adjusted') is not True or not _positive(r.get('volume'))):
                return {**missing,'reason':'adjusted_traded_close_missing'}
            if _instant(r['closeAt'])>known or _instant(r['closeAt'])>_instant(cutoff):
                return {**missing,'reason':'close_not_yet_observed'}
            ends.append({k:r[k] for k in ('date','close','closeAt')})
        value=(ends[1]['close']/ends[0]['close']-1)*100
        record={**missing,'status':'AVAILABLE','returnPct':value,'priceBasis':basis,
                'receivedAt':received,'source':snapshot.get('source'),'sourceResponseSha256':snapshot.get('sourceResponseSha256'),
                'start':ends[0],'end':ends[1],'historicalVintageVerified':False}
        if snapshot.get('sourceSnapshotSha256'):
            record['sourceSnapshotSha256']=snapshot['sourceSnapshotSha256']
        record['evidenceId']=_hash(record);return record
    except (KeyError,TypeError,ValueError,OverflowError):return {**missing,'reason':'history_metadata_invalid'}


def breadth_from_ledger(observations, *, cutoff):
    """Select a complete received vintage, preserving the existing comparable-close method."""
    fields=('advancers','decliners','unchanged','unavailable','eligibleCount','totalUniverseCount')
    groups={}
    for row in observations:
        if not isinstance(row,dict):continue
        series=str(row.get('seriesId',''))
        if not series.startswith('breadth.prime.'):continue
        field=series.removeprefix('breadth.prime.')
        if field not in fields:continue
        try:
            if max(_instant(row['observedAt']),_instant(row['availableFrom']))>_instant(cutoff):continue
            if type(row['value']) not in (int,float) or not math.isfinite(row['value']) or row['value']<0 or int(row['value'])!=row['value']:continue
        except (KeyError,ValueError,TypeError):continue
        meta=row.get('metadata') or {}
        key=(row.get('periodEnd'),meta.get('sourceObservationHash'),meta.get('calculatedAt'))
        if not all(key):continue
        current=groups.setdefault(key,{})
        if field in current and (current[field] is None or current[field]['value']!=row['value']):current[field]=None
        else:current[field]=row
    valid=[]
    for key,group in groups.items():
        if any(not group.get(f) for f in fields):continue
        values={f:int(group[f]['value']) for f in fields}
        if values['advancers']+values['decliners']+values['unchanged']!=values['eligibleCount'] or values['eligibleCount']+values['unavailable']!=values['totalUniverseCount']:continue
        valid.append({'status':'AVAILABLE','periodEnd':key[0],'counts':values,
            'universeId':'tse_prime_domestic_common','universeLabelJa':'東証プライム国内普通株',
            'comparisonBasis':'PREVIOUS_COMPARABLE_CLOSE','receivedAt':max(group[f]['observedAt'] for f in fields),
            'sourceObservationHash':key[1],'calculatedAt':key[2],
            'methodVersion':group['advancers'].get('metadata',{}).get('methodVersion'),
            'source':'J-Quants V2 licensed aggregate','historicalVintageVerified':False})
    if not valid:return {'status':'UNAVAILABLE','reason':'complete_received_breadth_vintage_missing'}
    result=max(valid,key=lambda r:(r['periodEnd'],_instant(r['receivedAt'])))
    result['evidenceId']=_hash(result);return result


def build_snapshot(*, session_dates, cutoff, prices, symbols, classifications, breadth=None):
    """Use one fixed public sample and exact endpoints for each independent horizon."""
    if len(symbols)>100 or len(set(symbols))!=len(symbols):raise ValueError('public_sample_bound_or_duplicate')
    if not session_dates or len(set(session_dates))!=len(session_dates) or session_dates!=sorted(session_dates):
        raise ValueError('canonical_ordered_sessions_required')
    end=session_dates[-1];periods={}
    for horizon in (1,5,10,20):
        if len(session_dates)<=horizon:continue
        start=session_dates[-horizon-1]
        def calc(symbol,kind='EQUITY'):
            return period_return(prices.get(symbol),start=start,end=end,cutoff=cutoff,instrument_id=symbol,kind=kind)
        index=calc('NIKKEI_225_INDEX','INDEX');benchmark=calc('1306','ETF')
        sectors=[]
        for code,spec in SECTORS.items():
            result=calc(spec['symbol'],'ETF')
            sectors.append({**result,'sector17Code':code,'nameJa':spec['nameJa'],
                'comparisonKind':'SECTOR_ETF_PRICE_PROXY','benchmarkInstrumentId':'1306',
                'relativeToBenchmarkPct':result['returnPct']-benchmark['returnPct']
                    if result['status']==benchmark['status']=='AVAILABLE' else None})
        assets=[]
        for symbol in symbols:
            result=calc(symbol);meta=classifications.get(symbol) or {};sector=None
            try:
                if (_instant(meta['receivedAt'])<=_instant(cutoff) and meta['effectiveDate']<=end
                        and meta.get('source')=='J-Quants V2 equities/master'):
                    sector=next((r for r in sectors if r['sector17Code']==meta.get('sector17Code')),None)
            except (KeyError,ValueError,TypeError):pass
            assets.append({**result,'sector17Code':sector['sector17Code'] if sector else None,
                'sectorNameJa':sector['nameJa'] if sector else None,'classification':meta if sector else None,
                'relativeToNikkeiPct':result['returnPct']-index['returnPct'] if result['status']==index['status']=='AVAILABLE' else None,
                'relativeToSectorPct':result['returnPct']-sector['returnPct'] if sector and result['status']==sector['status']=='AVAILABLE' else None})
        available=[r for r in assets if r['status']=='AVAILABLE'];returns=[r['returnPct'] for r in available]
        counts={'advancers':sum(v>0 for v in returns),'decliners':sum(v<0 for v in returns),'unchanged':sum(v==0 for v in returns),
                'available':len(available),'expected':len(symbols),'missing':len(symbols)-len(available)}
        periods[str(horizon)]={'horizonSessions':horizon,'startDate':start,'endDate':end,
            'index':index,'benchmark':benchmark,'sectors':sectors,'assets':assets,
            'sample':{'scope':'FIXED_PUBLIC_WATCH_SAMPLE','isWholeMarket':False,'symbols':list(symbols),
                'counts':counts,'equalWeightReturnPct':sum(returns)/len(returns) if returns else None},
            'indexContributions':{'status':'UNAVAILABLE','reason':'exact_index_members_weights_adjustment_and_divisor_not_connected'},
            'directionScore':None,'actionAuthority':False}
    body={'schemaVersion':SCHEMA,'market':'JP','asOfDate':end,'periods':periods,
          'breadth':breadth or {'status':'UNAVAILABLE'},'classificationBasis':'CURRENT_RECEIVED_MASTER',
          'actionAuthority':False,'automaticAiCalls':0,'predictiveProbabilityVerified':False,
          'limitationsJa':['取得できた監視サンプルを市場全体として扱いません。',
            '業種はETF価格による比較です。業種指数そのもの、配当再投資リターンや資金流入量ではありません。',
            '業種分類は取得済みの現行分類です。過去時点の所属・将来の注文を示すものではありません。',
            '異なる期間を一つの強気度へ合算しません。指数寄与は正しい構成・係数の接続待ちです。']}
    body['evidenceId']=_hash(body);body['informationCutoff']=cutoff;return body


def explanation_facts(snapshot):
    facts=[]
    for horizon,row in (snapshot.get('periods') or {}).items():
        if row['index']['status']!='AVAILABLE':continue
        candidates=[r for r in row['sectors'] if r['relativeToBenchmarkPct'] is not None]
        strongest=max(candidates,key=lambda r:r['relativeToBenchmarkPct']) if candidates else None
        text=f"{row['startDate']}から{row['endDate']}の{horizon}営業日: 日経平均{row['index']['returnPct']:+.2f}%。"
        if strongest:text+=f"取得業種ETF中の相対上位は{strongest['nameJa']}、TOPIX連動ETF比{strongest['relativeToBenchmarkPct']:+.2f}ポイント。業種全体の資金流入とは未確認。"
        facts.append({'text':text,'priority':'P1','source':'market_internals_calculation','verification':'UNCONFIRMED',
            'provenance':{'scope':'published_metadata_snapshot','eventId':'market-internals-'+horizon,
                'publishedAt':None,'receivedAt':row['index'].get('receivedAt'),'observedAt':row['endDate'],'revision':None,'url':None,
                'sourceRowSha256':snapshot['evidenceId'],'sourceLabel':'日本株の指数・業種比較'}})
    return facts

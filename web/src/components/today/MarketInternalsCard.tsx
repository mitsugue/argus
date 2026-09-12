import React from 'react';

type Return = { status:string; instrumentId:string; returnPct:number|null; startDate:string;endDate:string;receivedAt?:string; reason?:string };
type Sector = Return & { sector17Code:string; nameJa:string; relativeToBenchmarkPct:number|null };
type Asset = Return & { sectorNameJa:string|null; relativeToSectorPct:number|null;relativeToNikkeiPct:number|null };
type Counts = { advancers:number; decliners:number; unchanged:number; available:number;expected:number;missing:number };
type Period = { horizonSessions:number;startDate:string;endDate:string;index:Return;benchmark:Return;sectors:Sector[];assets:Asset[];sample:{isWholeMarket:false;counts:Counts};indexContributions:{status:string} };
type Document = { schemaVersion:string;evidenceId:string;asOfDate:string;periods:Record<string,Period>;actionAuthority:false;predictiveProbabilityVerified:false;limitationsJa:string[];
  breadth:{status:string;periodEnd?:string;universeLabelJa?:string;receivedAt?:string;counts?:{advancers:number;decliners:number;unchanged:number;unavailable:number;totalUniverseCount:number}};
  acquisition?:{status:string;lastSuccessfulAcquisitionAt?:string;failedSymbols?:string[]} };
const obj=(v:unknown):v is Record<string,any>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const num=(v:unknown)=>typeof v==='number'&&Number.isFinite(v);
const nullable=(v:unknown)=>v===null||num(v);
const returnRow=(r:unknown):r is Return=>obj(r)&&['AVAILABLE','UNAVAILABLE'].includes(r.status)&&typeof r.instrumentId==='string'
  &&(r.status==='AVAILABLE'?num(r.returnPct):r.returnPct===null)&&typeof r.startDate==='string'&&typeof r.endDate==='string';
export function validMarketInternals(v:unknown):v is Document {
  if(!obj(v)||v.schemaVersion!=='jp-market-internals-v1'||v.actionAuthority!==false||v.predictiveProbabilityVerified!==false
    ||typeof v.evidenceId!=='string'||! /^[a-f0-9]{64}$/.test(v.evidenceId)||!obj(v.periods)||!obj(v.breadth)
    ||!['AVAILABLE','UNAVAILABLE'].includes(v.breadth.status)||Object.keys(v.periods).length===0
    ||!Array.isArray(v.limitationsJa)||!v.limitationsJa.every((x:unknown)=>typeof x==='string'))return false;
  if(v.breadth.status==='AVAILABLE') {
    const counts=v.breadth.counts;
    if(!obj(counts)||!['advancers','decliners','unchanged','unavailable','totalUniverseCount'].every(k=>Number.isSafeInteger(counts[k])&&counts[k]>=0)
      ||counts.advancers+counts.decliners+counts.unchanged+counts.unavailable!==counts.totalUniverseCount
      ||typeof v.breadth.periodEnd!=='string'||typeof v.breadth.universeLabelJa!=='string')return false;
  }
  return Object.entries(v.periods).every(([key,r])=>obj(r)&&[1,5,10,20].includes(Number(key))&&r.horizonSessions===Number(key)
    &&returnRow(r.index)&&returnRow(r.benchmark)&&r.benchmark.startDate===r.startDate&&r.benchmark.endDate===r.endDate&&Array.isArray(r.sectors)&&r.sectors.length<=17
    &&r.sectors.every((s:unknown)=>obj(s)&&typeof s.nameJa==='string'&&nullable(s.relativeToBenchmarkPct)&&returnRow(s))
    &&Array.isArray(r.assets)&&r.assets.length<=100&&r.assets.every((a:unknown)=>obj(a)&&nullable(a.relativeToSectorPct)&&nullable(a.relativeToNikkeiPct)&&returnRow(a))
    &&obj(r.sample)&&r.sample.isWholeMarket===false&&obj(r.sample.counts)
    &&['advancers','decliners','unchanged','available','expected','missing'].every(k=>Number.isSafeInteger(r.sample.counts[k])&&r.sample.counts[k]>=0)
    &&r.sample.counts.advancers+r.sample.counts.decliners+r.sample.counts.unchanged===r.sample.counts.available
    &&r.sample.counts.available+r.sample.counts.missing===r.sample.counts.expected
    &&r.sample.counts.expected===r.assets.length&&r.index.startDate===r.startDate&&r.index.endDate===r.endDate
    &&r.sectors.every((s:Sector)=>s.startDate===r.startDate&&s.endDate===r.endDate)
    &&r.assets.every((a:Asset)=>a.startDate===r.startDate&&a.endDate===r.endDate));
}
const percent=(n:number|null)=>n===null?'未取得':`${n>0?'+':''}${n.toFixed(2)}%`;
const points=(n:number|null)=>n===null?'未取得':`${n>0?'+':''}${n.toFixed(2)}ポイント`;
const stamp=(v?:string)=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'}):'未確認';

export function MarketInternalsCard({document,horizon}:{document:unknown;horizon:number}) {
  if(!validMarketInternals(document)||!document.periods[String(horizon)])return <section className="card at-internals" aria-label="日本株の指数・業種比較">
    <h3>市場の中で起きた変化</h3><p>指数・業種・銘柄を同じ期間で比較できるデータを確認中です。</p></section>;
  const row=document.periods[String(horizon)],counts=row.sample.counts;
  const sectors=[...row.sectors].sort((a,b)=>(b.relativeToBenchmarkPct??-Infinity)-(a.relativeToBenchmarkPct??-Infinity));
  const top=sectors.find(s=>s.relativeToBenchmarkPct!==null);
  const breadth=document.breadth;
  return <section className="card at-internals" aria-label="日本株の指数・業種比較">
    <h3>市場の中で起きた変化</h3>
    <p>{row.startDate} → {row.endDate} · 過去{horizon}営業日の比較</p>
    <p className="at-internals__lead">日経平均 <strong>{percent(row.index.returnPct)}</strong>
      {top&&<> ／ 相対上位の業種ETF：{top.nameJa} <strong>{percent(top.returnPct)}</strong></>}</p>
    {top&&<p>{top.nameJa}のETFは、同じ期間のTOPIX連動ETFより{points(top.relativeToBenchmarkPct)}。指数全体と業種の値動きを分けて確認します。</p>}
    <p>公開監視サンプル{counts.expected}銘柄のうち比較できた{counts.available}銘柄：上昇{counts.advancers}・下落{counts.decliners}・横ばい{counts.unchanged}。
      {counts.missing>0&&`比較不能${counts.missing}銘柄。`}市場全体の騰落数ではありません。</p>
    {breadth.status==='AVAILABLE'&&breadth.counts&&<p>{breadth.periodEnd}の{breadth.universeLabelJa}：上昇{breadth.counts.advancers}・下落{breadth.counts.decliners}・横ばい{breadth.counts.unchanged}
      （対象{breadth.counts.totalUniverseCount}、比較不能{breadth.counts.unavailable}）。各銘柄の直前の比較可能終値との比較です。</p>}
    {document.acquisition?.status==='PARTIAL'&&<p role="status">一部の更新は未取得です。最後の取得成功：{stamp(document.acquisition.lastSuccessfulAcquisitionAt)}。</p>}
    <details><summary>業種・銘柄別の比較を見る</summary>
      <p>業種ETFの価格比較です。配当再投資リターンや実際の資金流入量ではありません。</p>
      <div className="at-internals__rows">{sectors.map(sector=><div key={sector.instrumentId}>
        <span>{sector.nameJa} <small>{sector.instrumentId}</small></span><b>{percent(sector.returnPct)}</b>
        <small>TOPIX連動ETF比 {points(sector.relativeToBenchmarkPct)}</small></div>)}</div>
      <h4>観測した銘柄との関係</h4>
      {row.assets.map(asset=><div className="at-internals__asset" key={asset.instrumentId}><b>{asset.instrumentId} · {asset.sectorNameJa??'業種未確認'}</b>
        <p>騰落 {percent(asset.returnPct)} ／ 日経平均との差 {points(asset.relativeToNikkeiPct)} ／ 業種ETFとの差 {points(asset.relativeToSectorPct)}</p></div>)}
    </details>
    <details><summary>対象・出典・不足している根拠</summary>
      <p>日経平均：Yahoo Financeの現物指数終値。業種・監視銘柄：J-Quantsの調整済み終値。比較用TOPIX連動ETFは1306です。</p>
      <p>指数取得 {stamp(row.index.receivedAt)} ／ 集計取得 {stamp(breadth.receivedAt)}</p>
      {document.limitationsJa.map(text=><p key={text}>{text}</p>)}
      <p>この時点の根拠ID：<code className="at-internals__id">{document.evidenceId}</code></p>
    </details>
  </section>;
}

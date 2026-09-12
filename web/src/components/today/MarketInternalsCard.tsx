import React from 'react';
import { validMarketInternals } from '../../lib/marketInternals';

const percent=(n:number|null)=>n===null?'未取得':`${n>0?'+':''}${n.toFixed(2)}%`;
const points=(n:number|null)=>n===null?'未取得':`${n>0?'+':''}${n.toFixed(2)}ポイント`;
const stamp=(v?:string)=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'}):'未確認';

export function MarketInternalsCard({document,horizon,focusSymbol}:{document:unknown;horizon:number;focusSymbol?:string}) {
  if(!validMarketInternals(document)||!document.periods[String(horizon)])return <section className="card at-internals" aria-label="日本株の指数・業種比較">
    <h3>{focusSymbol?`${focusSymbol}と市場の変化`:"市場の中で起きた変化"}</h3><p>指数・業種・銘柄を同じ期間で比較できるデータを確認中です。</p></section>;
  const row=document.periods[String(horizon)],counts=row.sample.counts;
  const sectors=[...row.sectors].sort((a,b)=>(b.relativeToBenchmarkPct??-Infinity)-(a.relativeToBenchmarkPct??-Infinity));
  const top=sectors.find(s=>s.relativeToBenchmarkPct!==null);
  const breadth=document.breadth;
  const selectedAsset=focusSymbol?row.assets.find(asset=>asset.instrumentId===focusSymbol):null;
  return <section className="card at-internals" aria-label="日本株の指数・業種比較">
    <h3>{focusSymbol?`${focusSymbol}と市場の変化`:"市場の中で起きた変化"}</h3>
    <p>{row.startDate} → {row.endDate} · 過去{horizon}営業日の比較</p>
    <p className="at-internals__lead">日経平均 <strong>{percent(row.index.returnPct)}</strong>
      {top&&<> ／ 相対上位の業種ETF：{top.nameJa} <strong>{percent(top.returnPct)}</strong></>}</p>
    {top&&<p>{top.nameJa}のETFは、同じ期間のTOPIX連動ETFより{points(top.relativeToBenchmarkPct)}。指数全体と業種の値動きを分けて確認します。</p>}
    {focusSymbol&&<div className="at-internals__asset" data-market-context-symbol={focusSymbol}>
      {selectedAsset?.status==='AVAILABLE'?<>
        <p>{focusSymbol} <strong>{percent(selectedAsset.returnPct)}</strong> ／ 日経平均との差 <strong>{points(selectedAsset.relativeToNikkeiPct)}</strong></p>
        <p>{selectedAsset.sectorNameJa??'業種未確認'} · 業種ETFとの差 {points(selectedAsset.relativeToSectorPct)}。</p>
        <p>これは同じ期間の価格比較です。企業固有の材料や実際の保有状態に対する判断は、追加の根拠と合わせて確認します。</p>
      </>:<p>この銘柄について、同じ期間・尺度で比較できるデータは未取得です。別の銘柄や業種の値で補いません。</p>}
    </div>}
    {!focusSymbol&&<p>公開監視サンプル{counts.expected}銘柄のうち比較できた{counts.available}銘柄：上昇{counts.advancers}・下落{counts.decliners}・横ばい{counts.unchanged}。
      {counts.missing>0&&`比較不能${counts.missing}銘柄。`}市場全体の騰落数ではありません。</p>}
    {!focusSymbol&&breadth.status==='AVAILABLE'&&breadth.counts&&<p>{breadth.periodEnd}の{breadth.universeLabelJa}：上昇{breadth.counts.advancers}・下落{breadth.counts.decliners}・横ばい{breadth.counts.unchanged}
      （対象{breadth.counts.totalUniverseCount}、比較不能{breadth.counts.unavailable}）。各銘柄の直前の比較可能終値との比較です。</p>}
    {document.acquisition?.status==='PARTIAL'&&<p role="status">一部の更新は未取得です。最後の取得成功：{stamp(document.acquisition.lastSuccessfulAcquisitionAt)}。</p>}
    {!focusSymbol&&<details><summary>業種・銘柄別の比較を見る</summary>
      <p>業種ETFの価格比較です。配当再投資リターンや実際の資金流入量ではありません。</p>
      <div className="at-internals__rows">{sectors.map(sector=><div key={sector.instrumentId}>
        <span>{sector.nameJa} <small>{sector.instrumentId}</small></span><b>{percent(sector.returnPct)}</b>
        <small>TOPIX連動ETF比 {points(sector.relativeToBenchmarkPct)}</small></div>)}</div>
      <h4>観測した銘柄との関係</h4>
      {row.assets.map(asset=><div className="at-internals__asset" key={asset.instrumentId}><b>{asset.instrumentId} · {asset.sectorNameJa??'業種未確認'}</b>
        <p>騰落 {percent(asset.returnPct)} ／ 日経平均との差 {points(asset.relativeToNikkeiPct)} ／ 業種ETFとの差 {points(asset.relativeToSectorPct)}</p></div>)}
    </details>}
    <details><summary>対象・出典・不足している根拠</summary>
      <p>日経平均：Yahoo Financeの現物指数終値。業種・監視銘柄：J-Quantsの調整済み終値。比較用TOPIX連動ETFは1306です。</p>
      <p>指数取得 {stamp(row.index.receivedAt)} ／ 集計取得 {stamp(breadth.receivedAt)}</p>
      {document.limitationsJa.map(text=><p key={text}>{text}</p>)}
      <p>この時点の根拠ID：<code className="at-internals__id">{document.evidenceId}</code></p>
    </details>
  </section>;
}

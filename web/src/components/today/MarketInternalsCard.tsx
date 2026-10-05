import React from 'react';
import { validMarketInternals } from '../../lib/marketInternals';

const percent=(n:number|null)=>n===null?'未取得':`${n>0?'+':''}${n.toFixed(2)}%`;
const points=(n:number|null)=>n===null?'未取得':`${n>0?'+':''}${n.toFixed(2)}ポイント`;
const stamp=(v?:string)=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'}):'未確認';

export function MarketInternalsCard({document,horizon,focusSymbol}:{document:unknown;horizon:number;focusSymbol?:string}) {
  if(!validMarketInternals(document)||!document.periods[String(horizon)])return <section className="card at-internals" aria-label="日本株の指数・業種比較">
    <h3>{focusSymbol?`${focusSymbol}と市場の変化`:"上昇は市場全体に広がっているか"}</h3><p>指数・業種・銘柄を同じ期間で比較できるデータを確認中です。</p></section>;
  const row=document.periods[String(horizon)],counts=row.sample.counts;
  const sectors=[...row.sectors].sort((a,b)=>(b.relativeToBenchmarkPct??-Infinity)-(a.relativeToBenchmarkPct??-Infinity));
  const top=sectors.find(s=>s.relativeToBenchmarkPct!==null);
  const breadth=document.breadth;
  const selectedAsset=focusSymbol?row.assets.find(asset=>asset.instrumentId===focusSymbol):null;
  return <section className="card at-internals" aria-label="日本株の指数・業種比較">
    <h3>{focusSymbol?`${focusSymbol}と市場の変化`:"上昇は市場全体に広がっているか"}</h3>
    <p>{row.startDate} → {row.endDate} · 過去{horizon}営業日の比較</p>
    {document.comparisonAvailability?.latestSessionIncluded===false&&<p role="status">
      {document.comparisonAvailability.latestCompletedSessionDate}の終値が比較に必要な系列でそろっていないため、{document.comparisonAvailability.comparedThrough}までの確定値を表示しています。
    </p>}
    {top&&<><p className="at-context-lead">{top.nameJa}が、同じ期間の市場平均より{(top.relativeToBenchmarkPct??0)>=0?'強い':'弱い'}</p>
      <div className="at-context-metrics"><article><span>{top.nameJa} · 過去{horizon}営業日</span><strong>{percent(top.returnPct)}</strong></article>
        <article><span>TOPIX連動ETFとの差</span><strong>{points(top.relativeToBenchmarkPct)}</strong></article></div>
      <p>指数だけでなく、上昇している業種の広がりを比べます。特定の業種だけが強い場合は、その業種の動きを市場全体の強さと読み替えないことが大切です。</p></>}
    {focusSymbol&&<div className="at-internals__asset" data-market-context-symbol={focusSymbol}>
      {selectedAsset?.status==='AVAILABLE'?<>
        <p>{focusSymbol} <strong>{percent(selectedAsset.returnPct)}</strong> ／ 日経平均との差 <strong>{points(selectedAsset.relativeToNikkeiPct)}</strong></p>
        <p>{selectedAsset.sectorNameJa??'業種未確認'} · 業種ETFとの差 {points(selectedAsset.relativeToSectorPct)}。</p>
        <p>これは同じ期間の価格比較です。登録銘柄への影響は企業固有の材料など、追加の根拠と合わせて確認します。</p>
      </>:<p>この銘柄について、同じ期間・尺度で比較できるデータは未取得です。別の銘柄や業種の値で補いません。</p>}
    </div>}
    {!focusSymbol&&breadth.status==='AVAILABLE'&&breadth.counts&&<div className="at-breadth">
      <b>1日の上昇・下落銘柄数</b><p className="at-context-date">{breadth.periodEnd} · {breadth.universeLabelJa}</p>
      <div className="at-context-metrics"><article><span>上昇</span><strong>{breadth.counts.advancers.toLocaleString('ja-JP')}<small>銘柄</small></strong></article>
        <article><span>下落</span><strong>{breadth.counts.decliners.toLocaleString('ja-JP')}<small>銘柄</small></strong></article></div>
      <p>{breadth.counts.decliners>breadth.counts.advancers?'下落した銘柄の方が多い日です。':breadth.counts.advancers>breadth.counts.decliners?'上昇した銘柄の方が多い日です。':'上昇と下落の銘柄数は同じです。'}上の過去{horizon}営業日の業種比較とは、集計期間が異なります。</p>
    </div>}
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
      <p>同じ期間の日経平均 {percent(row.index.returnPct)}</p>
      {!focusSymbol&&<p>公開監視サンプル{counts.expected}銘柄のうち比較できた{counts.available}銘柄：上昇{counts.advancers}・下落{counts.decliners}・横ばい{counts.unchanged}。{counts.missing>0&&`比較不能${counts.missing}銘柄。`}市場全体の騰落数ではありません。</p>}
      {!focusSymbol&&breadth.status==='AVAILABLE'&&breadth.counts&&<p>横ばい{breadth.counts.unchanged}銘柄 · 対象{breadth.counts.totalUniverseCount} · 比較不能{breadth.counts.unavailable}。各銘柄の直前の比較可能終値との比較です。</p>}
      <p>日経平均：Yahoo Financeの現物指数終値。業種・監視銘柄：J-Quantsの調整済み終値。比較用TOPIX連動ETFは1306です。</p>
      <p>指数取得 {stamp(row.index.receivedAt)} ／ 集計取得 {stamp(breadth.receivedAt)}</p>
      {document.limitationsJa.map(text=><p key={text}>{text}</p>)}
      <p>この時点の根拠ID：<code className="at-internals__id">{document.evidenceId}</code></p>
    </details>
  </section>;
}

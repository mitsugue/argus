import { OwnerOverview } from '../dialogue/OwnerOverview';
import type { Job } from '../dialogue/OwnerDialogue';
import { OwnerDialogue } from '../dialogue/OwnerDialogue';
import type { AssetItem } from '../../types/assetItem';
import React, { useState } from 'react';
import { SharedMarketContext } from '../today/SharedMarketContext';
import { MarketBriefCard } from '../today/MarketBriefCard';

/** Shared public evidence and authenticated private explanation; no SDA mutation. */
export function AssetMarketContext({symbol,market,asset}:{symbol:string;market:string;asset?:AssetItem}) {
  const [horizon,setHorizon]=useState(5);
  const [overview,setOverview]=useState<Job|null>(null);
  const overviewMatches=overview?.context.subject.symbol===symbol&&overview.context.subject.market===market&&overview.context.horizonSessions===horizon;
  if(market!=='JP'&&market!=='US')return null;
  return <section className="ad-market-context" aria-label={`${symbol}と市場の関係`}>
    <label>比較する期間 <select value={horizon} onChange={event=>setHorizon(Number(event.target.value))}>
      {[1,5,10,20].map(days=><option key={days} value={days}>{days}営業日</option>)}
    </select></label>
    <OwnerOverview key={`${market}:${symbol}:${horizon}`} symbol={symbol} market={market} horizon={horizon} asset={asset} onReference={setOverview}/>
    {market==='JP'&&<SharedMarketContext horizon={horizon} focusSymbol={symbol}/>}
    {market==='JP'&&<details className="ad-market-context__brief"><summary>Todayと同じ市場の見立てを見る</summary>
      <p>市場全体の説明です。保有情報を使った質問は、この下の所有者専用の対話へ接続します。</p>
      <MarketBriefCard market="JP"/>
    </details>}
    <OwnerDialogue key={symbol} symbol={symbol} market={market} horizon={horizon} asset={asset} previousRequestId={overviewMatches?overview.requestId:undefined}/>
  </section>;
}

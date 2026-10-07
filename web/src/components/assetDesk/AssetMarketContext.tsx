import { OwnerOverview } from '../dialogue/OwnerOverview';
import type { AssetItem } from '../../types/assetItem';
import React, { useState } from 'react';
import { SharedMarketContext } from '../today/SharedMarketContext';
import { MarketBriefCard } from '../today/MarketBriefCard';

/** Shared public evidence and authenticated private explanation; no SDA mutation. */
export function AssetMarketContext({symbol,market,asset}:{symbol:string;market:string;asset?:AssetItem}) {
  const [horizon,setHorizon]=useState(5);
  const [comparisonOpen,setComparisonOpen]=useState(false);
  const [briefOpen,setBriefOpen]=useState(false);
  if(market!=='JP'&&market!=='US')return null;
  return <section className="ad-market-context" aria-label={`${symbol}と市場の関係`}>
    <label>市場と比べる期間 <select value={horizon} onChange={event=>setHorizon(Number(event.target.value))}>
      {[1,5,10,20].map(days=><option key={days} value={days}>{days}営業日</option>)}
    </select></label>
    <OwnerOverview key={`${market}:${symbol}:${horizon}`} symbol={symbol} market={market} horizon={horizon} asset={asset}/>
    {market==='JP'&&<details className="ad-market-context__brief" open={comparisonOpen} onToggle={event=>setComparisonOpen(event.currentTarget.open)}><summary>指数・業種とこの銘柄の比較</summary>
      {comparisonOpen&&<SharedMarketContext horizon={horizon} focusSymbol={symbol}/>}</details>}
    {market==='JP'&&<details className="ad-market-context__brief" open={briefOpen} onToggle={event=>setBriefOpen(event.currentTarget.open)}><summary>市場全体の見立て（Today）</summary>
      <p>市場全体の背景を確認できます。</p>
      {briefOpen&&<MarketBriefCard market="JP"/>}
    </details>}
  </section>;
}

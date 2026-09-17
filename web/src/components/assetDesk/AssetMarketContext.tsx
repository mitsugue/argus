import { OwnerOverview } from '../dialogue/OwnerOverview';
import type { AssetItem } from '../../types/assetItem';
import React, { useState } from 'react';
import { SharedMarketContext } from '../today/SharedMarketContext';
import { MarketBriefCard } from '../today/MarketBriefCard';

/** Shared public evidence and authenticated private explanation; no SDA mutation. */
export function AssetMarketContext({symbol,market,asset}:{symbol:string;market:string;asset?:AssetItem}) {
  const [horizon,setHorizon]=useState(5);
  if(market!=='JP'&&market!=='US')return null;
  return <section className="ad-market-context" aria-label={`${symbol}と市場の関係`}>
    <label>比較する期間 <select value={horizon} onChange={event=>setHorizon(Number(event.target.value))}>
      {[1,5,10,20].map(days=><option key={days} value={days}>{days}営業日</option>)}
    </select></label>
    <OwnerOverview key={`${market}:${symbol}:${horizon}`} symbol={symbol} market={market} horizon={horizon} asset={asset}/>
    {market==='JP'&&<SharedMarketContext horizon={horizon} focusSymbol={symbol}/>}
    {market==='JP'&&<details className="ad-market-context__brief"><summary>Todayと同じ市場の見立てを見る</summary>
      <p>市場全体と銘柄固有の根拠を分けて確認できます。</p>
      <MarketBriefCard market="JP"/>
    </details>}
  </section>;
}

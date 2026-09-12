import React, { useState } from 'react';
import { SharedMarketContext } from '../today/SharedMarketContext';
import { MarketBriefCard } from '../today/MarketBriefCard';

/** Public market explanation, never an owner-specific recommendation or SDA input. */
export function AssetMarketContext({symbol,market}:{symbol:string;market:string}) {
  const [horizon,setHorizon]=useState(5);
  if(market!=='JP')return null;
  return <section className="ad-market-context" aria-label={`${symbol}と市場の関係`}>
    <label>比較する期間 <select value={horizon} onChange={event=>setHorizon(Number(event.target.value))}>
      {[1,5,10,20].map(days=><option key={days} value={days}>過去{days}営業日</option>)}
    </select></label>
    <SharedMarketContext horizon={horizon} focusSymbol={symbol}/>
    <details className="ad-market-context__brief"><summary>Todayと同じ市場の見立てを見る</summary>
      <p>市場全体の説明です。保有数量・購入理由・保有期間を反映した銘柄固有の統合AI説明は、まだ接続できていません。</p>
      <MarketBriefCard market="JP"/>
    </details>
  </section>;
}

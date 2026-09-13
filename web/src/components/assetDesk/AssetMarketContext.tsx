import { OwnerDialogue } from '../dialogue/OwnerDialogue';
import type { AssetItem } from '../../types/assetItem';
import React, { useState } from 'react';
import { SharedMarketContext } from '../today/SharedMarketContext';
import { MarketBriefCard } from '../today/MarketBriefCard';

/** Public market explanation, never an owner-specific recommendation or SDA input. */
export function AssetMarketContext({symbol,market,asset}:{symbol:string;market:string;asset?:AssetItem}) {
  const [horizon,setHorizon]=useState(5);
  if(market!=='JP'&&market!=='US')return null;
  if(market==='US')return <OwnerDialogue key={symbol} symbol={symbol} market="US" horizon={horizon} asset={asset}/>;
  return <section className="ad-market-context" aria-label={`${symbol}と市場の関係`}>
    <label>比較する期間 <select value={horizon} onChange={event=>setHorizon(Number(event.target.value))}>
      {[1,5,10,20].map(days=><option key={days} value={days}>過去{days}営業日</option>)}
    </select></label>
    <SharedMarketContext horizon={horizon} focusSymbol={symbol}/>
    <details className="ad-market-context__brief"><summary>Todayと同じ市場の見立てを見る</summary>
      <p>市場全体の説明です。保有情報を使った質問は、この下の所有者専用の対話へ接続します。</p>
      <MarketBriefCard market="JP"/>
    </details>
    <OwnerDialogue key={symbol} symbol={symbol} market="JP" horizon={horizon} asset={asset}/>
  </section>;
}

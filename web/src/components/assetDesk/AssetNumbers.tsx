import React from 'react';
import type { DeskCardData } from './types';
import { useDecisionEvidence } from '../../hooks/useDecisionEvidence';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import { selectMarketInternals } from '../../lib/marketInternals';

// 2026-10-26 (owner): the first card keeps the target, supply and results; the
// stock page adds only what the card does not show — the five-day gap to the
// Nikkei, from the same market-internals frame as Today (display only).

export const AssetNikkeiGap: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const evidence = useDecisionEvidence();
  const { brief } = useMarketBrief();
  if (d.asset.market !== 'JP') return null;
  const internals = selectMarketInternals(brief, evidence.marketView?.internals, 5).document;
  const gap = internals?.periods['5']?.assets
    .find((asset) => asset.instrumentId === d.asset.symbol.toUpperCase())?.relativeToNikkeiPct ?? null;
  if (gap == null) return null;
  return <p className="ad-conclusion__gap" data-asset-nikkei-gap={d.asset.symbol}>
    日経との差（5日） {gap >= 0 ? '+' : ''}{gap.toFixed(2)}%
  </p>;
};

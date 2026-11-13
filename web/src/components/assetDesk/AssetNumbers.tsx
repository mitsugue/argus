import React from 'react';
import type { DeskCardData } from './types';
import { useDecisionEvidence } from '../../hooks/useDecisionEvidence';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import { selectMarketInternals } from '../../lib/marketInternals';
import { assetPeriodGapJa } from '../../lib/assetPeriodGap';

// 2026-10-26 (owner): the first card keeps the target, supply and results; the
// stock page adds only what the card does not show — the five-day gap to the
// Nikkei, from the same market-internals frame as Today (display only).

export const AssetNikkeiGap: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const evidence = useDecisionEvidence();
  const { brief } = useMarketBrief();
  if (d.asset.market !== 'JP') return null;
  const internals = selectMarketInternals(brief, evidence.marketView?.internals, 5).document;
  const row = internals?.periods['5']?.assets
    .find((asset) => asset.instrumentId === d.asset.symbol.toUpperCase());
  const line = assetPeriodGapJa(row, 5);
  if (!line) return null;
  return <p className="ad-conclusion__gap" data-asset-nikkei-gap={d.asset.symbol}>{line}</p>;
};

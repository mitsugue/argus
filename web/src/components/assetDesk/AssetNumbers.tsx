import React from 'react';
import type { DeskCardData } from './types';
import { useAnalystTargetState } from '../../hooks/useAnalystTargets';
import { useDecisionEvidence } from '../../hooks/useDecisionEvidence';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import { selectMarketInternals } from '../../lib/marketInternals';
import { analystTargetGap, outlookMoney } from '../../domain/assetOutlook';
import { earningsAmount, earningsShortDate } from '../../domain/assetEarnings';

// 2026-10-25 (owner): four numbers under the conclusion — the analysts'
// target, supply and demand, the next results and the gap to the Nikkei.

const signed = (value: number, digits = 1) => `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;

const Tile: React.FC<{ label: string; value: string; sub?: string | null }> = ({ label, value, sub }) => (
  <div className="ad-number">
    <span className="ad-number__label">{label}</span>
    <b>{value}{sub && <small>{sub}</small>}</b>
  </div>
);

export const AssetNumbers: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const analyst = useAnalystTargetState();
  const evidence = useDecisionEvidence();
  const { brief } = useMarketBrief();
  const market = d.asset.market;
  if (market !== 'JP' && market !== 'US') return null;
  const key = `${market}:${d.asset.symbol.toUpperCase()}`;
  const target = analyst.items[key];
  const price = d.strat.status === 'mock' ? null : d.strat.price ?? d.card?.price ?? null;
  const gap = target ? analystTargetGap(target, price) : null;
  const supply = d.sdg?.market === market && d.sdg.supplyDemandRank !== 'Unknown' ? d.sdg : null;
  const ratio = supply?.ratios?.margin ?? supply?.ratios?.jsf ?? null;
  const earnings = analyst.earnings?.[key];
  const nextDate = earningsShortDate(earnings);
  const eps = earnings?.estimate?.eps;
  const internals = market === 'JP' ? selectMarketInternals(brief, evidence.marketView?.internals, 5).document : null;
  const versusNikkei = internals?.periods['5']?.assets
    .find((asset) => asset.instrumentId === d.asset.symbol.toUpperCase())?.relativeToNikkeiPct ?? null;
  return (
    <div className="ad-numbers" data-asset-numbers={key}>
      <Tile label="目標株価" value={target ? outlookMoney(target.mean, market) : '—'} sub={gap != null ? signed(gap) : null} />
      <Tile label="需給" value={supply ? supply.supplyDemandRank : '—'} sub={ratio != null ? `倍率 ${ratio.toFixed(1)}` : null} />
      <Tile label="次の決算" value={nextDate ?? '—'}
        sub={eps != null ? `予想EPS ${earningsAmount(eps, earnings?.estimate?.epsCurrency ?? null)}` : null} />
      {market === 'JP' && <Tile label="日経との差 5日" value={versusNikkei != null ? signed(versusNikkei, 2) : '—'} />}
    </div>
  );
};

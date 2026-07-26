import React from 'react';
import type { DeskCardData } from './types';
import { SIGNALS, resolveSignal, type OwnerState, type SignalCode } from '../../domain/actionLevel';
import { SignedValue } from '../common/SignedValue';

// V12.2.12 — 閉じたカード(§6): 開かなくても「何をどうするか」が分かる1枚。
// 主判断はdomain/assetDecisionの出力のみ(AI PRIMARY / RULE TEMPORARY明示)。

const GENRE_TAG: Record<string, string> = { jp: 'JP', us: 'US', funds: '投信', crypto: 'CRYPTO' };

export function deskSignalCode(d: DeskCardData): SignalCode {
  if (d.card) return d.card.signalCode;
  const sig = resolveSignal(d.strat.action, {
    downsideOverride: d.incident?.actionOverride,
    dataQuality: d.strat.status === 'live' ? 'LIVE' : d.strat.status === 'mock' ? 'MOCK' : 'PARTIAL',
    materialDownside: !!d.incident,
    ownerState: (d.incident?.ownerState as OwnerState) || undefined,
  });
  return sig.code;
}

export const AssetDecisionSummary: React.FC<{
  d: DeskCardData; open: boolean; onToggle: () => void;
}> = ({ d, open, onToggle }) => {
  const code = deskSignalCode(d);
  const sigColor = `var(${SIGNALS[code].token})`;
  const view = d.decisionFirst;

  return (
    <button className="ad-head" onClick={onToggle} aria-expanded={open}
      aria-label={`${view.symbol} ${view.name}, ${view.currentActionJa}`}>
      <span className="ad-l1">
        {view.held ? <span className="ad-held">保有</span> : <span className="ad-watch">WATCH</span>}
        <span className="ad-sym">{view.symbol}</span>
        <span className="ad-name">{view.name}</span>
        <span className="ad-mkt">{GENRE_TAG[d.genre]}</span>
        <span className="ad-price">{view.priceText}</span>
        <span className="ad-chg">{view.changePct == null ? '—'
          : <SignedValue value={view.changePct} suffix="%" arrow={false} />}</span>
        <span className="ad-chevron" aria-hidden>{open ? '−' : '+'}</span>
      </span>
      <span className="ad-l2">
        <span className="ad-cmd" style={{ color: sigColor }}>{view.currentActionJa}</span>
        <span className="ad-owner-state">
          {view.held
            ? `保有損益 ${view.pnlPct == null ? '未計算'
              : `${view.pnlPct >= 0 ? '+' : ''}${view.pnlPct.toFixed(1)}%`}`
            : '監視のみ'}
        </span>
        <span className="ad-prio">{view.priority}</span>
        <span className="ad-data">{view.dataStatus}</span>
      </span>
    </button>
  );
};

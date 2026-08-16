import React from 'react';
import type { DeskCardData } from './types';
import { SIGNALS, type SignalCode } from '../../domain/actionLevel';
import { SignedValue } from '../common/SignedValue';
import { quoteAge, quoteAsOf } from '../../domain/liveQuote';

// V12.2.12 — 閉じたカード(§6): 開かなくても「何をどうするか」が分かる1枚。
// 主判断はdomain/assetDecisionの出力のみ(AI PRIMARY / RULE TEMPORARY明示)。

const GENRE_TAG: Record<string, string> = { jp: 'JP', us: 'US', funds: '投信', crypto: 'CRYPTO' };

export function deskSignalCode(d: DeskCardData): SignalCode {
  // Compatibility color only. The decision itself is the SDA action already
  // projected into decisionFirst; legacy card/incident/rule fields cannot win.
  return d.decisionFirst.signalCode as SignalCode;
}

export const AssetDecisionSummary: React.FC<{
  d: DeskCardData; open: boolean; onToggle: () => void; interactive?: boolean;
}> = ({ d, open, onToggle, interactive = true }) => {
  const code = deskSignalCode(d);
  const sigColor = `var(${SIGNALS[code].token})`;
  const view = d.decisionFirst;

  const content = <>
      <span className="ad-l1">
        {view.held ? <span className="ad-held">保有</span> : <span className="ad-watch">WATCH</span>}
        <span className="ad-sym">{view.symbol}</span>
        <span className="ad-name">{view.name}</span>
        <span className="ad-mkt">{GENRE_TAG[d.genre]}</span>
        <span className="ad-price">{view.priceText}</span>
        <span className="ad-chg">{view.changePct == null ? '—'
          : <SignedValue value={view.changePct} suffix="%" arrow={false} />}</span>
        {interactive && <span className="ad-chevron" aria-hidden>{open ? '−' : '+'}</span>}
      </span>
      <span className="ad-l2">
        <span className="ad-cmd" style={{ color: sigColor }}>{view.currentActionJa}</span>
        {view.canonicalDecisionStatus && <span className="ad-data">
          SDA {view.canonicalDecisionStatus}
        </span>}
        <span className="ad-owner-state">
          {view.held
            ? `保有損益 ${view.pnlPct == null ? '未計算'
              : `${view.pnlPct >= 0 ? '+' : ''}${view.pnlPct.toFixed(1)}%`}`
            : '監視のみ'}
        </span>
        <span className="ad-prio">{view.priority}</span>
        <span className="ad-data">{view.dataStatus}</span>
      </span>
      {view.quoteTruth && <span className="ad-quote-meta">
        <span>{view.quoteTruth.instrumentType}</span>
        <mark data-delay={view.quoteTruth.delayClass}>{view.quoteTruth.delayClass}</mark>
        <span>{view.quoteTruth.provider}</span>
        <span>{quoteAsOf(view.quoteTruth)}</span>
        <span>{quoteAge(view.quoteTruth)}</span>
      </span>}
    </>;
  const label = `${view.symbol} ${view.name}, ${view.currentActionJa}`;
  return interactive ? (
    <button className="ad-head" onClick={onToggle} aria-expanded={open} aria-label={label}>
      {content}
    </button>
  ) : (
    <div className="ad-head" aria-label={label}>{content}</div>
  );
};

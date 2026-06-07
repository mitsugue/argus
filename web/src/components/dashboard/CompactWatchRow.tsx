import React from 'react';
import { ActionPill } from '../action/ActionBadge';
import type { WatchEntry } from '../../types/watch';

interface Props {
  entry: WatchEntry;
}

function formatPrice(value: number, market: 'JP' | 'US'): string {
  if (market === 'JP') return `¥${Math.round(value).toLocaleString('en-US')}`;
  return `$${value.toFixed(2)}`;
}

function formatPct(pct: number): string {
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : '';
  return `${sign}${Math.abs(pct).toFixed(2)}%`;
}

function changeClass(pct: number): string {
  if (pct > 0.05) return 'watch-row__change watch-row__change--up';
  if (pct < -0.05) return 'watch-row__change watch-row__change--down';
  return 'watch-row__change';
}

// Today-page preview row. Per spec the Today page only shows:
//   ticker / name / action / price + Δ / one short scanner rationale /
//   next trigger. No volume, no VWAP, no margin / JSF / guidance — those
//   live on the full Watchlist page so the home view stays scan-friendly.
export const CompactWatchRow: React.FC<Props> = ({ entry }) => {
  return (
    <div className="watch-row">
      <div className="watch-row__primary">
        <div className="watch-row__id">
          <span className="watch-row__symbol">{entry.symbol}</span>
          <span className="watch-row__name">{entry.name}</span>
        </div>
        <div className="watch-row__price-block">
          <span className="watch-row__price">{formatPrice(entry.price, entry.market)}</span>
          <span className={changeClass(entry.changePct)}>{formatPct(entry.changePct)}</span>
        </div>
        <div className="watch-row__action">
          <ActionPill action={entry.action} size="sm" />
        </div>
      </div>
      {entry.reason && (
        <p className="alert-card__reason" style={{ margin: 0 }}>{entry.reason}</p>
      )}
    </div>
  );
};

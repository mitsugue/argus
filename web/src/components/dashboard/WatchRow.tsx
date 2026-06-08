import React from 'react';
import type { WatchEntry, WatchJP, WatchUS } from '../../types/watch';
import { ActionPill } from '../action/ActionBadge';

interface Props {
  entry: WatchEntry;
}

function formatPrice(value: number, market: 'JP' | 'US'): string {
  if (market === 'JP') return `¥${Math.round(value).toLocaleString('en-US')}`;
  return `$${value.toFixed(2)}`;
}

function formatChangeAbs(abs: number, market: 'JP' | 'US'): string {
  const sign = abs > 0 ? '+' : abs < 0 ? '−' : '';
  const magnitude = Math.abs(abs);
  const body = market === 'JP'
    ? Math.round(magnitude).toString()
    : magnitude.toFixed(2);
  return `${sign}${body}`;
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

function formatVolume(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

function formatEarnings(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// JP-specific metadata line — Vol · VWAP · Margin L/S · JSF · Earnings.
const JpMeta: React.FC<{ row: WatchJP }> = ({ row }) => (
  <div className="watch-row__meta">
    <span>Vol {formatVolume(row.volume)}</span>
    {row.vwapDeltaPct != null && (
      <>
        <span className="watch-row__dot">·</span>
        <span>VWAP {row.vwapDeltaPct > 0 ? '+' : ''}{row.vwapDeltaPct.toFixed(2)}%</span>
      </>
    )}
    {(row.marginLong != null && row.marginShort != null) && (
      <>
        <span className="watch-row__dot">·</span>
        <span>
          Margin {(row.marginLong / 1000).toFixed(1)}k / {(row.marginShort / 1000).toFixed(1)}k
        </span>
      </>
    )}
    {(row.jsfBorrowed != null && row.jsfLent != null) && (
      <>
        <span className="watch-row__dot">·</span>
        <span>
          JSF +{row.jsfBorrowed} / −{row.jsfLent}
        </span>
      </>
    )}
    {row.earningsDate && (
      <>
        <span className="watch-row__dot">·</span>
        <span>Earnings {formatEarnings(row.earningsDate)}</span>
      </>
    )}
  </div>
);

// US-specific metadata — Pre/AH Δ · Guidance · Sector · Rate sensitivity · Earnings.
const UsMeta: React.FC<{ row: WatchUS }> = ({ row }) => {
  const sessionChange = row.premarketPct != null
    ? { label: 'PM', value: row.premarketPct }
    : row.afterHoursPct != null
      ? { label: 'AH', value: row.afterHoursPct }
      : null;
  return (
    <div className="watch-row__meta">
      {sessionChange && (
        <>
          <span>{sessionChange.label} {sessionChange.value > 0 ? '+' : ''}{sessionChange.value.toFixed(2)}%</span>
          <span className="watch-row__dot">·</span>
        </>
      )}
      {row.guidance && (
        <>
          <span>Guidance <span className={`watch-row__guidance watch-row__guidance--${row.guidance}`}>{row.guidance}</span></span>
          <span className="watch-row__dot">·</span>
        </>
      )}
      {row.sectorTrend && (
        <>
          <span>Sector {row.sectorTrend}</span>
          <span className="watch-row__dot">·</span>
        </>
      )}
      {row.rateSensitivity && (
        <>
          <span>Rate-sens {row.rateSensitivity}</span>
          <span className="watch-row__dot">·</span>
        </>
      )}
      {row.earningsDate && <span>Earnings {formatEarnings(row.earningsDate)}</span>}
    </div>
  );
};

export const WatchRow: React.FC<Props> = ({ entry }) => {
  return (
    <div className="watch-row">
      <div className="watch-row__primary">
        <div className="watch-row__id">
          <span className="watch-row__symbol">{entry.symbol}</span>
          <span className="watch-row__name">{entry.name}</span>
        </div>
        <div className="watch-row__price-block">
          <span className="watch-row__price">{formatPrice(entry.price, entry.market)}</span>
          <span className={changeClass(entry.changePct)}>
            {formatPct(entry.changePct)}
            <span className="watch-row__change-abs">
              {formatChangeAbs(entry.changeAbs, entry.market)}
            </span>
          </span>
        </div>
        <div className="watch-row__action">
          <ActionPill action={entry.action} size="sm" />
        </div>
      </div>
      {entry.market === 'JP' ? <JpMeta row={entry} /> : <UsMeta row={entry} />}
      {entry.newsHeadline && (
        <div className="watch-row__news">{entry.newsHeadline}</div>
      )}
      {entry.reason && (
        <div className="watch-row__reason">{entry.reason}</div>
      )}
    </div>
  );
};

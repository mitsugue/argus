import React, { useMemo } from 'react';
import { PageShell } from './PageShell';
import { WatchRow } from '../components/dashboard/WatchRow';
import { ActionPill } from '../components/action/ActionBadge';
import { watchlist } from '../mock/watchlist';
import { useJapanWatchlist } from '../hooks/useJapanWatchlist';
import type { WatchEntry, WatchJP, JapanStockQuote } from '../types/watch';
import type { ActionKey } from '../types/action';
import '../components/dashboard/Dashboard.css';

// Sort: defensive first (EXIT > TRIM > WAIT_FOR_PULLBACK > WAIT > BUY_DIP > ADD > HOLD).
const URGENCY: Record<ActionKey, number> = {
  EXIT: 0,
  TRIM: 1,
  WAIT_FOR_PULLBACK: 2,
  WAIT: 3,
  BUY_DIP: 4,
  ADD: 5,
  HOLD: 6,
};

const sortByUrgency = (a: WatchEntry, b: WatchEntry) =>
  URGENCY[a.action as ActionKey] - URGENCY[b.action as ActionKey];

// Distinct actions that appear in scope — used for the summary chip strip.
function tally(entries: WatchEntry[]): { action: ActionKey; count: number }[] {
  const counts = new Map<ActionKey, number>();
  for (const e of entries) {
    counts.set(e.action as ActionKey, (counts.get(e.action as ActionKey) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([action, count]) => ({ action, count }))
    .sort((a, b) => URGENCY[a.action] - URGENCY[b.action]);
}

// Live J-Quants rows carry price/change/volume only — there is no AI action
// label yet, so show a neutral placeholder. Wiring the scanner's action is a
// separate step. (VWAP / margin / news are also absent from daily bars.)
const JP_PLACEHOLDER_ACTION: ActionKey = 'HOLD';

function toWatchJP(q: JapanStockQuote): WatchJP {
  return {
    market: 'JP',
    symbol: q.symbol,
    name: q.name,
    price: q.price,
    changePct: q.changePct,
    changeAbs: q.changeAbs,
    volume: q.volume,
    action: JP_PLACEHOLDER_ACTION,
    updatedAt: Date.now(),
  };
}

export const Watchlist: React.FC = () => {
  // Japan rows are live from J-Quants (backend), with connecting/mock states.
  const { data: jp, phase, attempt } = useJapanWatchlist();

  const jpRows = useMemo<WatchJP[]>(
    () => (jp ? jp.stocks.map(toWatchJP) : []),
    [jp],
  );
  // United States stays on seed data until wired to a real source.
  const usRows = useMemo(
    () => watchlist.filter((e) => e.market === 'US').sort(sortByUrgency),
    [],
  );
  const summary = useMemo(() => tally([...jpRows, ...usRows]), [jpRows, usRows]);

  const jpStatusLabel =
    phase === 'connecting'
      ? attempt > 1 ? `waking backend · try ${attempt}` : 'connecting'
      : phase; // 'live' | 'mock'

  return (
    <PageShell
      title="Watchlist"
      subtitle="Tracked names with their action label. Sorted by urgency — defensive calls first."
    >
      <div className="watch-summary">
        {summary.map(({ action, count }) => (
          <span className="watch-summary__item" key={action}>
            <ActionPill action={action} size="sm" />
            <span className="watch-summary__count">{count}</span>
          </span>
        ))}
      </div>

      <section>
        <div className="section-head">
          <span className="section-head__title">Japan</span>
          <span className={`watch-status watch-status--${phase}`}>{jpStatusLabel}</span>
          {phase === 'live' && jp?.asOf ? (
            <span className="section-head__count">live · as of {jp.asOf}</span>
          ) : (
            <span className="section-head__count">{jpRows.length} names</span>
          )}
        </div>
        <div className="card watch-list">
          {jpRows.map((row) => (
            <WatchRow key={row.symbol} entry={row} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">United States</span>
          <span className="section-head__count">{usRows.length} names</span>
        </div>
        <div className="card watch-list">
          {usRows.map((row) => (
            <WatchRow key={row.symbol} entry={row} />
          ))}
        </div>
      </section>
    </PageShell>
  );
};

import React, { useMemo } from 'react';
import { PageShell } from './PageShell';
import { WatchRow } from '../components/dashboard/WatchRow';
import { ActionPill } from '../components/action/ActionBadge';
import { watchlist } from '../mock/watchlist';
import type { WatchEntry } from '../types/watch';
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

export const Watchlist: React.FC = () => {
  const jpRows = useMemo(
    () => watchlist.filter((e) => e.market === 'JP').sort(sortByUrgency),
    []
  );
  const usRows = useMemo(
    () => watchlist.filter((e) => e.market === 'US').sort(sortByUrgency),
    []
  );
  const summary = useMemo(() => tally(watchlist), []);

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
          <span className="section-head__count">{jpRows.length} names</span>
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

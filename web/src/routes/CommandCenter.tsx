import React from 'react';
import { PageShell } from './PageShell';
import { HeroCard } from '../components/dashboard/HeroCard';
import { TopRotations } from '../components/regime/TopRotations';
import { CompactWatchRow } from '../components/dashboard/CompactWatchRow';
import { CompactEventRow } from '../components/dashboard/CompactEventRow';
import { CompactCoreRow } from '../components/dashboard/CompactCoreRow';
import {
  indexFundStatus,
  todayJudgment,
  upcomingEvents,
} from '../mock/dashboard';
import { topRotations as mockRotations } from '../mock/regime';
import { watchlist } from '../mock/watchlist';
import { useMarketRegime } from '../hooks/useMarketRegime';
import type { ActionKey } from '../types/action';
import type { TopRotation } from '../types/regime';
import type { RouteKey } from '../components/NavRail';
import '../components/dashboard/Dashboard.css';

interface Props {
  onNavigate: (key: RouteKey) => void;
}

// Today is a SUMMARY. Detail (full alert cards, dense watchlist rows,
// event escalation policy, per-position reasoning) lives on the
// respective detail pages.
const URGENCY: Record<ActionKey, number> = {
  EXIT: 0,
  TRIM: 1,
  WAIT_FOR_PULLBACK: 2,
  WAIT: 3,
  BUY_DIP: 4,
  ADD: 5,
  HOLD: 6,
};

const PRIORITY_WATCH_LIMIT = 3;
const PREVIEW_EVENT_LIMIT = 3;

// Compact aliases for the core preview ("JP Core" rather than the full
// fund title). Keyed by the position symbol.
const CORE_SHORT: Record<string, string> = {
  'eMAXIS Slim S&P 500':     'US Core (NISA)',
  'eMAXIS Slim All-Country': 'Global Core (NISA)',
  'VTI':                     'US ETF',
  'Nikkei 225 Index':        'Nikkei-linked',
};

const formatDate = (iso: string) => {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  });
};

export const CommandCenter: React.FC<Props> = ({ onNavigate }) => {
  // Live Top Rotations from the Market Regime engine (falls back to mock when
  // the backend is unavailable). Split the "A -> B" label into from/to.
  const { data: regime } = useMarketRegime();
  const topRotations: TopRotation[] = (() => {
    const live = regime?.topRotations ?? [];
    if (live.length === 0) return mockRotations;
    return live.map((t) => {
      const [from, to] = t.label.split(' -> ');
      return { from: from ?? t.label, to: to ?? '' };
    });
  })();

  const priority = watchlist
    .slice()
    .sort((a, b) => URGENCY[a.action as ActionKey] - URGENCY[b.action as ActionKey])
    .slice(0, PRIORITY_WATCH_LIMIT);
  const events = upcomingEvents
    .slice()
    .sort((a, b) => a.at - b.at)
    .slice(0, PREVIEW_EVENT_LIMIT);

  return (
    <PageShell title="Daily Command Center" subtitle={formatDate(todayJudgment.date)}>
      <HeroCard judgment={todayJudgment} />

      <section>
        <div className="section-head">
          <span className="section-head__title">Top Rotations</span>
          <button
            className="section-head__link"
            onClick={() => {
              // Signal Market Regime to scroll to the full board after it mounts
              // (fixes the iPhone half-wrong landing position).
              try { sessionStorage.setItem('argus.scrollTo', 'full-board'); } catch { /* ignore */ }
              onNavigate('regime');
            }}
          >
            full board
          </button>
        </div>
        <TopRotations rotations={topRotations} />
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Priority watchlist</span>
          <button className="section-head__link" onClick={() => onNavigate('watchlist')}>
            {priority.length} of {watchlist.length} names · view all
          </button>
        </div>
        <div className="card watch-list">
          {priority.map((row) => (
            <CompactWatchRow key={row.symbol} entry={row} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Event Radar</span>
          <button className="section-head__link" onClick={() => onNavigate('events')}>
            next {events.length}
          </button>
        </div>
        <div className="card event-list">
          {events.map((e) => (
            <CompactEventRow key={e.id} event={e} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Core Portfolio</span>
          <button className="section-head__link" onClick={() => onNavigate('core')}>
            {indexFundStatus.length} positions
          </button>
        </div>
        <div className="card core-list">
          {indexFundStatus.map((p) => (
            <CompactCoreRow
              key={p.symbol}
              position={p}
              shortLabel={CORE_SHORT[p.symbol]}
            />
          ))}
        </div>
      </section>
    </PageShell>
  );
};

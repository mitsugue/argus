import React from 'react';
import { PageShell } from './PageShell';
import { HeroCard } from '../components/dashboard/HeroCard';
import { AlertCard } from '../components/dashboard/AlertCard';
import { EventRow } from '../components/dashboard/EventRow';
import { CoreRow } from '../components/dashboard/CoreRow';
import { WatchRow } from '../components/dashboard/WatchRow';
import {
  actionAlerts,
  indexFundStatus,
  todayJudgment,
  upcomingEvents,
} from '../mock/dashboard';
import { watchlist } from '../mock/watchlist';
import type { ActionKey } from '../types/action';
import type { RouteKey } from '../components/NavRail';
import '../components/dashboard/Dashboard.css';

interface Props {
  onNavigate: (key: RouteKey) => void;
}

// Daily action priority (per spec): individual stocks → satellites → index.
// Index funds are deliberately separated so they're not visually promoted
// as daily-trade targets.
const SATELLITE_CLASSES = new Set([
  'JP_STOCK', 'US_STOCK', 'GOLD', 'REIT', 'BOND', 'CRYPTO', 'COMMODITY', 'USDJPY',
]);

// Defensive calls first — same ordering used by the Watchlist page so the
// preview here mirrors what the user sees on drill-in.
const URGENCY: Record<ActionKey, number> = {
  EXIT: 0,
  TRIM: 1,
  WAIT_FOR_PULLBACK: 2,
  WAIT: 3,
  BUY_DIP: 4,
  ADD: 5,
  HOLD: 6,
};

const PREVIEW_LIMIT = 4;

const formatDate = (iso: string) => {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

export const CommandCenter: React.FC<Props> = ({ onNavigate }) => {
  const satellites = actionAlerts.filter((a) => SATELLITE_CLASSES.has(a.assetClass));
  const events = upcomingEvents.slice().sort((a, b) => a.at - b.at).slice(0, 4);
  const priority = watchlist
    .slice()
    .sort((a, b) => URGENCY[a.action as ActionKey] - URGENCY[b.action as ActionKey])
    .slice(0, PREVIEW_LIMIT);

  return (
    <PageShell title="Daily Command Center" subtitle={formatDate(todayJudgment.date)}>
      <HeroCard judgment={todayJudgment} />

      <section>
        <div className="section-head">
          <span className="section-head__title">Action Alerts</span>
          <span className="section-head__count">
            {satellites.length} satellite classes
          </span>
        </div>
        <div className="alert-grid">
          {satellites.map((c) => (
            <AlertCard key={c.assetClass} card={c} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Priority watchlist</span>
          <button
            className="section-head__link"
            onClick={() => onNavigate('watchlist')}
          >
            {priority.length} of {watchlist.length} names · view all
          </button>
        </div>
        <div className="card watch-list">
          {priority.map((row) => (
            <WatchRow key={row.symbol} entry={row} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Event Radar</span>
          <button
            className="section-head__link"
            onClick={() => onNavigate('events')}
          >
            next {events.length} events
          </button>
        </div>
        <div className="card event-list">
          {events.map((e) => (
            <EventRow key={e.id} event={e} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Core Portfolio</span>
          <button
            className="section-head__link"
            onClick={() => onNavigate('core')}
          >
            {indexFundStatus.length} positions
          </button>
        </div>
        <div className="card core-list">
          {indexFundStatus.map((p) => (
            <CoreRow key={p.symbol} position={p} />
          ))}
        </div>
      </section>
    </PageShell>
  );
};

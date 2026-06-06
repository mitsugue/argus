import React from 'react';
import { PageShell } from './PageShell';
import { HeroCard } from '../components/dashboard/HeroCard';
import { AlertCard } from '../components/dashboard/AlertCard';
import { EventRow } from '../components/dashboard/EventRow';
import { CoreRow } from '../components/dashboard/CoreRow';
import {
  actionAlerts,
  indexFundStatus,
  todayJudgment,
  upcomingEvents,
} from '../mock/dashboard';
import '../components/dashboard/Dashboard.css';

// Daily action priority (per spec): individual stocks → satellites → index.
// Index funds are deliberately separated below so they're not visually
// promoted as daily-trade targets.
const SATELLITE_CLASSES = new Set([
  'JP_STOCK',
  'US_STOCK',
  'GOLD',
  'REIT',
  'BOND',
  'CRYPTO',
  'COMMODITY',
  'USDJPY',
]);

const formatDate = (iso: string) => {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

export const CommandCenter: React.FC = () => {
  const satellites = actionAlerts.filter((a) => SATELLITE_CLASSES.has(a.assetClass));
  const events = upcomingEvents.slice().sort((a, b) => a.at - b.at).slice(0, 4);

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
          <span className="section-head__title">Event Radar</span>
          <span className="section-head__count">
            next {events.length} events
          </span>
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
          <span className="section-head__count">
            {indexFundStatus.length} positions
          </span>
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

import React from 'react';
import type { RiskLevel } from '../types/action';
import './AppShell.css';

interface NextEvent {
  title: string;       // short event title
  kind: string;        // CPI / FOMC / BOJ ...
  daysAway: number;    // 0 = today, 1 = tomorrow
  impact: RiskLevel;
  onClick?: () => void;
}

interface Props {
  sidebar: React.ReactNode;
  children: React.ReactNode;
  lastUpdated: Date;
  nextEvent?: NextEvent;
}

const IMPACT_COLOR: Record<RiskLevel, string> = {
  low:     'var(--risk-low)',
  med:     'var(--risk-med)',
  high:    'var(--risk-high)',
  extreme: 'var(--risk-extreme)',
};

function formatLastUpdated(d: Date): string {
  const now = new Date();
  const diff = Math.max(0, now.getTime() - d.getTime());
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatDaysAway(days: number): string {
  if (days === 0) return 'today';
  if (days === 1) return 'in 1d';
  if (days < 0) return `${-days}d ago`;
  return `in ${days}d`;
}

// Slim header (brand + next event + status + last-updated) on top,
// sidebar + main below. No clock, no UPLINK MOCK, no crosshairs.
export const AppShell: React.FC<Props> = ({ sidebar, children, lastUpdated, nextEvent }) => {
  return (
    <div className="shell">
      <header className="shell__header">
        <div className="shell__brand">
          <span className="shell__brand-name">A.R.G.U.S.</span>
          <span className="shell__brand-tag">
            Autonomous Risk and Global Uncertainty Scanner
          </span>
        </div>
        <div className="shell__meta">
          {nextEvent && (
            <button
              className="shell__next-event"
              onClick={nextEvent.onClick}
              style={{ ['--ne-fg' as string]: IMPACT_COLOR[nextEvent.impact] }}
              aria-label={`Next event: ${nextEvent.title}, ${formatDaysAway(nextEvent.daysAway)}`}
            >
              <span className="shell__next-event-dot" />
              <span className="shell__next-event-label">Next</span>
              {nextEvent.kind}
              <span className="shell__next-event-when">· {formatDaysAway(nextEvent.daysAway)}</span>
            </button>
          )}
          <span className="shell__status">Market Open</span>
          <span className="shell__updated">
            <span className="shell__updated-label">Updated</span>
            {formatLastUpdated(lastUpdated)}
          </span>
        </div>
      </header>
      <div className="shell__body">
        {sidebar}
        <main className="shell__main">{children}</main>
      </div>
    </div>
  );
};

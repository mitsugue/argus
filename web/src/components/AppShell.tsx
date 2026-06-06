import React from 'react';
import './AppShell.css';

interface Props {
  sidebar: React.ReactNode;
  children: React.ReactNode;
  // ISO timestamp of the most recent judgment refresh — formatted in-place.
  lastUpdated: Date;
}

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

// Slim header (brand + status + last-updated) on top, sidebar + main below.
// No clock, no "UPLINK MOCK", no crosshairs, no terminal ornaments.
export const AppShell: React.FC<Props> = ({ sidebar, children, lastUpdated }) => {
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

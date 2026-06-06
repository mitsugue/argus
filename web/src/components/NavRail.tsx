import React from 'react';
import './NavRail.css';

export type RouteKey =
  | 'command'
  | 'alerts'
  | 'regime'
  | 'events'
  | 'watchlist'
  | 'core';

interface NavItem {
  key: RouteKey;
  label: string;
}

const NAV: NavItem[] = [
  { key: 'command',   label: 'Today' },
  { key: 'alerts',    label: 'Action Alerts' },
  { key: 'regime',    label: 'Market Regime' },
  { key: 'events',    label: 'Event Radar' },
  { key: 'watchlist', label: 'Watchlist' },
  { key: 'core',      label: 'Core Portfolio' },
];

interface Props {
  active: RouteKey;
  onSelect: (key: RouteKey) => void;
}

export const NavRail: React.FC<Props> = ({ active, onSelect }) => {
  return (
    <nav className="nav" aria-label="Sections">
      <div className="nav__group-label">Workspace</div>
      {NAV.map((n) => (
        <button
          key={n.key}
          className={`nav__btn ${active === n.key ? 'is-active' : ''}`}
          onClick={() => onSelect(n.key)}
          aria-current={active === n.key ? 'page' : undefined}
        >
          <span className="nav__dot" aria-hidden />
          {n.label}
        </button>
      ))}
    </nav>
  );
};

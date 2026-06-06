import React from 'react';
import { ActionPill } from './action/ActionBadge';
import type { ActionKey, RiskLevel } from '../types/action';
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
  // The headline judgment — pinned at the top so it stays visible across
  // every page. Clicking jumps back to the Command Center.
  todayCall: { action: ActionKey; risk: RiskLevel };
}

export const NavRail: React.FC<Props> = ({ active, onSelect, todayCall }) => {
  return (
    <nav className="nav" aria-label="Sections">
      <button
        className="nav__today"
        onClick={() => onSelect('command')}
        aria-label="Jump to today's command center"
      >
        <span className="nav__today-label">Today's call</span>
        <ActionPill action={todayCall.action} />
      </button>

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

      <div className="nav__footer">
        <span className="nav__footer-dot" />
        <span>v{__APP_VERSION__}</span>
      </div>
    </nav>
  );
};

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
  // null when the user is on the (hidden) AI Review route — no main item is "active" then
  active: RouteKey | null;
  onSelect: (key: RouteKey) => void;
  todayCall: { action: ActionKey; risk: RiskLevel };
  onReviewLink?: () => void;
  isReview?: boolean;
}

export const NavRail: React.FC<Props> = ({
  active,
  onSelect,
  todayCall,
  onReviewLink,
  isReview,
}) => {
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
        {onReviewLink && (
          <button
            className={`nav__review-link ${isReview ? 'is-active' : ''}`}
            onClick={onReviewLink}
            title="Open the AI review sheet"
          >
            AI review
          </button>
        )}
      </div>
    </nav>
  );
};

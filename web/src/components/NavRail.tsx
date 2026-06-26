import React from 'react';
import './NavRail.css';

// Page/door titles are ALWAYS English (owner spec) — Japanese is reserved for the
// in-page explanatory text, not the nav. So the nav renders the English NAV labels
// directly (no locale lookup).

export type RouteKey =
  | 'command'
  | 'regime'
  | 'watchlist'
  | 'core'
  | 'guide';

interface NavItem {
  key: RouteKey;
  label: string;
}

// Order = the user's decision flow (2026-06-13): 1) Today = whole-market
// grasp, 2) Watchlist = individual entries (⚡ entry scout lives here),
// 3+) everything else is supporting information.
const NAV: NavItem[] = [
  { key: 'command',   label: 'Today' },
  { key: 'watchlist', label: 'Watchlist' },
  { key: 'regime',    label: 'Market Context' },
  { key: 'core',      label: 'Core Portfolio' },
];

interface Props {
  // null when the user is on the (hidden) AI Review route — no main item is "active" then
  active: RouteKey | null;
  onSelect: (key: RouteKey) => void;
  onReviewLink?: () => void;
  isReview?: boolean;
}

export const NavRail: React.FC<Props> = ({
  active,
  onSelect,
  onReviewLink,
  isReview,
}) => {
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

      <button
        className={`nav__btn nav__btn--guide ${active === 'guide' ? 'is-active' : ''}`}
        onClick={() => onSelect('guide')}
        aria-current={active === 'guide' ? 'page' : undefined}
      >
        <span className="nav__dot" aria-hidden />
        Guide
      </button>

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

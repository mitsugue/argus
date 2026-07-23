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
  | 'backup'
  | 'quality'
  | 'guide';

interface NavItem {
  key: RouteKey;
  label: string;
}

// Order = the professional decision flow (V12.2.12): 1) Today = stance/changes/
// actions, 2) Asset Desk = per-asset judgment + evidence (the single canonical
// per-stock page, ex-Watchlist), 3) Positions & Risk = portfolio-wide meaning,
// 4) Market Context = the backdrop. Route keys are UNCHANGED
// (command/watchlist/core/regime) — only labels and order are display concerns.
const NAV: NavItem[] = [
  { key: 'command',   label: 'Today' },
  { key: 'watchlist', label: 'Asset Desk' },
  { key: 'core',      label: 'Positions & Risk' },
  { key: 'regime',    label: 'Market Context' },
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
      <div className="nav__desktop">
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

      {/* v11.19.1 (owner request): backup operations consolidated on ONE page,
          placed at the bottom group next to Guide. */}
      <button
        className={`nav__btn nav__btn--backup ${active === 'backup' ? 'is-active' : ''}`}
        onClick={() => onSelect('backup')}
        aria-current={active === 'backup' ? 'page' : undefined}
      >
        <span className="nav__dot" aria-hidden />
        Backup
      </button>

      {/* v11.22.0: Data Quality — 運用点検ページ(下段グループ・Backupの下) */}
      <button
        className={`nav__btn nav__btn--guide ${active === 'quality' ? 'is-active' : ''}`}
        onClick={() => onSelect('quality')}
        aria-current={active === 'quality' ? 'page' : undefined}
      >
        <span className="nav__dot" aria-hidden />
        Data Quality
      </button>

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
      </div>

      <div className="nav__mobile" aria-label="Mobile sections">
        <button className={`nav__mobile-btn ${active === 'command' ? 'is-active' : ''}`}
          onClick={() => onSelect('command')}><span className="nav__mobile-dot" />Today</button>
        <button className={`nav__mobile-btn ${active === 'regime' ? 'is-active' : ''}`}
          onClick={() => onSelect('regime')}><span className="nav__mobile-dot" />Market</button>
        <button className={`nav__mobile-btn ${active === 'watchlist' || active === 'core' ? 'is-active' : ''}`}
          onClick={() => onSelect('watchlist')}><span className="nav__mobile-dot" />Assets</button>
        <button className={`nav__mobile-btn ${isReview ? 'is-active' : ''}`}
          onClick={onReviewLink}><span className="nav__mobile-dot" />Review</button>
        <details className={`nav__mobile-system ${active === 'quality' || active === 'backup' || active === 'guide' ? 'is-active' : ''}`}>
          <summary className="nav__mobile-btn"><span className="nav__mobile-dot" />System</summary>
          <div className="nav__mobile-system-menu">
            <button onClick={() => onSelect('quality')}>Data Quality</button>
            <button onClick={() => onSelect('backup')}>Backup</button>
            <button onClick={() => onSelect('guide')}>Guide</button>
          </div>
        </details>
      </div>
    </nav>
  );
};

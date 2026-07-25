import React from 'react';
import {
  PRIMARY_NAVIGATION, SYSTEM_NAVIGATION, type RouteKey,
} from '../navigation';
import './NavRail.css';

// Page/door titles are ALWAYS English (owner spec) — Japanese is reserved for the
// in-page explanatory text, not the nav. So the nav renders the English NAV labels
// directly (no locale lookup).

export type { RouteKey } from '../navigation';

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
        {PRIMARY_NAVIGATION.map((item) => (
        <button
          key={item.route}
          className={`nav__btn ${active === item.route ? 'is-active' : ''}`}
          onClick={() => onSelect(item.route)}
          aria-current={active === item.route ? 'page' : undefined}
        >
          <span className="nav__dot" aria-hidden />
          {item.desktopLabel}
        </button>
        ))}

      {SYSTEM_NAVIGATION.map((item, index) => <button
        key={item.route}
        className={`nav__btn ${index === 0 ? 'nav__btn--backup' : 'nav__btn--guide'} ${active === item.route ? 'is-active' : ''}`}
        onClick={() => onSelect(item.route)}
        aria-current={active === item.route ? 'page' : undefined}
      >
        <span className="nav__dot" aria-hidden />
        {item.desktopLabel}
      </button>)}

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
        {PRIMARY_NAVIGATION.map((item) => <button key={item.route}
          className={`nav__mobile-btn ${active === item.route ? 'is-active' : ''}`}
          onClick={() => onSelect(item.route)}
          aria-current={active === item.route ? 'page' : undefined}>
          <span className="nav__mobile-dot" />{item.mobileLabel}
        </button>)}
        <details className={`nav__mobile-system ${SYSTEM_NAVIGATION.some((item) => item.route === active) ? 'is-active' : ''}`}>
          <summary className="nav__mobile-btn"><span className="nav__mobile-dot" />System</summary>
          <div className="nav__mobile-system-menu">
            {SYSTEM_NAVIGATION.map((item) => <button key={item.route}
              onClick={() => onSelect(item.route)}>{item.mobileLabel}</button>)}
          </div>
        </details>
      </div>
    </nav>
  );
};

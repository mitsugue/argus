import React from 'react';
import {
  PRIMARY_NAVIGATION, type RouteKey,
} from '../navigation';
import './NavRail.css';

// Page/door titles are ALWAYS English (owner spec) — Japanese is reserved for the
// in-page explanatory text, not the nav. So the nav renders the English NAV labels
// directly (no locale lookup).

export type { RouteKey } from '../navigation';

interface Props {
  // null on contextual/support routes — no workspace item is falsely active.
  active: RouteKey | null;
  onSelect: (key: RouteKey) => void;
}

export const NavRail: React.FC<Props> = ({ active, onSelect }) => {
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
      </div>

      <div className="nav__mobile" aria-label="Mobile sections">
        {PRIMARY_NAVIGATION.map((item) => <button key={item.route}
          className={`nav__mobile-btn ${active === item.route ? 'is-active' : ''}`}
          onClick={() => onSelect(item.route)}
          aria-current={active === item.route ? 'page' : undefined}>
          <span className="nav__mobile-dot" />{item.mobileLabel}
        </button>)}
      </div>
    </nav>
  );
};

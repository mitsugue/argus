import React from 'react';
import { ActionPill } from './action/ActionBadge';
import type { ActionKey, RiskLevel } from '../types/action';
import { useLocale, t, type DictKey } from '../i18n';
import './NavRail.css';

const NAV_KEY: Record<string, DictKey> = {
  command: 'nav.today', watchlist: 'nav.watchlist', regime: 'nav.marketContext', core: 'nav.corePortfolio',
};

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
  useLocale();   // re-render on locale switch
  return (
    <nav className="nav" aria-label="Sections">
      <button
        className="nav__today"
        onClick={() => onSelect('command')}
        aria-label="Jump to today's command center"
      >
        <span className="nav__today-label">{t('nav.todaysCall')}</span>
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
          {t(NAV_KEY[n.key] ?? 'nav.today')}
        </button>
      ))}

      <button
        className={`nav__btn nav__btn--guide ${active === 'guide' ? 'is-active' : ''}`}
        onClick={() => onSelect('guide')}
        aria-current={active === 'guide' ? 'page' : undefined}
      >
        <span className="nav__dot" aria-hidden />
        {t('nav.guide')}
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

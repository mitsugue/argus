import React from 'react';
import './NavRail.css';

// Six top-level routes. State-based (no react-router) — single source of
// truth in App.tsx.
export type RouteKey = 'command' | 'alerts' | 'regime' | 'events' | 'watchlist' | 'core';

interface NavItem {
  key: RouteKey;
  glyph: string;   // single-glyph icon, command-center mono
  jp: string;      // 2-char JP label
}

const NAV: NavItem[] = [
  { key: 'command',   glyph: '◉', jp: '司令' },
  { key: 'alerts',    glyph: '!', jp: '通報' },
  { key: 'regime',    glyph: '◐', jp: '相場' },
  { key: 'events',    glyph: '⌖', jp: '事象' },
  { key: 'watchlist', glyph: '◇', jp: '監視' },
  { key: 'core',      glyph: '∞', jp: '基盤' },
];

interface Props {
  active: RouteKey;
  onSelect: (key: RouteKey) => void;
}

export const NavRail: React.FC<Props> = ({ active, onSelect }) => {
  return (
    <nav className="nav-rail" aria-label="Sections">
      {NAV.map((n) => (
        <button
          key={n.key}
          className={`nav-rail__btn ${active === n.key ? 'is-active' : ''}`}
          onClick={() => onSelect(n.key)}
          aria-label={n.jp}
          aria-pressed={active === n.key}
        >
          <span className="nav-rail__glyph">{n.glyph}</span>
          <span className="nav-rail__label">{n.jp}</span>
        </button>
      ))}
    </nav>
  );
};

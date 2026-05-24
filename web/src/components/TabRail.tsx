import React from 'react';
import './TabRail.css';

export type TabKey = 'news' | 'calibration' | 'hotspots' | 'watch';

interface Tab {
  key: TabKey;
  glyph: string;
  label: string;
}

const TABS: Tab[] = [
  { key: 'news',        glyph: 'N', label: 'NEWS' },
  { key: 'calibration', glyph: 'C', label: 'CALIB' },
  { key: 'hotspots',    glyph: 'H', label: 'HOTSPOTS' },
  { key: 'watch',       glyph: 'A', label: 'AI WATCH' },
];

interface Props {
  active: TabKey | null;
  onToggle: (key: TabKey) => void;
}

/**
 * Floating vertical tab strip pinned to the right edge of the bubble canvas.
 * Tapping a tab toggles its overlay; tapping the active tab again closes it.
 */
export const TabRail: React.FC<Props> = ({ active, onToggle }) => {
  return (
    <nav className="tab-rail" aria-label="Panel tabs">
      {TABS.map((t) => (
        <button
          key={t.key}
          className={`tab-rail__btn ${active === t.key ? 'is-active' : ''}`}
          onClick={() => onToggle(t.key)}
          aria-label={t.label}
          aria-pressed={active === t.key}
        >
          <span className="tab-rail__glyph">{t.glyph}</span>
          <span className="tab-rail__label">{t.label}</span>
        </button>
      ))}
    </nav>
  );
};

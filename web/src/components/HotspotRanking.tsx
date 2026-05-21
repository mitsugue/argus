import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import type { GlobePillar } from '../types';
import { flag } from '../util/flag';
import './HotspotRanking.css';

const COLOR_VAR: Record<GlobePillar['color'], string> = {
  cyan: 'var(--hud-cyan)',
  amber: 'var(--hud-amber)',
  danger: 'var(--hud-danger)',
};

interface Props {
  pillars: GlobePillar[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  limit?: number;
}

export const HotspotRanking: React.FC<Props> = ({
  pillars,
  selectedId,
  onSelect,
  limit = 6,
}) => {
  const ranked = useMemo(
    () => [...pillars].sort((a, b) => b.intensity - a.intensity).slice(0, limit),
    [pillars, limit]
  );

  return (
    <section className="hotspots hud-corner">
      <div className="hotspots__head">
        <span className="hud-panel__title">HOTSPOTS</span>
        <span className="hotspots__sub">TOP {ranked.length}</span>
      </div>
      <div className="hotspots__list">
        {ranked.map((p, i) => {
          const active = p.id === selectedId;
          return (
            <button
              key={p.id}
              onClick={() => onSelect(p.id)}
              className={`hotspot ${active ? 'is-active' : ''}`}
            >
              <span className="hotspot__rank">{String(i + 1).padStart(2, '0')}</span>
              <span className="hotspot__flag">{flag(p.countryCode)}</span>
              <span className="hotspot__label">{p.label}</span>
              <span className="hotspot__bar-wrap">
                <motion.span
                  className="hotspot__bar"
                  initial={false}
                  animate={{ width: `${p.intensity * 100}%` }}
                  transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                  style={{ background: COLOR_VAR[p.color] }}
                />
              </span>
              <span
                className="hotspot__pct"
                style={{ color: COLOR_VAR[p.color] }}
              >
                {Math.round(p.intensity * 100)}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
};

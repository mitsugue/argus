import React, { useEffect, useMemo, useRef } from 'react';
import { motion } from 'framer-motion';
import type { GlobePillar } from '../types';
import { flag } from '../util/flag';
import './NewsFeed.css';

const COLOR_VAR: Record<GlobePillar['color'], string> = {
  cyan: 'var(--hud-cyan)',
  amber: 'var(--hud-amber)',
  danger: 'var(--hud-danger)',
};

interface Props {
  pillars: GlobePillar[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export const NewsFeed: React.FC<Props> = ({ pillars, selectedId, onSelect }) => {
  const items = useMemo(
    () => [...pillars].sort((a, b) => b.intensity - a.intensity),
    [pillars]
  );

  // Auto-scroll selected into view
  const listRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!selectedId) return;
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-id="${selectedId}"]`
    );
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selectedId]);

  return (
    <section className="news-feed hud-corner">
      <div className="news-feed__head">
        <span className="hud-panel__title">NEWS FEED</span>
        <span className="news-feed__count">{items.length}</span>
      </div>
      <div className="news-feed__list" ref={listRef}>
        {items.map((p) => {
          const active = p.id === selectedId;
          return (
            <button
              key={p.id}
              data-id={p.id}
              onClick={() => onSelect(p.id)}
              className={`news-item ${active ? 'is-active' : ''}`}
              style={{ borderLeftColor: COLOR_VAR[p.color] }}
            >
              <div className="news-item__row">
                <span className="news-item__flag">{flag(p.countryCode)}</span>
                <span className="news-item__country">{p.country}</span>
                <span className="news-item__src">{p.source}</span>
                <span
                  className="news-item__int"
                  style={{ color: COLOR_VAR[p.color] }}
                >
                  {Math.round(p.intensity * 100)}
                </span>
              </div>
              <div className="news-item__head">{p.headline}</div>
              <motion.div
                className="news-item__bar"
                initial={false}
                animate={{ width: `${p.intensity * 100}%` }}
                transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                style={{ background: COLOR_VAR[p.color] }}
              />
            </button>
          );
        })}
      </div>
    </section>
  );
};

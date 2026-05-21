import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { NewsEvent } from '../types';
import { flag } from '../util/flag';
import './NewsStream.css';

interface Props {
  events: NewsEvent[];
  onSelect?: (pillarId: string) => void;
  selectedPillarId?: string | null;
}

const formatTime = (ms: number) => {
  const d = new Date(ms);
  return (
    String(d.getHours()).padStart(2, '0') +
    ':' +
    String(d.getMinutes()).padStart(2, '0') +
    ':' +
    String(d.getSeconds()).padStart(2, '0')
  );
};

const itemTransition = { type: 'spring' as const, stiffness: 320, damping: 30 };

export const NewsStream: React.FC<Props> = ({ events, onSelect, selectedPillarId }) => {
  return (
    <section className="news-stream hud-corner">
      <header className="news-stream__head">
        <span className="news-stream__title">
          <span className="news-stream__beacon" />
          NEWS · LIVE
        </span>
        <span className="news-stream__count">{events.length} / 5</span>
      </header>

      <div className="news-stream__list">
        <AnimatePresence initial={false} mode="popLayout">
          {events.map((e) => {
            const active = selectedPillarId === e.pillarId;
            return (
              <motion.button
                key={e.id}
                layout
                onClick={() => onSelect?.(e.pillarId)}
                initial={{ y: -28, opacity: 0, filter: 'blur(4px)' }}
                animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
                exit={{
                  y: 18,
                  opacity: 0,
                  filter: 'blur(4px)',
                  transition: { duration: 0.45, ease: 'easeIn' },
                }}
                transition={itemTransition}
                className={
                  'news-stream__item news-stream__item--' +
                  e.severity +
                  (active ? ' is-active' : '')
                }
              >
                <div className="news-stream__row">
                  <span className="news-stream__flag">{flag(e.countryCode)}</span>
                  <span className="news-stream__country">{e.country}</span>
                  <span className="news-stream__src">{e.source}</span>
                  <span className="news-stream__ts">{formatTime(e.receivedAt)}</span>
                </div>
                <div className="news-stream__headline">{e.headline}</div>
                <motion.div
                  className="news-stream__bar"
                  initial={{ scaleX: 1 }}
                  animate={{ scaleX: 0 }}
                  transition={{ duration: 12, ease: 'linear' }}
                />
              </motion.button>
            );
          })}
        </AnimatePresence>

        {events.length === 0 && (
          <div className="news-stream__empty">incoming feed…</div>
        )}
      </div>
    </section>
  );
};

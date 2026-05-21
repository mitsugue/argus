import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion, type PanInfo } from 'framer-motion';
import type { AlertItem } from '../types';
import { randomAlert } from '../mock/data';
import './AlertSystem.css';

const AUTO_DISMISS_MS = 7000;
const MAX_VISIBLE = 2;

export const AlertSystem: React.FC = () => {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);

  // Spawn alerts at intervals
  useEffect(() => {
    setAlerts([randomAlert()]);
    const t = setInterval(() => {
      setAlerts((prev) => [randomAlert(), ...prev].slice(0, MAX_VISIBLE));
    }, 5500);
    return () => clearInterval(t);
  }, []);

  // Auto-dismiss per alert: each alert sets its own expiry based on createdAt
  useEffect(() => {
    if (!alerts.length) return;
    const now = Date.now();
    const timers = alerts.map((a) => {
      const remaining = Math.max(500, a.createdAt + AUTO_DISMISS_MS - now);
      return setTimeout(() => {
        setAlerts((prev) => prev.filter((x) => x.id !== a.id));
      }, remaining);
    });
    return () => timers.forEach(clearTimeout);
  }, [alerts]);

  const dismiss = (id: string) => setAlerts((prev) => prev.filter((a) => a.id !== id));

  const onDragEnd = (id: string) => (_: unknown, info: PanInfo) => {
    if (Math.abs(info.offset.x) > 80 || Math.abs(info.velocity.x) > 350) {
      dismiss(id);
    }
  };

  return (
    <div className="alerts">
      <AnimatePresence initial={false}>
        {alerts.map((a) => (
          <motion.div
            key={a.id}
            className={`alert alert--${a.severity}`}
            layout
            initial={{ y: -40, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -40, opacity: 0, transition: { duration: 0.25 } }}
            transition={{ type: 'spring', stiffness: 280, damping: 28 }}
            drag="x"
            dragConstraints={{ left: -40, right: 40 }}
            dragElastic={0.4}
            onDragEnd={onDragEnd(a.id)}
          >
            <div className="alert__bracket alert__bracket--l" />
            <div className="alert__bracket alert__bracket--r" />
            <div className="alert__head">
              <span className="alert__sev">{a.severity.toUpperCase()}</span>
              <span className="alert__sym">{a.symbol}</span>
              <button className="alert__close" onClick={() => dismiss(a.id)} aria-label="close">
                ×
              </button>
            </div>
            <div className="alert__title">{a.title}</div>
            <div className="alert__detail">{a.detail}</div>
            <motion.div
              className="alert__timer"
              initial={{ scaleX: 1 }}
              animate={{ scaleX: 0 }}
              transition={{ duration: AUTO_DISMISS_MS / 1000, ease: 'linear' }}
            />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

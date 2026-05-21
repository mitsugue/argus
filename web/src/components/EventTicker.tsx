import React, { useEffect, useState } from 'react';
import './EventTicker.css';

const SEEDS = [
  '[OK] J-Quants daily quotes synced · 4,021 stocks',
  '[INFO] Sentinel: no anomaly in last 5 minutes',
  '[OK] Catalyst score recomputed for 184 stocks',
  '[WARN] Twitter buzz threshold passed for $NVDA',
  '[OK] VWAP reclaim detected · 7203',
  '[INFO] FOMC minutes parsed · hawkish bias',
  '[OK] News crawler: 312 headlines / 14 outlets',
  '[INFO] Volatility regime: low (VIX < 15)',
  '[OK] Cross-market correlation matrix refreshed',
  '[WARN] Liquidity drain detected on small-caps',
];

export const EventTicker: React.FC = () => {
  const [lines, setLines] = useState<string[]>(SEEDS);
  useEffect(() => {
    const t = setInterval(() => {
      const ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
      const pick = SEEDS[Math.floor(Math.random() * SEEDS.length)];
      setLines((prev) => [`${ts} · ${pick}`, ...prev].slice(0, 25));
    }, 2200);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="event-ticker hud-corner">
      <span className="event-ticker__brand">EVENTS</span>
      <div className="event-ticker__rail">
        {lines.concat(lines).map((l, i) => (
          <span key={i} className="event-ticker__line">
            <span className="event-ticker__dot">›</span>
            {l}
          </span>
        ))}
      </div>
    </div>
  );
};

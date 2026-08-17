import React from 'react';
import './EventTicker.css';

// Static feed — pure horizontal slide, no in-place text mutation.
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
  return (
    <div className="event-ticker hud-corner">
      <span className="event-ticker__brand">EVENTS</span>
      <div className="event-ticker__rail">
        <div className="event-ticker__track">
          {SEEDS.concat(SEEDS).map((l, i) => (
            <span key={i} className="event-ticker__line">
              <span className="event-ticker__dot">›</span>
              {l}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

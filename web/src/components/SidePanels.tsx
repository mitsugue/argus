import React, { useEffect, useState } from 'react';
import './SidePanels.css';

const METRIC_SEED = [
  { label: 'VIX', value: 14.2, fmt: (n: number) => n.toFixed(2) },
  { label: 'S&P 500', value: 5872.4, fmt: (n: number) => n.toFixed(1) },
  { label: 'USD/JPY', value: 153.6, fmt: (n: number) => n.toFixed(2) },
  { label: 'BTC', value: 96420, fmt: (n: number) => Math.round(n).toLocaleString() },
];

export const MarketReadout: React.FC = () => {
  const [vals, setVals] = useState(METRIC_SEED.map((m) => m.value));
  useEffect(() => {
    const t = setInterval(() => {
      setVals((prev) =>
        prev.map((v, i) => {
          const noise = (Math.random() - 0.5) * v * 0.003;
          return +(v + noise).toFixed(4);
        })
      );
    }, 1100);
    return () => clearInterval(t);
  }, []);

  return (
    <section className="side-panel hud-panel hud-corner">
      <div className="hud-panel__title">MARKET PULSE</div>
      <div className="side-panel__grid">
        {METRIC_SEED.map((m, i) => (
          <div key={m.label} className="metric">
            <div className="metric__label">{m.label}</div>
            <div className="metric__value">{m.fmt(vals[i])}</div>
            <div className="metric__spark">
              {Array.from({ length: 20 }).map((_, j) => (
                <span
                  key={j}
                  style={{ height: `${20 + Math.sin((Date.now() / 600 + j * 0.5 + i) % 100) * 25 + Math.random() * 35}%` }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

const PHASES = [
  { code: 'Ph.1', name: 'BROAD', done: true },
  { code: 'Ph.2', name: 'RESCORE', done: true },
  { code: 'Ph.3', name: 'CROSS', done: true },
  { code: 'Ph.4', name: 'FINAL', done: false, active: true },
  { code: 'Ph.5', name: 'POST-OPEN', done: false },
];

export const PhasePanel: React.FC = () => {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <section className="side-panel hud-panel hud-corner">
      <div className="hud-panel__title">SCAN PHASE</div>
      <div className="phases">
        {PHASES.map((p) => (
          <div
            key={p.code}
            className={`phase ${p.done ? 'is-done' : ''} ${p.active ? 'is-active' : ''}`}
          >
            <span className="phase__dot" />
            <div className="phase__col">
              <div className="phase__code">{p.code}</div>
              <div className="phase__name">{p.name}</div>
            </div>
            <div className="phase__status">
              {p.done ? '100%' : p.active ? `${(tick * 7) % 100}%` : '——'}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

const LOG_LINES = [
  '[OK] J-Quants daily quotes synced · 4,021 stocks',
  '[INFO] Sentinel: no anomaly in last 5 minutes',
  '[OK] Catalyst score recomputed for 184 stocks',
  '[WARN] Twitter buzz threshold passed for $NVDA',
  '[OK] VWAP reclaim detected · 7203',
  '[INFO] Phase 4 schedule: 09:00 JST',
];

export const LogPanel: React.FC = () => {
  const [lines, setLines] = useState<string[]>(LOG_LINES);
  useEffect(() => {
    const t = setInterval(() => {
      const ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
      const pick = LOG_LINES[Math.floor(Math.random() * LOG_LINES.length)];
      setLines((prev) => [`${ts} ${pick}`, ...prev].slice(0, 40));
    }, 2200);
    return () => clearInterval(t);
  }, []);

  return (
    <section className="side-panel hud-panel hud-corner side-panel--scroll">
      <div className="hud-panel__title">SYSTEM LOG</div>
      <div className="logs">
        {lines.map((l, i) => (
          <div key={i} className="logs__line">
            <span className="logs__dot">›</span> {l}
          </div>
        ))}
      </div>
    </section>
  );
};

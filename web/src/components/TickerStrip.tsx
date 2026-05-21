import React, { useEffect, useState } from 'react';
import './TickerStrip.css';

interface Metric {
  label: string;
  value: number;
  prev: number;
  fmt: (n: number) => string;
}

const SEED: Metric[] = [
  { label: 'VIX', value: 14.2, prev: 14.2, fmt: (n) => n.toFixed(2) },
  { label: 'S&P 500', value: 5872.4, prev: 5872.4, fmt: (n) => n.toFixed(1) },
  { label: 'NASDAQ', value: 18742.1, prev: 18742.1, fmt: (n) => n.toFixed(1) },
  { label: 'DOW', value: 42013.8, prev: 42013.8, fmt: (n) => n.toFixed(0) },
  { label: 'USD/JPY', value: 153.6, prev: 153.6, fmt: (n) => n.toFixed(2) },
  { label: 'EUR/USD', value: 1.083, prev: 1.083, fmt: (n) => n.toFixed(4) },
  { label: 'BTC', value: 96420, prev: 96420, fmt: (n) => Math.round(n).toLocaleString() },
  { label: 'ETH', value: 3284.6, prev: 3284.6, fmt: (n) => n.toFixed(1) },
  { label: 'GOLD', value: 2724.5, prev: 2724.5, fmt: (n) => n.toFixed(1) },
  { label: 'WTI', value: 78.2, prev: 78.2, fmt: (n) => n.toFixed(2) },
  { label: '10Y UST', value: 4.31, prev: 4.31, fmt: (n) => n.toFixed(3) + '%' },
];

export const TickerStrip: React.FC = () => {
  const [metrics, setMetrics] = useState<Metric[]>(SEED);
  useEffect(() => {
    const t = setInterval(() => {
      setMetrics((prev) =>
        prev.map((m) => {
          const noise = (Math.random() - 0.5) * m.value * 0.003;
          return { ...m, prev: m.value, value: +(m.value + noise).toFixed(4) };
        })
      );
    }, 1300);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="ticker-strip hud-corner">
      <span className="ticker-strip__brand">GLOBAL · PULSE</span>
      <div className="ticker-strip__rail">
        <div className="ticker-strip__track">
          {metrics.concat(metrics).map((m, i) => {
            const delta = m.value - m.prev;
            const cls = delta === 0 ? '' : delta > 0 ? 'up' : 'down';
            return (
              <span key={i} className="ticker-strip__item">
                <span className="ticker-strip__lbl">{m.label}</span>
                <span className={`ticker-strip__val ${cls}`}>{m.fmt(m.value)}</span>
                <span className={`ticker-strip__delta ${cls}`}>
                  {delta >= 0 ? '▲' : '▼'}
                </span>
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
};

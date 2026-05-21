import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import type { PredictionEntry } from '../types/calibration';
import { computeStats, generateMockLedger } from '../mock/calibration';
import './CalibrationTracker.css';

const fmtPct = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`;

export const CalibrationTracker: React.FC = () => {
  const [ledger, setLedger] = useState<PredictionEntry[]>(() => generateMockLedger());

  // Periodically nudge — simulates a fresh prediction resolving
  useEffect(() => {
    const t = setInterval(() => {
      setLedger((prev) => {
        const pendingIdx = prev.findIndex((p) => p.outcome === 'pending');
        if (pendingIdx === -1) return prev;
        const updated = [...prev];
        const p = updated[pendingIdx];
        const isHit = Math.random() < p.probability;
        const movePct =
          (p.direction === 'up' ? 1 : -1) *
          (isHit ? 0.6 + Math.random() * 2 : -(0.3 + Math.random() * 1.5));
        updated[pendingIdx] = {
          ...p,
          outcome: isHit ? 'hit' : 'miss',
          resolvedAt: Date.now(),
          movePct: +movePct.toFixed(2),
          priceAtResolution: +(p.priceAtPrediction * (1 + movePct / 100)).toFixed(2),
        };
        return updated;
      });
    }, 4500);
    return () => clearInterval(t);
  }, []);

  const stats = useMemo(() => computeStats(ledger, 30), [ledger]);
  const trend = useMemo(() => trendDelta(stats.dailyHitRate), [stats.dailyHitRate]);
  const recent = useMemo(
    () => ledger.filter((e) => e.outcome !== 'pending').slice(0, 24).reverse(),
    [ledger],
  );

  return (
    <section className="calibration hud-corner">
      <span className="panel-tab">
        CALIBRATION · {stats.windowDays}D · {stats.resolvedCount}R/{stats.pendingCount}P
      </span>

      <div className="calibration__hero">
        <div className="calibration__pct">
          <div className="calibration__pct-val">{fmtPct(stats.hitRate, 1)}</div>
          <div className="calibration__pct-label">HIT RATE</div>
        </div>
        <div className="calibration__metrics">
          <Metric
            label="EXPECTED"
            value={fmtPct(stats.expectedRate, 1)}
            tone="dim"
          />
          <Metric
            label="DELTA"
            value={(trend >= 0 ? '+' : '') + (trend * 100).toFixed(1) + 'pp'}
            tone={trend >= 0 ? 'cyan' : 'amber'}
          />
          <Metric
            label="BRIER"
            value={stats.brierScore.toFixed(3)}
            tone="dim"
          />
        </div>
      </div>

      <Sparkline data={stats.dailyHitRate.map((d) => d.rate)} />

      <div className="calibration__ribbon-wrap">
        <span className="calibration__row-label">RECENT · {recent.length}</span>
        <div className="calibration__ribbon">
          {recent.map((e) => (
            <span
              key={e.id}
              className={`calibration__dot calibration__dot--${e.outcome}`}
              title={`${e.code} ${e.direction} ${fmtPct(e.probability)}`}
            />
          ))}
        </div>
      </div>

      <div className="calibration__curve">
        <span className="calibration__row-label">RELIABILITY</span>
        <svg viewBox="0 0 100 60" preserveAspectRatio="none" className="calibration__curve-svg">
          {/* Diagonal ideal */}
          <line x1="0" y1="60" x2="100" y2="0" stroke="rgba(0,243,255,0.2)" strokeWidth="0.4" strokeDasharray="2 2" />
          {/* Grid */}
          {[0, 25, 50, 75, 100].map((v) => (
            <line key={'h' + v} x1="0" y1={60 - (v / 100) * 60} x2="100" y2={60 - (v / 100) * 60} stroke="rgba(0,243,255,0.08)" strokeWidth="0.3" />
          ))}
          {/* Actual */}
          <polyline
            points={stats.bins
              .map((b, i) => {
                const x = (i + 0.5) * (100 / stats.bins.length);
                const y = 60 - b.actualRate * 60;
                return `${x},${y}`;
              })
              .join(' ')}
            fill="none"
            stroke="var(--hud-cyan)"
            strokeWidth="1.2"
          />
          {stats.bins.map((b, i) => {
            const x = (i + 0.5) * (100 / stats.bins.length);
            const y = 60 - b.actualRate * 60;
            return (
              <circle
                key={i}
                cx={x}
                cy={y}
                r={b.count ? 1.5 + Math.min(2.4, b.count / 12) : 0.8}
                fill={b.count ? 'var(--hud-cyan)' : 'rgba(0,243,255,0.2)'}
              />
            );
          })}
        </svg>
        <div className="calibration__curve-axis">
          <span>PRED 0</span>
          <span>0.5</span>
          <span>1.0</span>
        </div>
      </div>
    </section>
  );
};

const Metric: React.FC<{ label: string; value: string; tone: 'cyan' | 'amber' | 'dim' }> = ({
  label,
  value,
  tone,
}) => (
  <div className={`metric-cell metric-cell--${tone}`}>
    <div className="metric-cell__label">{label}</div>
    <div className="metric-cell__value">{value}</div>
  </div>
);

const Sparkline: React.FC<{ data: number[] }> = ({ data }) => {
  if (!data.length) return null;
  const max = Math.max(...data, 0.6);
  const points = data
    .map((d, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - (d / max) * 100;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  return (
    <div className="calibration__spark">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="calibration__spark-svg">
        <motion.polyline
          initial={false}
          animate={{ points }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          fill="none"
          stroke="var(--hud-cyan)"
          strokeWidth="1.5"
          style={{ filter: 'drop-shadow(0 0 3px rgba(0,243,255,0.5))' }}
        />
        <line x1="0" y1="100" x2="100" y2="100" stroke="rgba(0,243,255,0.15)" strokeWidth="0.6" />
      </svg>
    </div>
  );
};

function trendDelta(daily: Array<{ rate: number; n: number }>): number {
  // Compare first 5 vs last 5 days weighted by n
  const first = daily.slice(0, 5).filter((d) => d.n > 0);
  const last = daily.slice(-5).filter((d) => d.n > 0);
  if (!first.length || !last.length) return 0;
  const avg = (arr: typeof first) =>
    arr.reduce((s, d) => s + d.rate * d.n, 0) / arr.reduce((s, d) => s + d.n, 0);
  return avg(last) - avg(first);
}

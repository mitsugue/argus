import React, { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { TrackedSymbol } from '../types';
import { hitRate, seedSymbols, tickSymbol, uid } from '../mock/data';
import './PredictionTracker.css';

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
const fmtPct = (p: number) => `${(p * 100).toFixed(0)}%`;

const ProgressRing: React.FC<{ value: number; size?: number; stroke?: number; label: string }> = ({
  value,
  size = 96,
  stroke = 6,
  label,
}) => {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - Math.max(0, Math.min(1, value)));
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke="rgba(0,243,255,0.12)"
          strokeWidth={stroke}
          fill="none"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke="var(--hud-cyan)"
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          initial={false}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ filter: 'drop-shadow(0 0 6px rgba(0,243,255,0.6))' }}
        />
        {/* Tick marks */}
        {Array.from({ length: 24 }).map((_, i) => {
          const a = (i / 24) * Math.PI * 2 - Math.PI / 2;
          const x1 = size / 2 + Math.cos(a) * (r + stroke / 2 + 2);
          const y1 = size / 2 + Math.sin(a) * (r + stroke / 2 + 2);
          const x2 = size / 2 + Math.cos(a) * (r + stroke / 2 + 5);
          const y2 = size / 2 + Math.sin(a) * (r + stroke / 2 + 5);
          return (
            <line
              key={i}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke="var(--hud-cyan-faint)"
              strokeWidth={1}
            />
          );
        })}
      </svg>
      <div className="ring__center">
        <div className="ring__value">{fmtPct(value)}</div>
        <div className="ring__label">{label}</div>
      </div>
    </div>
  );
};

export const PredictionTracker: React.FC = () => {
  const [symbols, setSymbols] = useState<TrackedSymbol[]>(() => seedSymbols());
  const [activeIdx, setActiveIdx] = useState(0);
  const [input, setInput] = useState('');

  useEffect(() => {
    const t = setInterval(() => {
      setSymbols((prev) => prev.map(tickSymbol));
    }, 1500);
    return () => clearInterval(t);
  }, []);

  const active = symbols[activeIdx] ?? symbols[0];
  const aggregateHitRate = useMemo(() => {
    const all = symbols.flatMap((s) => s.history);
    if (!all.length) return 0;
    return all.filter((h) => h.hit).length / all.length;
  }, [symbols]);

  const onAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const code = input.trim().toUpperCase();
    if (!code) return;
    if (symbols.some((s) => s.code === code)) {
      setInput('');
      return;
    }
    const base = 100 + Math.random() * 400;
    const predicted = +(base * (1 + (Math.random() * 0.04 - 0.02))).toFixed(2);
    const now = Date.now();
    setSymbols((prev) => [
      ...prev,
      {
        code,
        name: `${code} (Watch)`,
        currentPrice: +base.toFixed(2),
        predictedPrice: predicted,
        actualPrice: null,
        predictedAt: now,
        resolvesAt: now + 10 * 60 * 1000,
        history: [],
      },
    ]);
    setActiveIdx(symbols.length);
    setInput('');
  };

  const onRemove = (code: string) => {
    setSymbols((prev) => prev.filter((s) => s.code !== code));
    setActiveIdx(0);
  };

  if (!active) {
    return (
      <section className="tracker hud-panel hud-corner">
        <div className="hud-panel__title">PREDICTION LOOP</div>
        <form onSubmit={onAdd} className="tracker__add">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="銘柄コード…"
          />
          <button type="submit">+ ADD</button>
        </form>
      </section>
    );
  }

  const remaining = Math.max(0, active.resolvesAt - Date.now());
  const progress = 1 - remaining / (10 * 60 * 1000);
  const diffPct = (active.predictedPrice - active.currentPrice) / active.currentPrice;
  const symbolHit = hitRate(active);

  return (
    <section className="tracker hud-panel hud-corner">
      <div className="tracker__head">
        <span className="hud-panel__title">PREDICTION LOOP</span>
        <span className="tracker__agg">
          AGG HIT <strong>{fmtPct(aggregateHitRate)}</strong>
        </span>
      </div>

      <form onSubmit={onAdd} className="tracker__add">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="銘柄コード (AAPL / 7203...)"
          maxLength={8}
        />
        <button type="submit">+ ADD</button>
      </form>

      <div className="tracker__tabs">
        {symbols.map((s, i) => (
          <button
            key={s.code}
            className={`tracker__tab ${i === activeIdx ? 'is-active' : ''}`}
            onClick={() => setActiveIdx(i)}
          >
            {s.code}
          </button>
        ))}
      </div>

      <div className="tracker__body">
        <ProgressRing value={symbolHit} label="HIT RATE" />

        <div className="tracker__col">
          <div className="tracker__row">
            <span className="hud-label">CURRENT</span>
            <span className="tracker__num">{fmt(active.currentPrice)}</span>
          </div>
          <div className="tracker__row">
            <span className="hud-label">PRED · 10m</span>
            <span
              className="tracker__num tracker__num--accent"
              style={{ color: diffPct >= 0 ? 'var(--hud-cyan)' : 'var(--hud-amber)' }}
            >
              {fmt(active.predictedPrice)}
              <em>{diffPct >= 0 ? '▲' : '▼'} {(diffPct * 100).toFixed(2)}%</em>
            </span>
          </div>
          <div className="tracker__row">
            <span className="hud-label">ACTUAL</span>
            <span className="tracker__num" style={{ color: active.actualPrice ? 'var(--hud-text)' : 'var(--hud-text-faint)' }}>
              {active.actualPrice ? fmt(active.actualPrice) : '—— pending'}
            </span>
          </div>

          <div className="tracker__bar">
            <motion.div
              className="tracker__bar-fill"
              initial={false}
              animate={{ width: `${progress * 100}%` }}
              transition={{ ease: 'linear', duration: 0.4 }}
            />
            <span className="tracker__bar-label">
              T-{Math.ceil(remaining / 1000)}s · resolve
            </span>
          </div>

          <button className="tracker__remove" onClick={() => onRemove(active.code)}>
            × REMOVE {active.code}
          </button>
        </div>
      </div>

      <div className="tracker__history">
        <div className="hud-label" style={{ marginBottom: 4 }}>RECENT · HIT/MISS</div>
        <div className="tracker__history-row">
          <AnimatePresence initial={false}>
            {active.history.slice(-16).map((h) => (
              <motion.span
                key={h.id}
                initial={{ opacity: 0, scaleY: 0 }}
                animate={{ opacity: 1, scaleY: 1 }}
                exit={{ opacity: 0 }}
                className={`tracker__dot ${h.hit ? 'hit' : 'miss'}`}
                title={`${fmt(h.predicted)} → ${fmt(h.actual ?? 0)}`}
              />
            ))}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
};

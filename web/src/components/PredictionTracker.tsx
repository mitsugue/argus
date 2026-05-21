import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import type { TrackedSymbol } from '../types';
import { hitRate, seedSymbols, tickSymbol, uid } from '../mock/data';
import './PredictionTracker.css';

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
const fmtPct = (p: number) => `${(p * 100).toFixed(0)}%`;

const ProgressRing: React.FC<{ value: number; size?: number; stroke?: number; label?: string }> = ({
  value,
  size = 56,
  stroke = 5,
  label,
}) => {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - Math.max(0, Math.min(1, value)));
  return (
    <div className="ring ring--sm" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(0,243,255,0.12)" strokeWidth={stroke} fill="none" />
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
          style={{ filter: 'drop-shadow(0 0 4px rgba(0,243,255,0.45))' }}
        />
      </svg>
      <div className="ring__center">
        <div className="ring__value" style={{ fontSize: size <= 60 ? 11 : 18 }}>
          {fmtPct(value)}
        </div>
        {label && <div className="ring__label">{label}</div>}
      </div>
    </div>
  );
};

export const PredictionTracker: React.FC = () => {
  const [symbols, setSymbols] = useState<TrackedSymbol[]>(() => seedSymbols());
  const [activeCode, setActiveCode] = useState<string | null>(null);
  const [input, setInput] = useState('');

  useEffect(() => {
    const t = setInterval(() => {
      setSymbols((prev) => prev.map(tickSymbol));
    }, 1500);
    return () => clearInterval(t);
  }, []);

  const active =
    symbols.find((s) => s.code === activeCode) ?? symbols[0] ?? null;

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
    setActiveCode(code);
    setInput('');
  };

  const onRemove = (code: string) => {
    setSymbols((prev) => prev.filter((s) => s.code !== code));
    setActiveCode(null);
  };

  return (
    <section className="tracker hud-corner">
      <div className="tracker__head">
        <span className="hud-panel__title">AI WATCH</span>
        <span className="tracker__agg">
          AGG <strong>{fmtPct(aggregateHitRate)}</strong>
        </span>
      </div>

      <form onSubmit={onAdd} className="tracker__add">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="銘柄コード追加…"
          maxLength={8}
        />
        <button type="submit">＋</button>
      </form>

      <div className="tracker__rows">
        {symbols.map((s) => {
          const rate = hitRate(s);
          const diff = (s.predictedPrice - s.currentPrice) / s.currentPrice;
          const isActive = s.code === active?.code;
          return (
            <button
              key={s.code}
              onClick={() => setActiveCode(s.code)}
              className={`watch-row ${isActive ? 'is-active' : ''}`}
            >
              <span className="watch-row__code">{s.code}</span>
              <span className="watch-row__price">{fmt(s.currentPrice)}</span>
              <span
                className="watch-row__diff"
                style={{ color: diff >= 0 ? 'var(--hud-cyan)' : 'var(--hud-amber)' }}
              >
                {diff >= 0 ? '▲' : '▼'}
                {(Math.abs(diff) * 100).toFixed(2)}%
              </span>
              <span className="watch-row__rate">{fmtPct(rate)}</span>
              <span className="watch-row__dots">
                {s.history.slice(-8).map((h) => (
                  <span key={h.id} className={`watch-row__dot ${h.hit ? 'hit' : 'miss'}`} />
                ))}
              </span>
            </button>
          );
        })}
      </div>

      {active && (
        <div className="tracker__detail">
          <ProgressRing value={hitRate(active)} label="HIT" />
          <div className="tracker__detail-col">
            <div className="tracker__detail-row">
              <span className="hud-label">NOW</span>
              <span className="tracker__detail-val">{fmt(active.currentPrice)}</span>
            </div>
            <div className="tracker__detail-row">
              <span className="hud-label">PRED 10M</span>
              <span
                className="tracker__detail-val"
                style={{
                  color:
                    active.predictedPrice >= active.currentPrice
                      ? 'var(--hud-cyan)'
                      : 'var(--hud-amber)',
                }}
              >
                {fmt(active.predictedPrice)}
              </span>
            </div>
            <div className="tracker__detail-row">
              <span className="hud-label">ACT</span>
              <span
                className="tracker__detail-val"
                style={{
                  color: active.actualPrice ? 'var(--hud-text)' : 'var(--hud-text-faint)',
                }}
              >
                {active.actualPrice ? fmt(active.actualPrice) : '— pending'}
              </span>
            </div>
            <button className="tracker__remove" onClick={() => onRemove(active.code)}>
              × REMOVE
            </button>
          </div>
        </div>
      )}
    </section>
  );
};

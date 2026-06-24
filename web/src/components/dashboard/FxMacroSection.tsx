import React from 'react';
import { useRatesSnapshot } from '../../hooks/useRatesSnapshot';
import { SignedValue } from '../common/SignedValue';
import { getMetricTone, TONE_VAR } from '../../lib/numericTone';
import './FxMacroSection.css';

// FX / MACRO (v10.145) — the macro backdrop the per-stock calls hang off:
// USDJPY, US 10Y yield, VIX. Levels (neutral) with a day-change tint where the
// metric's polarity is meaningful (rising VIX = adverse = red, via getMetricTone).
export const FxMacroSection: React.FC = () => {
  const { data } = useRatesSnapshot();
  if (!data) return null;
  const rows = [
    { id: 'usdjpy', label: 'USD/JPY', pt: data.usdJpy, unit: '' },
    { id: 'us10y', label: 'US 10Y', pt: data.us10y, unit: '%' },
    { id: 'vix', label: 'VIX', pt: data.vix, unit: '' },
  ].filter((r) => r.pt);

  // Honesty: most of this is FRED daily (lagged ~1-7 days), NOT realtime like a
  // broker quote. Show the as-of date + a 遅延 tag when stale so the number isn't
  // mistaken for live. USD/JPY uses a realtime source (source==='twelvedata-rt')
  // when available — then no 遅延 tag.
  const todayJst = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  const daysOld = (d?: string) => (d ? Math.round((Date.parse(todayJst) - Date.parse(d)) / 86400000) : 0);

  return (
    <section className="fxm">
      <div className="fxm-head">
        <span className="fxm-title">FX / MACRO</span>
        <span className="fxm-note">USD/JPYはリアルタイム、金利・VIXはFRED日次(数日遅延)</span>
      </div>
      <div className="card fxm-grid">
        {rows.map((r) => {
          const v = r.pt!.latestValue;
          const prev = (r.pt as { previousValue?: number }).previousValue;
          const chg = typeof prev === 'number' && prev !== 0 ? ((v - prev) / Math.abs(prev)) * 100 : null;
          const pt = r.pt as { latestDate?: string; source?: string };
          const rt = pt.source === 'twelvedata-rt';
          const old = daysOld(pt.latestDate);
          return (
            <div className="fxm-cell" key={r.id}>
              <span className="fxm-k">{r.label}</span>
              <span className="fxm-v">{r.unit === '%' ? `${v.toFixed(2)}%` : v.toFixed(2)}</span>
              {chg != null && (
                <span className="fxm-chg" style={{ color: TONE_VAR[getMetricTone(r.id, chg)] }}>
                  <SignedValue value={chg} suffix="%" arrow={false} />
                </span>
              )}
              <span className="fxm-asof">
                {rt ? 'リアルタイム' : pt.latestDate ? `${pt.latestDate}${old >= 1 ? ` ·遅延${old}日` : ''}` : ''}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
};

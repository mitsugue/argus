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

  return (
    <section className="fxm">
      <div className="fxm-head"><span className="fxm-title">FX / MACRO</span></div>
      <div className="card fxm-grid">
        {rows.map((r) => {
          const v = r.pt!.latestValue;
          const prev = (r.pt as { previousValue?: number }).previousValue;
          const chg = typeof prev === 'number' && prev !== 0 ? ((v - prev) / Math.abs(prev)) * 100 : null;
          return (
            <div className="fxm-cell" key={r.id}>
              <span className="fxm-k">{r.label}</span>
              <span className="fxm-v">{r.unit === '%' ? `${v.toFixed(2)}%` : v.toFixed(2)}</span>
              {chg != null && (
                <span className="fxm-chg" style={{ color: TONE_VAR[getMetricTone(r.id, chg)] }}>
                  <SignedValue value={chg} suffix="%" arrow={false} />
                </span>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
};

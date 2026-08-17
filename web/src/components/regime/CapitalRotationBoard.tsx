import React from 'react';
import type { CapitalRotationRow } from '../../types/regime';
import './CapitalRotationBoard.css';

interface Props {
  rows: CapitalRotationRow[];
}

// Color the flow only when it's clearly directional. Near-zero stays
// muted so the eye reads only meaningful moves.
function flowKind(value: number): 'out' | 'in' | 'neutral' {
  if (value <= -20) return 'out';
  if (value >= 20) return 'in';
  return 'neutral';
}

// Map flow value (-100 .. +100) to a percentage along the meter.
function meterLeft(value: number): string {
  const clamped = Math.max(-100, Math.min(100, value));
  return `${((clamped + 100) / 200) * 100}%`;
}

// Cross-asset money-flow reading. Three signals per row: Flow (meter +
// label), Strength, Role. No action labels — those live on Action
// Alerts / Watchlist so this view stays a pure flow diagnostic.
export const CapitalRotationBoard: React.FC<Props> = ({ rows }) => {
  return (
    <div className="card rotation">
      {rows.map((r) => {
        const kind = flowKind(r.flowValue);
        return (
          <div className="rotation__row" key={r.assetClass}>
            <span className="rotation__asset">{r.assetClass}</span>
            <div
              className="rotation__meter"
              role="img"
              aria-label={`${r.flow}, ${r.flowValue}`}
            >
              <span className="rotation__meter-center" aria-hidden />
              <span
                className={`rotation__meter-dot rotation__meter-dot--${kind}`}
                style={{ left: meterLeft(r.flowValue) }}
              />
            </div>
            <span className={`rotation__flow-label rotation__flow-label--${kind}`}>
              {r.flow}
            </span>
            <div className="rotation__chips">
              <span className="rotation__chip">{r.strength}</span>
              <span className="rotation__chip rotation__chip--role">{r.role}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

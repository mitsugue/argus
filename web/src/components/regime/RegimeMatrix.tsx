import React from 'react';
import type { RegimeMatrixState } from '../../types/regime';
import './RegimeMatrix.css';

interface AxisLabels {
  xNeg: string;
  xPos: string;
  yNeg: string;
  yPos: string;
}

interface Props {
  state: RegimeMatrixState;
  /** Render the smaller, quieter variant used as a supporting view
      beneath the Capital Rotation Board. */
  compact?: boolean;
  /** Override the four axis-end labels (defaults to the legacy
      Risk Off/On × Rates Relief/Pressure framing). */
  axisLabels?: AxisLabels;
}

const DEFAULT_AXIS_LABELS: AxisLabels = {
  xNeg: 'Risk Off', xPos: 'Risk On', yNeg: 'Rates Relief', yPos: 'Rates Pressure',
};

// 2-axis classification of the current cross-asset environment.
//   X axis: Risk Off ←→ Risk On
//   Y axis: Rates Relief (bottom) ←→ Rates Pressure (top)
// A.R.G.U.S. classifies; it does not predict. The matrix is a snapshot
// of WHERE the market sits right now, not where it will go.
const W = 400;
const H = 280;
const PAD_L = 36;
const PAD_R = 12;
const PAD_T = 18;
const PAD_B = 24;

// Normalize [-1, 1] coordinate to plot pixel.
function plotX(x: number): number {
  return PAD_L + ((x + 1) / 2) * (W - PAD_L - PAD_R);
}
function plotY(y: number): number {
  // y=+1 (Rates Pressure) → top of plot, y=-1 → bottom
  return PAD_T + ((1 - y) / 2) * (H - PAD_T - PAD_B);
}

export const RegimeMatrix: React.FC<Props> = ({ state, compact = false, axisLabels = DEFAULT_AXIS_LABELS }) => {
  const cx = plotX(state.x);
  const cy = plotY(state.y);
  // Highlight the active quadrant with a faint tint.
  const tintX = state.x < 0 ? PAD_L : plotX(0);
  const tintY = state.y > 0 ? PAD_T : plotY(0);
  const tintW = (W - PAD_L - PAD_R) / 2;
  const tintH = (H - PAD_T - PAD_B) / 2;

  return (
    <div className={`matrix${compact ? ' matrix--compact' : ''}`}>
      <div className="matrix__plot">
        <svg
          className="matrix__svg"
          viewBox={`0 0 ${W} ${H}`}
          xmlns="http://www.w3.org/2000/svg"
          role="img"
          aria-label={`Regime matrix: ${state.quadrantLabel}`}
        >
          {/* Active-quadrant tint */}
          <rect
            className="matrix__quadrant-tint"
            x={tintX}
            y={tintY}
            width={tintW}
            height={tintH}
          />

          {/* Quarter grid (subtle) */}
          <line className="matrix__grid-line"
            x1={plotX(-0.5)} y1={PAD_T} x2={plotX(-0.5)} y2={H - PAD_B} />
          <line className="matrix__grid-line"
            x1={plotX(0.5)} y1={PAD_T} x2={plotX(0.5)} y2={H - PAD_B} />
          <line className="matrix__grid-line"
            x1={PAD_L} y1={plotY(0.5)} x2={W - PAD_R} y2={plotY(0.5)} />
          <line className="matrix__grid-line"
            x1={PAD_L} y1={plotY(-0.5)} x2={W - PAD_R} y2={plotY(-0.5)} />

          {/* Center axes */}
          <line className="matrix__axis-line"
            x1={plotX(0)} y1={PAD_T} x2={plotX(0)} y2={H - PAD_B} />
          <line className="matrix__axis-line"
            x1={PAD_L} y1={plotY(0)} x2={W - PAD_R} y2={plotY(0)} />

          {/* Axis labels. X labels OUTSIDE the plot at the bottom; Y
              labels INSIDE the plot tucked against the Y axis at top
              and bottom so they never collide with the X labels. */}
          <text className="matrix__axis-label"
            x={PAD_L} y={H - 4} textAnchor="start">{axisLabels.xNeg}</text>
          <text className="matrix__axis-label"
            x={W - PAD_R} y={H - 4} textAnchor="end">{axisLabels.xPos}</text>
          <text className="matrix__axis-label"
            x={plotX(0) + 6} y={PAD_T + 12} textAnchor="start">{axisLabels.yPos}</text>
          <text className="matrix__axis-label"
            x={plotX(0) + 6} y={H - PAD_B - 6} textAnchor="start">{axisLabels.yNeg}</text>

          {/* Asset class context dots */}
          {state.assets.map((a) => (
            <g key={a.label}>
              <circle className="matrix__asset-dot"
                cx={plotX(a.x)} cy={plotY(a.y)} r={3} />
              <text className="matrix__asset-label"
                x={plotX(a.x) + 6} y={plotY(a.y) + 3}>{a.label}</text>
            </g>
          ))}

          {/* Current location — larger, accented */}
          <circle className="matrix__current-pulse" cx={cx} cy={cy} r={20} />
          <circle className="matrix__current-ring"  cx={cx} cy={cy} r={11} />
          <circle className="matrix__current-dot"   cx={cx} cy={cy} r={5.5} />
        </svg>
      </div>

      <aside className="matrix__sidebar">
        <div className="matrix__sidebar-row">
          <span className="matrix__sidebar-label">Current location</span>
          <span className="matrix__sidebar-value">{state.quadrantLabel}</span>
        </div>
        <div className="matrix__sidebar-row">
          <span className="matrix__sidebar-label">Primary regime</span>
          <div className="matrix__sidebar-tags">
            <span className="matrix__sidebar-tag">{state.primaryRegime}</span>
          </div>
        </div>
        <div className="matrix__sidebar-row">
          <span className="matrix__sidebar-label">Secondary regime</span>
          <div className="matrix__sidebar-tags">
            <span className="matrix__sidebar-tag">{state.secondaryRegime}</span>
          </div>
        </div>
        <div className="matrix__sidebar-row">
          <span className="matrix__sidebar-label">Posture</span>
          <p className="matrix__sidebar-posture">{state.posture}</p>
        </div>
      </aside>
    </div>
  );
};

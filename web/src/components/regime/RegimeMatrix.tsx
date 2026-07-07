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
  /** v12.0.8 Part E: データが部分的な時は「現在地は暫定」を明示。 */
  provisional?: boolean;
  /** v12.0.8: 軸の意味と入力の説明(1〜2行・オーナー可読)。 */
  axisHelpJa?: string;
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

export const RegimeMatrix: React.FC<Props> = ({ state, compact = false, axisLabels = DEFAULT_AXIS_LABELS, provisional = false, axisHelpJa }) => {
  const cx = plotX(state.x);
  const cy = plotY(state.y);
  // Highlight the active quadrant with a faint tint.
  const tintX = state.x < 0 ? PAD_L : plotX(0);
  const tintY = state.y > 0 ? PAD_T : plotY(0);
  const tintW = (W - PAD_L - PAD_R) / 2;
  const tintH = (H - PAD_T - PAD_B) / 2;

  // v10.190: lay out asset labels with vertical de-collision + side flipping so
  // clustered points (e.g. the US risk assets that pile up top-right) stay
  // readable. Labels near the right edge flip to the LEFT of their dot; labels
  // that would overlap are pushed apart and connected to their dot by a leader.
  const MIN_GAP = 12;
  const laidOut = React.useMemo(() => {
    const pts = state.assets.map((a) => {
      const dotX = plotX(a.x);
      const dotY = plotY(a.y);
      const estW = a.label.length * 5.2 + 8;
      const toLeft = dotX + estW > W - PAD_R;
      return { label: a.label, dotX, dotY, toLeft, labelY: dotY };
    });
    for (const side of [true, false]) {
      const grp = pts.filter((p) => p.toLeft === side).sort((p, q) => p.dotY - q.dotY);
      let lastY = -Infinity;
      for (const p of grp) {
        p.labelY = Math.max(p.dotY, lastY + MIN_GAP);
        lastY = p.labelY;
      }
      const last = grp[grp.length - 1];
      const overflow = last ? last.labelY - (H - PAD_B - 4) : 0;
      if (overflow > 0) for (const p of grp) p.labelY -= overflow;
    }
    return pts;
  }, [state.assets]);

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

          {/* Asset class context dots (de-collided labels + leader lines) */}
          {laidOut.map((p) => (
            <g key={p.label}>
              <circle className="matrix__asset-dot" cx={p.dotX} cy={p.dotY} r={3} />
              {Math.abs(p.labelY - p.dotY) > 2 && (
                <line className="matrix__asset-leader"
                  x1={p.dotX} y1={p.dotY}
                  x2={p.toLeft ? p.dotX - 5 : p.dotX + 5} y2={p.labelY - 3} />
              )}
              <text className="matrix__asset-label"
                x={p.toLeft ? p.dotX - 6 : p.dotX + 6} y={p.labelY}
                textAnchor={p.toLeft ? 'end' : 'start'}>{p.label}</text>
            </g>
          ))}

          {/* Current location — larger, accented */}
          <circle className="matrix__current-pulse" cx={cx} cy={cy} r={20} />
          <circle className="matrix__current-ring"  cx={cx} cy={cy} r={11} />
          <circle className="matrix__current-dot"   cx={cx} cy={cy} r={5.5} />
        </svg>
        {/* Legend — the blue marker is the MARKET's current location, not your
            position. Grey dots are asset classes (also not holdings). */}
        <p className="matrix__legend">
          <span className="matrix__legend-key"><i className="matrix__legend-dot matrix__legend-dot--current" />市場全体の現在地{provisional ? '(暫定)' : ''}</span>
          <span className="matrix__legend-key"><i className="matrix__legend-dot matrix__legend-dot--asset" />各資産クラス</span>
          <span className="matrix__legend-note">※保有ポジションではありません</span>
        </p>
        {/* v12.0.8 Part E: 軸の意味と入力を明示(「なぜここが現在地なのか」を隠さない) */}
        {axisHelpJa && (
          <p style={{ margin: '4px 0 0', fontSize: 10.5, color: 'var(--text-faint)', lineHeight: 1.6 }}>
            {axisHelpJa}{provisional ? ' データが部分的なため現在地は暫定です。' : ''}
          </p>
        )}
        <details style={{ marginTop: 2 }}>
          <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>各点の座標(入力の内訳)を見る</summary>
          <div style={{ fontSize: 10.5, color: 'var(--text-sub)', lineHeight: 1.7 }}>
            <p style={{ margin: '2px 0' }}>現在地: x={state.x.toFixed(2)} / y={state.y.toFixed(2)}(±1に正規化・データ欠損は0=中立に写像し、根拠なく端に寄せません)</p>
            {state.assets.map((a) => (
              <span key={a.label} style={{ display: 'inline-block', marginRight: 10 }}>{a.label}: x={a.x.toFixed(2)} y={a.y.toFixed(2)}</span>
            ))}
          </div>
        </details>
      </div>

      <aside className="matrix__sidebar">
        <div className="matrix__sidebar-row">
          <span className="matrix__sidebar-label">Current location · 現在地(市場全体)</span>
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

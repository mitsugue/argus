// Cross-asset diagnostic types. A.R.G.U.S. classifies the current market —
// it does NOT predict the future. These shapes hold the classification,
// not forecasts.

// ── Regime Matrix ────────────────────────────────────────────────────
// X axis: -1 = Risk Off, +1 = Risk On
// Y axis: -1 = Rates Relief, +1 = Rates Pressure
export interface RegimeAxisPoint {
  label: string;
  x: number;
  y: number;
}

export interface RegimeMatrixState {
  x: number;
  y: number;
  quadrantLabel: string;
  primaryRegime: string;
  secondaryRegime: string;
  posture: string;
  assets: RegimeAxisPoint[];
}

// ── Capital Rotation Board ───────────────────────────────────────────
// Pure cross-asset money-flow reading. NOT an action-label table —
// action labels live on Action Alerts / Watchlist. Per the v8.1 spec the
// board carries only three signals per asset row: Flow, Strength, Role.

export type FlowLabel =
  | 'Outflow'
  | 'Slight Outflow'
  | 'Neutral'
  | 'Slight Inflow'
  | 'Inflow';

export type FlowStrength = 'Low' | 'Medium' | 'High';

export type AssetRole =
  | 'Risk'
  | 'Defensive'
  | 'Hedge'
  | 'Duration'
  | 'Liquidity';

export interface CapitalRotationRow {
  assetClass: string;
  flow: FlowLabel;
  /** -100 (full outflow) .. +100 (full inflow). Drives the flow meter. */
  flowValue: number;
  strength: FlowStrength;
  role: AssetRole;
}

// ── Top Rotations (Today summary) ────────────────────────────────────
// A 3-second money-flow summary. Lighter than the Capital Rotation Board.

export interface TopRotation {
  from: string;
  to: string;
}

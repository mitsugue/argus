import type { ActionKey } from './action';

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
  x: number;                       // current location, [-1, 1]
  y: number;                       // current location, [-1, 1]
  quadrantLabel: string;           // e.g., "Risk Off / Rates Pressure"
  primaryRegime: string;           // e.g., "Event Risk"
  secondaryRegime: string;         // e.g., "Rates Pressure"
  posture: string;                 // e.g., "Wait. Avoid aggressive new entries..."
  assets: RegimeAxisPoint[];       // optional context dots
}

// ── Capital Rotation Board ───────────────────────────────────────────

export type FlowDirection =
  | 'inflow'
  | 'slight-inflow'
  | 'neutral'
  | 'slight-outflow'
  | 'outflow';

export type FlowStrength = 'low' | 'med' | 'high';

export interface CapitalRotationRow {
  assetClass: string;
  flow: FlowDirection;
  strength: FlowStrength;
  driver: string;                  // e.g., "Rates Pressure", "Hedge Demand"
  action: ActionKey;
  nextCondition: string;
}

// ── Top Rotations (Today summary) ────────────────────────────────────
// A 3-second money-flow summary. Lighter than the Capital Rotation Board.

export interface TopRotation {
  from: string;
  to: string;
}

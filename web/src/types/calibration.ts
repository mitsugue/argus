// Shape mirrors what the future scanner.py ledger will emit so the
// frontend doesn't need restructuring when we swap mock → real backend.

export type Horizon = '10m' | '1h' | '1d' | 'open';
export type Direction = 'up' | 'down';
export type Outcome = 'hit' | 'miss' | 'pending';

/**
 * A single prediction the model has made. Recorded the moment a pick
 * is published, then `outcome` flips when the horizon resolves.
 */
export interface PredictionEntry {
  id: string;
  /** UTC ms — when the prediction was made */
  predictedAt: number;
  /** UTC ms — when the outcome can be resolved */
  resolvesAt: number;
  /** UTC ms — actual resolution (null if pending) */
  resolvedAt: number | null;
  code: string; // ticker / 銘柄コード
  name?: string;
  direction: Direction;
  /** Model's claimed probability — 0..1 */
  probability: number;
  horizon: Horizon;
  /** Snapshot of price at predictedAt */
  priceAtPrediction: number;
  /** Price at resolvesAt (null if pending) */
  priceAtResolution: number | null;
  /** Realized move from prediction to resolution, % */
  movePct: number | null;
  outcome: Outcome;
  /** Short tag for what drove the call (e.g. "VWAP_RECLAIM", "EDINET_CATALYST") */
  reasonCode?: string;
}

/**
 * Bucket for the calibration curve — when the model says ~X%, how often
 * does it actually hit? Computed from non-pending entries.
 */
export interface CalibrationBin {
  /** Bin midpoint, 0..1 */
  predictedProb: number;
  /** Count of predictions in this bin */
  count: number;
  /** Fraction that resolved as hits, 0..1 */
  actualRate: number;
}

export interface CalibrationStats {
  /** All resolved entries in the window */
  windowDays: number;
  resolvedCount: number;
  pendingCount: number;
  hitCount: number;
  hitRate: number; // 0..1
  /** Mean predicted probability across resolved entries */
  expectedRate: number;
  /** Brier score — lower is better (0 = perfect) */
  brierScore: number;
  /** Trend: hit rate per day over the window (sparkline) */
  dailyHitRate: Array<{ day: string; rate: number; n: number }>;
  /** Reliability diagram bins (typically 5–10) */
  bins: CalibrationBin[];
}

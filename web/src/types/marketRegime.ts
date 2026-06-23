// Live Market Regime + Capital Rotation engine (regime-v1) response shape.
// Mirrors GET /api/argus/market-regime. ARGUS classifies the CURRENT
// cross-asset environment — it does not predict. ETF rotation is a proxy for
// capital flow, not direct flow.

export type RegimeSnapshotStatus = 'live' | 'partial' | 'mock';
export type RegimeLabel = 'RISK_ON' | 'RISK_OFF' | 'CAUTIOUS' | 'EVENT_WAIT' | 'MIXED';
export type RotationStatus = 'inflow' | 'outflow' | 'neutral';
export type RatesPosture = 'supportive' | 'neutral' | 'tightening' | 'stress';
export type SourceStatus = 'live' | 'partial' | 'unavailable' | 'mock' | 'unused';

export interface RegimeCore {
  label: RegimeLabel;
  growthValueAxis: number;
  riskDurationAxis: number;
  summaryJa: string;
  confidence: number;
}

export interface RatesBackdrop {
  us10y: number;
  us2y: number;
  real10y: number;
  vix: number;
  hyOas: number;
  posture: RatesPosture;
  rationaleJa: string;
}

export interface RotationGroup {
  id: string;
  label: string;
  assets: string[];
  role: 'Risk' | 'Defensive' | 'Hedge' | 'Duration' | 'Liquidity';
  score: number;
  momentum1d: number | null;
  momentum5d: number | null;
  momentum20d: number | null;
  status: RotationStatus;
  available: boolean;
  rationaleJa: string;
}

export interface TopRotationItem {
  label: string;
  direction: RotationStatus;
  score: number;
  evidenceJa: string;
}

export interface RegimeMatrixData {
  x: number;
  y: number;
  xLabel: string;
  yLabel: string;
  points: { label: string; x: number; y: number }[];
  rationaleJa: string;
}

export interface MarketRegimeSnapshot {
  status: RegimeSnapshotStatus;
  asOf: string;
  engineVersion: string;
  regime: RegimeCore;
  ratesBackdrop: RatesBackdrop;
  rotationGroups: RotationGroup[];
  topRotations: TopRotationItem[];
  matrix: RegimeMatrixData;
  supportingEvidence: string[];
  sourceStatuses: {
    fred: SourceStatus;
    twelveData: SourceStatus;
    jquants: SourceStatus;
    manualFallback: SourceStatus;
  };
  dataLimitations: string[];
  /** Minutes since the held last-full-coverage reading (v10.34). Present only
      when the displayed regime is a held-over reading, not a fresh full one. */
  heldOverMin?: number;
  /** JP intraday overlay (v10.98) — present when JP watchlist breadth is live.
      Keeps a green global regime from masking a weak Japan tape. */
  jpIntradayOverlay?: {
    globalRegime: string;
    jpIntradayOverlay: 'NORMAL' | 'CAUTION' | 'RISK_OFF_WATCH' | string;
    holderRiskOverlay: string;
    flags: string[];
    displayJa: string;
    reasonJa: string;
  } | null;
}

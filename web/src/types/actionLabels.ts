// Mirrors the backend /api/argus/action-labels shape (rule-based engine v0).

export type SnapshotStatus = 'live' | 'partial' | 'mock';
export type LabelRisk = 'low' | 'medium' | 'high';
export type PostureLabel = 'RISK_ON' | 'CAUTIOUS' | 'RISK_OFF' | 'EVENT_WAIT' | 'MIXED';

export interface ActionLabel {
  symbol: string;
  market: 'US' | 'JP';
  name: string;
  action: string;               // "WAIT" | "WAIT FOR PULLBACK" | "HOLD" | ... (English)
  confidence: number;           // 0..1
  risk: LabelRisk;
  reasonJa: string;
  supportingData: {
    changePct: number;
    volume: number;
    eventEscalation: string;    // "D-3" | "normal" | ...
    ratesPosture: string;       // "elevated" | "neutral" | "easing"
    marketRegime?: string;      // regime label (v9.5+)
    quoteDate?: string | null;  // data date behind the label (v9.8+)
    quoteLagDays?: number | null; // calendar-day lag; >7 = stale-damped
    bigFlowRatio?: number | null; // 大口純流入率 (moomoo bridge, v10.2)
  };
  nextConditionJa: string;
  status: 'live' | 'mock';
}

export interface MarketPosture {
  label: PostureLabel;
  rationaleJa: string;
}

// calibration-v1 (v10.8+): the ledger's scored track record for today's
// posture, fed back into label confidence server-side. factor 1.0 = neutral
// (insufficient evidence or noise-band hit rate).
export interface Calibration {
  factor: number;
  basisJa: string;
  n: number;
  hitRate: number | null;
}

export interface ActionVisibility {
  visibilityLevel?: string | null;
  confidenceCap?: number | null;
  blockedActions?: string[];
  entryBlocked?: boolean;
  downgradeReasonJa?: string;
  reasonCodes?: string[];
  coverageLineJa?: string | null;
}
export interface ActionLabelsSnapshot {
  status: SnapshotStatus;
  asOf: string;
  engineVersion: string;
  marketPosture: MarketPosture;
  calibration?: Calibration;
  visibility?: ActionVisibility;   // v11 — the guard's live effect on judgment
  labels: ActionLabel[];
}

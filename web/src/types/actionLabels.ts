// Mirrors the backend /api/argus/action-labels shape (rule-based engine v0).

export type SnapshotStatus = 'live' | 'partial' | 'mock';
export type LabelRisk = 'low' | 'medium' | 'high';
export type PostureLabel = 'RISK_ON' | 'CAUTIOUS' | 'RISK_OFF' | 'EVENT_WAIT';

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
  };
  nextConditionJa: string;
  status: 'live' | 'mock';
}

export interface MarketPosture {
  label: PostureLabel;
  rationaleJa: string;
}

export interface ActionLabelsSnapshot {
  status: SnapshotStatus;
  asOf: string;
  engineVersion: string;
  marketPosture: MarketPosture;
  labels: ActionLabel[];
}

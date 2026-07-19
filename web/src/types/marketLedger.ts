export interface MarketLedgerHistoryPoint { periodEnd: string; value: number | null; unit: string }
export interface MarketLedgerRow {
  seriesId: string; labelJa: string; latestValue: number | null; unit: string;
  previousChange: number | null; fourPeriodDirection: 'up' | 'down' | 'flat' | null;
  fourPeriodTotal: number | null; consecutiveDirectionCount: number | null;
  thresholdDistance: number | null; thresholdSide: 'above' | 'below' | null;
  thresholdStreak: number | null;
  historicalPercentile: number | null; periodEnd: string | null; availableFrom: string | null;
  status: string; acquisition: string; sourceKind: string; history: MarketLedgerHistoryPoint[];
}
export interface TurningPoint {
  id: string; ruleId: string; ruleVersion: string; detectedAt: string;
  effectiveFrom: string; availableFrom: string; detectionMode: 'live' | 'retrospective';
  facts: string[]; direction: string; severity: string; classification: string;
  subsequentOutcome: string;
}
export interface MarketLedgerPayload {
  schemaVersion: string; asOf: string;
  summary: Record<string, string>;
  valuationSummary: { epsPreviousChange: number | null; eps5Change: number | null;
    eps20Change: number | null; per18Level: number | null; per21Level: number | null;
    per21RecentPeak: number | null; per21ChangeFromPeak: number | null; labelJa: string };
  flowCaveatJa: string;
  table: MarketLedgerRow[];
  derivedMetrics: Array<{ metricId: string; value: number | null; unit: string; asOf: string }>;
  turningPoints: TurningPoint[]; observationCount: number; stateHash: string;
  remoteReadBack: { verificationStatus: string; lastVerifiedReadBackAt: string | null };
  noteJa: string;
}
export interface CostPolicyPayload {
  mode: 'DETERMINISTIC' | 'EVENT_OPT_IN' | 'MANUAL'; eventOptIn: boolean;
  automaticAiEnabled: boolean; todayRuns: Record<'openai' | 'gemini' | 'anthropic', number>;
  todayEstimatedCostUsd: number; monthEstimatedCostUsd: number;
  lastExecutionReason: string | null; nextAllowedAiExecution: string; messageJa: string; asOf: string;
}

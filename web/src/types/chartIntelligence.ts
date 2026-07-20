export interface ChartBar {
  date: string; open: number; high: number; low: number; close: number;
  volume: number | null; adjusted: boolean; availableFrom: string;
  ma: Record<string, number | null>;
  bollinger: { middle: number; upper2: number; lower2: number; upper3: number;
    lower3: number; lower4: number } | null;
  rsi14: number | null;
  macd: { line: number; signal: number; histogram: number } | null;
  atr14: number | null; sar: number | null;
  ichimoku: { conversion: number | null; base: number | null;
    spanA: number | null; spanB: number | null };
  volumeRatio20: number | null;
}
export interface PriceZone {
  id: string; lower: number; upper: number; center: number;
  firstObservedAt: string; lastTestedAt: string; testCount: number; breakCount: number;
  sourceTypes: string[]; strength: 'strong' | 'medium' | 'weak';
  status: 'active' | 'broken' | 'reclaimed' | 'unconfirmed';
}
export interface TechnicalPoint {
  id: string; ruleId: string; effectiveFrom: string; availableFrom: string;
  status: 'candidate' | 'confirmed' | 'invalidated'; facts: string[];
  direction: string; classification: string; detectionMode: 'live' | 'retrospective'; severity: string;
}
export interface RelativeStrengthRow {
  seriesId: string; latestValue: number | null; change5Pct: number | null;
  change20Pct: number | null; slope20: number | null; shortMA: number | null;
  mediumMA: number | null; directionTurn: string | null; historicalPercentile: number | null;
  classification: string; status: string; history: Array<{ date: string; value: number }>;
}
export interface RotationRow {
  label: string; relative5Pct: number | null; relative20Pct: number | null;
  state: 'improving' | 'deteriorating' | 'mixed' | 'missing'; status: string;
}
export interface ChartIntelligencePayload {
  schemaVersion: string; methodVersion: string; asOf: string; symbol: string; market: string;
  displayNameJa?: string; proxyDisclosureJa?: string; timeframe: 'daily' | 'weekly';
  status: string; missingReasons: string[]; automaticAiCalls: number; costPolicyMode: string;
  periodEnd: string | null;
  indicators: { bars: ChartBar[]; status: string; missingReasons: string[] };
  zones: PriceZone[]; turningPoints: TechnicalPoint[];
  ledgerTurningPoints?: Array<{ id: string; effectiveFrom: string; facts: string[] }>;
  reactionAnomalies: Array<{ id: string; ruleId: string; effectiveFrom: string;
    facts: string[]; causeStatus: string; priceReactionStatus: string }>;
  relationshipBreaks: Array<{ id: string; ruleId: string; facts: string[]; status: string }>;
  eventMarkers: Array<{ id: string; date: string; labelJa: string; kind: string }>;
  valuationLevels: Array<{ multiple: number; value: number; asOf: string; availableFrom: string;
    labelJa: string; history: Array<{ date: string; availableFrom: string; value: number }> }>;
  relativeStrength?: Record<string, RelativeStrengthRow>;
  rotationMap?: RotationRow[];
  critique: Array<{ label: string; text: string }>;
  scenarios: Array<{ label: string; text: string }>;
  persistence: { stateHash: string; verificationStatus: string; lastVerifiedReadBackAt: string | null };
  noteJa: string;
}

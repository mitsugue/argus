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
  /** Authoritative quote timing. Omitted by legacy payloads, which must fall back to CLOSE. */
  quoteState?: 'RT' | 'D20' | 'CLOSE' | 'STALE';
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
  instrumentMetadata?: { instrumentId: string; symbol: string; market: string;
    assetType: 'ETF' | 'EQUITY' | string; displayNameJa: string; source: string;
    availableFrom: string | null; observedAt: string; revision: number;
    proxyFor?: string | null; licenseStatus?: string };
  turningPointPage?: { totalStoredCount: number; apiReturnCount: number; uiDisplayLimit: number;
    activeCount: number; confirmedCount: number; periodFilter: string | null;
    limit: number | null; nextCursor: string | null };
  todayIntelligence?: {
    schemaVersion: string; methodVersion: string; symbol: string; market: string; asOf: string | null;
    historyCoverage: { start: string | null; end: string | null; count: number };
    calibration: { schemaVersion: string; methodVersion: string; calibrationVersion: string;
      historyStart: string | null; historyEnd: string | null; historyCount: number;
      horizons: Record<string, {
        horizon: number; signalFamily?: string; rawOccurrenceCount: number; episodeCount: number;
        effectiveSampleCount: number; cooldownTradingDays?: number; calibrationStatus: string;
        probabilities: { UP: number; RANGE: number; DOWN: number } | null;
        directionProbabilities?: { UP: number; RANGE: number; DOWN: number } | null;
        levelProbabilities?: { upperTargetTouch: number | null; baseRangeClose: number | null;
          lowerTargetTouch: number | null; invalidationTouch: number | null } | null;
        baseRates?: Record<string, number>; brierScore?: number | null;
        baseRateBrierScore?: number | null; confidenceInterval?: Record<string, { low: number; high: number }> | null;
        modelBrier?: number | null; baselineBrier?: number | null; brierSkill?: number | null;
        brierSkillConfidenceInterval?: { low: number | null; high: number | null } | null;
        calibrationError?: number | null; calibrationIntegrity?: string; calibrationDatasetHash?: string;
        noFutureLeakage?: boolean; walkForward?: boolean; calibrationVersion?: string;
        probabilityEligibility?: {
          eligible: boolean; reasonCodes: string[]; effectiveSample: number;
          modelBrier: number | null; baselineBrier: number | null; brierSkill: number | null;
          calibrationIntegrity: string; probabilitySum: number | null;
          calibrationVersion: string; datasetHash: string | null; evaluatedAt: string | null;
          contractVersion: string;
        };
        methodVersion?: string; averageReactionDelay?: number | null;
        returnDistribution?: { q10: number | null; q25: number | null; median: number | null;
          q75: number | null; q90: number | null; meanMfe: number | null; meanMae: number | null };
        targetProbabilities?: { upperTargetTouch: number | null; baseRangeClose: number | null;
          lowerTargetTouch: number | null; invalidationTouch: number | null } | null;
        expectedValue?: { horizon: number; expectedReturn: number | null; medianReturn: number | null;
          q10: number | null; q90: number | null; expectedUpside: number | null;
          expectedDownside: number | null; rewardRisk: number | null };
      }> };
    shortSelling: { schemaVersion: string; status: string; historyStart: string | null;
      historyCount: number; latestDate?: string; freshness?: string; missingReason?: string | null;
      latest: null | { date: string; totalShortRatio: number; previousDayDifference: number | null;
        average5: number | null; average20: number | null; rollingPercentile: number | null;
        totalTradingValue: number; totalShortSellingValue: number; regulatedShortValue: number;
        nonRegulatedShortValue: number; source: string; availableFrom: string } };
    failedRally: { state: 'NONE' | 'WATCH' | 'CONFIRMED'; facts: string[];
      probability: number | null; metrics: Record<string, number | null>;
      backtest: { rawOccurrenceCount: number; episodeCount: number; effectiveSampleCount: number;
        calibrationStatus: string; probability: number | null; outcomes: Record<string, unknown> } };
    automaticAiCalls: number;
  };
  marketReplay?: {
    schemaVersion: string; methodVersion: string; instrumentId: string;
    stateHash: string; automaticAiCalls: number; computationMode: string;
    readBack: { verificationStatus: string; lastVerifiedReadBackAt: string | null };
    contexts: Record<string, MarketReplayContext>;
  };
  marketCalendar?: {
    market?: string; marketDate?: string; isTradingDay?: boolean;
    session?: string; holidayName?: string | null; nextTradingDay?: string;
  };
  shortDataAudit?: Array<Record<string, unknown>>;
  noteJa: string;
}

export interface ReplayOutcome {
  '1': number | null; '5': number | null; '20': number | null;
  mfe: number | null; mae: number | null; reactionClass: string;
  reactionDelayDays: number | null;
}
export interface ReplayEpisode {
  episodeId: string; date: string; episodeStart: string; episodePeak: number | null;
  rank: number; family: string; volatility: string; distance: number;
  similarityPct: number; dataCoverage: string; outcomes: ReplayOutcome;
}
export interface ReplayDistribution {
  count: number; q10: number | null; q25: number | null; median: number | null;
  q75: number | null; q90: number | null; min: number | null; max: number | null;
  histogram: Array<{ from: number; to: number; count: number }>;
}
export interface ReplayLedgerSeries {
  seriesId: string; labelJa: string; unit?: string; currentValue: number;
  change1: number | null; cumulative4: number | null; cumulative13: number | null;
  rollingPercentile: number; zScore: number; localPeak: boolean; localBottom: boolean;
  extremeFamily: string | null; source?: string;
  history: Array<{ date: string; availableFrom: string; value: number }>;
}
export interface MarketReplayContext {
  schemaVersion: string; methodVersion: string; featureVersion: string;
  reactionVersion: string; contextId: string; instrumentId: string; symbol: string;
  market: string; horizon: number; asOf: string; datasetHash: string;
  outcomeHash: string; calibrationHash: string; automaticAiCalls: number;
  derivedMetricMigration?: {
    oldMethodVersion: string; newMethodVersion: string;
    metricDefinition: { mae: string; mfe: string; direction: string; unit: string };
    recomputedAt: string; sourceDatasetHash: string; rawObservationsModified: false;
  };
  historyCoverage: { start: string | null; end: string | null; count: number };
  currentFeatures: Record<string, number>;
  currentRegime: { trend: string; volatility: string };
  similarEpisodes: {
    rawOccurrenceCount: number; groupedEpisodeCount: number; effectiveSampleCount: number;
    cooldownTradingDays: number; similarityMethod: string; featureVersion: string;
    episodes: ReplayEpisode[];
  };
  eventStudy: { window: number[]; noFutureLeakage: boolean;
    points: Array<{ day: number; sample: number; q10: number | null; q25: number | null;
      median: number | null; q75: number | null; q90: number | null }> };
  outcomeDistributions: Record<string, ReplayDistribution>;
  calibrationCurve: { horizon: number; walkForward: boolean; noFutureLeakage: boolean;
    points: Array<{ bin: number; sample: number; predicted: number; observed: number;
      smallSample: boolean }> };
  regimeAnalysis: Array<{ regime: string; effectiveSample: number; eligible: boolean;
    medianReturnPct: number | null; upRatePct: number | null }>;
  extremes: { methodVersion: string; thresholds: number[]; rawOccurrenceCount: number;
    effectiveEpisodeCount: number; publicationTimeIntegrity: boolean;
    series: ReplayLedgerSeries[]; events: Array<Record<string, unknown>> };
  changeConditions: Array<{ triggerType: string; price: number | null; event: string | null;
    timeframe: string; requiredConfirmation: string; status: string; sourceId?: string }>;
  probabilityQuality: { modelBrier: number | null; baselineBrier: number | null;
    brierSkill: number | null; effectiveSample: number | null;
    calibrationIntegrity: string | null; datasetHash: string;
    evaluationPeriod: { start: string | null; end: string | null } };
  computation: { mode: string; cacheKey: string; noFutureLeakage: boolean;
    publicationTimeIntegrity: boolean };
}

export interface ComparisonPoint {
  offsetSessions: number;
  date?: string;
  value: number;
}
export interface ComparisonBandPoint {
  offsetSessions: number;
  lower: number;
  upper: number;
}
export interface JapanMarketComparison {
  schemaVersion: 'jp-market-comparison-v1';
  informationCutoff: string;
  sourceAcquisition?: {
    sources: Record<string, { observations: number; firstDate: string | null; lastDate: string | null;
      nativeFrequency: 'DAILY'; originalVintageVerified: false; latestRawId: string | null;
      lastKnownAt: string | null; expectedCalendarCoverageVerified: false }>;
    historicalVintageVerified: false; full10yAllIndicatorsComplete: false;
  };
  historyCoverage?: {
    sourceBars: number; sourceStart: string | null; sourceEnd: string | null;
    candidateCount: number; candidateStart: string | null; candidateEnd: string | null;
    calendarStart: string | null; calendarEnd: string | null;
    candidatesByYear: Record<string, number>;
    excluded: { missingCalendarOrPriceSession: number; incompleteEpisode: number };
    maximumSelected: number; selectedCount: number; admittedCount: number;
    allMarketFeaturesTenYearsVerified: boolean;
  };
  /** Fixed-cutoff search receipt.  It explains selection and has no forecast authority. */
  /** Set while a saved market-condition comparison is shown because the history is recalculating. */
  retainedNoteJa?: string;
  /** How candidates were admitted: the yardstick per series and the bounds (2026-09-30). */
  selectionPolicy?: {
    policyId: string; lookbackSessions: number; maximumCandidates: number; minimumSeparationSessions: number;
    maximumDistance: number; shapeScalePct: number; distanceMeaning: string;
    componentWeights?: Record<string, number> | null;
    stateScales: Record<string, { scale: number; basis: 'ROBUST_MAD_HISTORY' | 'FIXED_DEFINITION'; observations: number; unit: string }>;
  };
  selectionAudit?: Record<string, {
    candidateCount: number;
    admittedCount: number;
    selectedCount: number;
    closest: { anchorDate: string; distance: number;
      status: 'SELECTED' | 'ADMITTED' | 'DISTANCE_ABOVE_THRESHOLD'; rank: number | null } | null;
  }>;
  anchorDate: string;
  actualAnchorPrice: number;
  unit: 'ANCHOR_100' | 'JPY_INDEX_POINTS';
  actual: ComparisonPoint[];
  candidates: Array<{
    snapshotId: string;
    anchorDate: string;
    comparisonKind: 'MARKET_ANALOG' | 'PARTIAL_COMPARISON';
    comparison: ComparisonPoint[];
    subsequentReference: ComparisonPoint[];
    missingFeatures: string[];
    missingGroups: string[];
    similarReasons: string[];
    /** Market-condition series actually compared (labels), and the defined total. Absent on older documents. */
    comparedFeatures?: string[];
    comparedFeatureCount?: number;
    stateFeatureDefinitionCount?: number;
    differences: string[];
  }>;
  forecast: {
    status: string;
    line: ComparisonPoint[];
    band: ComparisonBandPoint[];
    horizonSessions: number;
    validationStatus: 'UNVALIDATED' | 'VALIDATED';
    sampleCount: number;
    counts: { up: number; flat: number; down: number };
    flatThresholdPct: number;
    /** Walk-forward check of this forecast rule on the engine's own history (2026-09-30). */
    validation?: {
      method: string; evaluationStart: string | null; evaluationEnd: string | null; stepSessions: number;
      evaluations: number; directionalEvaluations: number; hits: number;
      hitRate: number | null; hitRateWilsonLower95: number | null; naiveMajorityRate: number | null;
      bandCoverage: number | null; meanAbsoluteError: number | null; naiveNoChangeMeanAbsoluteError: number | null;
      validationStatus: 'UNVALIDATED' | 'VALIDATED'; reasons: string[]; scaleRule: string;
      predictiveProbabilities: null;
    };
    /** Component-weight search: chosen on the first half, adopted on the third quarter, reported on the last. */
    weightSearch?: {
      gridSize: number; chosenWeights: Record<string, number>; choiceHorizon: number; adopted: boolean;
      trainStart: string; trainEnd: string; confirmStart?: string; confirmEnd?: string;
      testStart: string; testEnd: string;
      trainHitRate: number | null; trainNaiveRate: number | null;
      testHitRate: number | null; testNaiveRate: number | null; testWilsonLower95: number | null;
      equalWeightsTestHitRate: number | null; predictiveProbabilities: null;
    };
    /** What followed each of the seven warning conditions in the same history (2026-10-02). */
    signEventStudy?: SignEventStudy;
  };
  scaleExplanation: string;
  valuationEvidence?: {
    date: string; eps: number; per: number; epsKind: string;
    knownAt: string; publishedAt: string | null; sourceRef: string;
    sourceResponseSha256: string | null;
  };
  limitations: string[];
}

/** Direction record of the Nikkei paths ARGUS actually issued (one per anchor, scored after the horizon). */
export interface ForecastTrackRecordHorizon {
  horizonSessions: number; scoredForecasts: number; directionalForecasts: number; hits: number;
  hitRate: number | null; hitRateWilsonLower95: number | null; naiveMajorityRate: number | null;
  status: 'INSUFFICIENT_SAMPLE' | 'ABOVE_BASELINE' | 'NOT_ABOVE_BASELINE';
  firstTargetDate: string | null; lastTargetDate: string | null;
}
export interface ForecastTrackRecord {
  schemaVersion: 'argus-forecast-track-record-v1'; instrumentId: 'NIKKEI_225_INDEX';
  minimumDirectionalForecasts: number; horizons: Record<string, ForecastTrackRecordHorizon>;
  predictiveProbabilities: null; actionAuthority: false;
}

/** Outcome shares after activations, against every session of the same span. */
export interface SignEventStudyMetrics {
  evaluated: number; falls: number; fallShare: number | null; fallShareWilsonLower95: number | null;
  riseShare: number | null; meanReturnPct: number | null; baselineSessions: number;
  baselineFallShare: number | null; baselineMeanReturnPct: number | null;
}
export type SignEventStudyStatus = 'INSUFFICIENT_SAMPLE' | 'NOT_ABOVE_BASELINE' | 'ABOVE_BASELINE' | 'NOT_EVALUABLE';
export interface SignEventStudyCondition {
  family: 'D01' | 'D02' | 'D03' | 'D04' | 'D05' | 'D06' | 'D07';
  seriesId: string | null; activationValue: number | null; status: SignEventStudyStatus; reason: string | null;
  rawActivations: number; activations: number; overlappingMerged: number;
  firstActivation: string | null; lastActivation: string | null; coverageStart: string | null; coverageEnd: string | null;
  horizons: Record<string, SignEventStudyMetrics>; falseAlarms: number; falseAlarmShare: number | null;
  periods: Array<{ name: 'design' | 'confirm' | 'report'; start: string | null; end: string | null; activations: number;
    horizons: Record<string, SignEventStudyMetrics> }>;
  predictiveProbabilities: null; actionAuthority: false;
}
export interface SignEventStudy {
  schemaVersion: 'jp-sign-event-study-v1'; method: string; informationCutoff: string;
  status: 'AVAILABLE' | 'UNAVAILABLE'; cooldownSessions: number; horizons: number[]; primaryHorizon: number;
  minimumActivations: number; conditions: Record<string, SignEventStudyCondition>;
  historicalVintageVerified: false; validationStatus: 'UNVALIDATED';
  predictiveProbabilities: null; actionAuthority: false;
}

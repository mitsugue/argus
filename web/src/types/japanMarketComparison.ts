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
  };
  scaleExplanation: string;
  limitations: string[];
}

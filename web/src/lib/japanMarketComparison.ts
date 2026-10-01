import type { ForecastTrackRecord, JapanMarketComparison } from '../types/japanMarketComparison';

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 100 && v.every(x => typeof x === 'string');
const validCounts = (v: unknown, total: unknown) => {
  if (!object(v)) return false;
  const { up, flat, down } = v;
  return finite(up) && finite(flat) && finite(down) && [up, flat, down].every(x => Number.isInteger(x) && x >= 0)
    && up + flat + down === total;
};
const points = (v: unknown) => Array.isArray(v) && v.length <= 121 && v.every(p => object(p)
  && finite(p.offsetSessions) && Number.isInteger(p.offsetSessions) && finite(p.value) && p.value > 0);

export function validJapanMarketComparison(v: unknown, horizon: number): v is JapanMarketComparison {
  if (!object(v) || v.schemaVersion !== 'jp-market-comparison-v1'
    || typeof v.informationCutoff !== 'string' || !Number.isFinite(Date.parse(v.informationCutoff))
    || typeof v.anchorDate !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v.anchorDate)
    || !finite(v.actualAnchorPrice) || v.actualAnchorPrice <= 0
    || !['ANCHOR_100', 'JPY_INDEX_POINTS'].includes(String(v.unit))
    || !points(v.actual) || !(v.actual as unknown[]).length
    || typeof v.scaleExplanation !== 'string' || !strings(v.limitations)
    || !Array.isArray(v.candidates) || v.candidates.length > 10) return false;
  if (v.historyCoverage !== undefined) {
    const h = v.historyCoverage;
    const count = (n: unknown) => finite(n) && Number.isInteger(n) && n >= 0;
    const day = (d: unknown) => d === null || (typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d));
    if (!object(h) || !['sourceBars', 'candidateCount', 'maximumSelected', 'selectedCount', 'admittedCount'].every(k => count(h[k]))
      || !['sourceStart', 'sourceEnd', 'candidateStart', 'candidateEnd', 'calendarStart', 'calendarEnd'].every(k => day(h[k]))
      || !object(h.candidatesByYear) || Object.keys(h.candidatesByYear).length > 12
      || !Object.entries(h.candidatesByYear).every(([year, n]) => /^\d{4}$/.test(year) && count(n))
      || !object(h.excluded) || !count(h.excluded.missingCalendarOrPriceSession) || !count(h.excluded.incompleteEpisode)
      || typeof h.allMarketFeaturesTenYearsVerified !== 'boolean') return false;
  }
  if (v.retainedNoteJa !== undefined && (typeof v.retainedNoteJa !== 'string' || v.retainedNoteJa.length > 400)) return false;
  if (v.selectionPolicy !== undefined) {
    const p = v.selectionPolicy;
    if (!object(p) || typeof p.policyId !== 'string' || typeof p.distanceMeaning !== 'string'
      || !['lookbackSessions', 'maximumCandidates', 'minimumSeparationSessions'].every(k => finite(p[k]) && Number.isInteger(p[k]) && p[k] >= 1)
      || !finite(p.maximumDistance) || p.maximumDistance <= 0 || !finite(p.shapeScalePct) || p.shapeScalePct <= 0
      || !object(p.stateScales) || Object.keys(p.stateScales).length > 64
      || !Object.values(p.stateScales).every(sc => object(sc) && finite(sc.scale) && sc.scale > 0
        && ['ROBUST_MAD_HISTORY', 'FIXED_DEFINITION'].includes(String(sc.basis))
        && finite(sc.observations) && Number.isInteger(sc.observations) && sc.observations >= 0
        && typeof sc.unit === 'string')) return false;
  }
  if (v.selectionAudit !== undefined) {
    if (!object(v.selectionAudit) || Object.keys(v.selectionAudit).length > 12
      || !Object.entries(v.selectionAudit).every(([year, value]) => {
        if (!/^\d{4}$/.test(year) || !object(value)) return false;
        const candidateCount = value.candidateCount;
        const admittedCount = value.admittedCount;
        const selectedCount = value.selectedCount;
        if (![candidateCount, admittedCount, selectedCount].every(item => finite(item)
          && Number.isInteger(item) && item >= 0)
          || !finite(candidateCount) || !finite(admittedCount) || !finite(selectedCount)
          || admittedCount > candidateCount || selectedCount > admittedCount) return false;
        const closest = value.closest;
        return closest === null || (object(closest)
          && typeof closest.anchorDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(closest.anchorDate)
          && finite(closest.distance) && closest.distance >= 0
          && ['SELECTED', 'ADMITTED', 'DISTANCE_ABOVE_THRESHOLD'].includes(String(closest.status))
          && (closest.rank === null || (finite(closest.rank) && Number.isInteger(closest.rank) && closest.rank >= 1)));
      })) return false;
  }
  const ids = new Set<string>();
  if (v.sourceAcquisition !== undefined) {
    const s = v.sourceAcquisition;
    if (!object(s) || s.historicalVintageVerified !== false || s.full10yAllIndicatorsComplete !== false
      || !object(s.sources) || Object.keys(s.sources).length > 2) return false;
    for (const [key, r] of Object.entries(s.sources)) {
      const day = (d: unknown) => d === null || (typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d));
      if (!['jp_yield_curve', 'vix_ohlc'].includes(key) || !object(r)
        || !finite(r.observations) || !Number.isInteger(r.observations) || r.observations < 0
        || !day(r.firstDate) || !day(r.lastDate) || r.nativeFrequency !== 'DAILY'
        || r.originalVintageVerified !== false || r.expectedCalendarCoverageVerified !== false
        || !(r.latestRawId === null || (typeof r.latestRawId === 'string' && /^[a-f0-9]{64}$/.test(r.latestRawId)))
        || !(r.lastKnownAt === null || (typeof r.lastKnownAt === 'string' && Number.isFinite(Date.parse(r.lastKnownAt))))) return false;
    }
  }
  if (v.valuationEvidence !== undefined) {
    const e = v.valuationEvidence;
    if (!object(e) || e.date !== v.anchorDate || !finite(e.eps) || e.eps <= 0
      || !finite(e.per) || e.per <= 0
      || typeof e.knownAt !== 'string' || !Number.isFinite(Date.parse(e.knownAt))
      || Date.parse(e.knownAt) > Date.parse(v.informationCutoff)
      || e.publishedAt !== null) return false;
    // Two admitted evidence shapes, never mixed: the official Nikkei row
    // (exact source URL + response digest) or the ARGUS proxy reconstructed
    // from constituent EPS (argus: source ref, no response digest).
    const official = e.epsKind === 'DERIVED_FROM_INDEX_CLOSE_AND_INDEX_BASED_PER'
      && e.sourceRef === 'https://indexes.nikkei.co.jp/nkave/archives/summary/'
      && typeof e.sourceResponseSha256 === 'string' && /^[a-f0-9]{64}$/.test(e.sourceResponseSha256);
    const proxy = e.epsKind === 'PROXY_FROM_CONSTITUENT_FORECAST_EPS'
      && typeof e.sourceRef === 'string' && /^argus:index-valuation-proxy:[A-Za-z0-9+._-]{1,80}$/.test(e.sourceRef)
      && e.sourceResponseSha256 === null;
    if (!official && !proxy) return false;
  }
  for (const c of v.candidates) {
    if (!object(c) || typeof c.snapshotId !== 'string' || ids.has(c.snapshotId)
      || typeof c.anchorDate !== 'string' || !['MARKET_ANALOG', 'PARTIAL_COMPARISON'].includes(String(c.comparisonKind))
      || !points(c.comparison) || !points(c.subsequentReference) || !strings(c.missingFeatures)
      || !strings(c.missingGroups) || !strings(c.similarReasons) || !strings(c.differences)) return false;
    if (c.comparedFeatures !== undefined || c.comparedFeatureCount !== undefined || c.stateFeatureDefinitionCount !== undefined) {
      if (!strings(c.comparedFeatures) || !finite(c.comparedFeatureCount) || !Number.isInteger(c.comparedFeatureCount)
        || !finite(c.stateFeatureDefinitionCount) || !Number.isInteger(c.stateFeatureDefinitionCount)
        || c.comparedFeatureCount !== (c.comparedFeatures as string[]).length
        || c.comparedFeatureCount > c.stateFeatureDefinitionCount || c.stateFeatureDefinitionCount > 64) return false;
    }
    ids.add(c.snapshotId);
  }
  const f = v.forecast;
  return object(f) && typeof f.status === 'string' && f.horizonSessions === horizon
    && ['UNVALIDATED', 'VALIDATED'].includes(String(f.validationStatus))
    && points(f.line) && Array.isArray(f.band) && f.band.length <= 21
    && f.band.every(p => object(p) && finite(p.offsetSessions) && finite(p.lower) && finite(p.upper)
      && p.lower > 0 && p.lower <= p.upper)
    && finite(f.sampleCount) && Number.isInteger(f.sampleCount) && f.sampleCount >= 0
    && finite(f.flatThresholdPct) && f.flatThresholdPct >= 0 && validCounts(f.counts, f.sampleCount)
    && (f.validation === undefined || validForecastValidation(f.validation, f.validationStatus))
    && (f.weightSearch === undefined || validWeightSearch(f.weightSearch));
}

function validWeightSearch(w: unknown): boolean {
  if (!object(w)) return false;
  const rate = (n: unknown) => n === null || (finite(n) && n >= 0 && n <= 1);
  const day = (d: unknown) => typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d);
  return finite(w.gridSize) && Number.isInteger(w.gridSize) && w.gridSize >= 1 && w.gridSize <= 64
    && object(w.chosenWeights) && Object.values(w.chosenWeights).every(v => finite(v) && v >= 0)
    && finite(w.choiceHorizon) && typeof w.adopted === 'boolean' && w.predictiveProbabilities === null
    && ['trainStart', 'trainEnd', 'testStart', 'testEnd'].every(k => day(w[k]))
    && String(w.trainEnd) < String(w.testStart)
    && ['trainHitRate', 'trainNaiveRate', 'testHitRate', 'testNaiveRate', 'testWilsonLower95', 'equalWeightsTestHitRate']
      .every(k => rate(w[k]));
}

function validForecastValidation(v: unknown, status: unknown): boolean {
  if (!object(v)) return false;
  const rate = (n: unknown) => n === null || (finite(n) && n >= 0 && n <= 1);
  const count = (n: unknown) => finite(n) && Number.isInteger(n) && n >= 0;
  const nonNegative = (n: unknown) => n === null || (finite(n) && n >= 0);
  return typeof v.method === 'string' && v.predictiveProbabilities === null
    && ['evaluations', 'directionalEvaluations', 'hits', 'stepSessions'].every(k => count(v[k]))
    && (v.hits as number) <= (v.directionalEvaluations as number)
    && (v.directionalEvaluations as number) <= (v.evaluations as number)
    && ['hitRate', 'hitRateWilsonLower95', 'naiveMajorityRate', 'bandCoverage'].every(k => rate(v[k]))
    && nonNegative(v.meanAbsoluteError) && nonNegative(v.naiveNoChangeMeanAbsoluteError)
    && v.validationStatus === status && strings(v.reasons)
    && (v.validationStatus === 'VALIDATED') === ((v.reasons as string[]).length === 0);
}

const rate = (v: unknown) => v === null || (typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1);
const count = (v: unknown) => Number.isInteger(v) && (v as number) >= 0;

export function validForecastTrackRecord(v: unknown): v is ForecastTrackRecord {
  const value = v as ForecastTrackRecord;
  if (!value || value.schemaVersion !== 'argus-forecast-track-record-v1' || value.instrumentId !== 'NIKKEI_225_INDEX'
    || value.predictiveProbabilities !== null || value.actionAuthority !== false
    || !count(value.minimumDirectionalForecasts) || !value.horizons || typeof value.horizons !== 'object') return false;
  return Object.entries(value.horizons).every(([key, h]) => h && String(h.horizonSessions) === key
    && count(h.scoredForecasts) && count(h.directionalForecasts) && count(h.hits)
    && h.hits <= h.directionalForecasts && h.directionalForecasts <= h.scoredForecasts
    && rate(h.hitRate) && rate(h.hitRateWilsonLower95) && rate(h.naiveMajorityRate)
    && (h.directionalForecasts > 0 || h.hitRate === null)
    && ['INSUFFICIENT_SAMPLE', 'ABOVE_BASELINE', 'NOT_ABOVE_BASELINE'].includes(h.status)
    && (h.status === 'INSUFFICIENT_SAMPLE') === (h.directionalForecasts < value.minimumDirectionalForecasts));
}

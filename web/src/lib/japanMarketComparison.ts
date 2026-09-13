import type { JapanMarketComparison } from '../types/japanMarketComparison';

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
  const ids = new Set<string>();
  if (v.valuationEvidence !== undefined) {
    const e = v.valuationEvidence;
    if (!object(e) || e.date !== v.anchorDate || !finite(e.eps) || e.eps <= 0
      || !finite(e.per) || e.per <= 0 || e.epsKind !== 'DERIVED_FROM_INDEX_CLOSE_AND_INDEX_BASED_PER'
      || typeof e.knownAt !== 'string' || !Number.isFinite(Date.parse(e.knownAt))
      || Date.parse(e.knownAt) > Date.parse(v.informationCutoff)
      || e.publishedAt !== null
      || e.sourceRef !== 'https://indexes.nikkei.co.jp/nkave/archives/summary/'
      || typeof e.sourceResponseSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(e.sourceResponseSha256)) return false;
  }
  for (const c of v.candidates) {
    if (!object(c) || typeof c.snapshotId !== 'string' || ids.has(c.snapshotId)
      || typeof c.anchorDate !== 'string' || !['MARKET_ANALOG', 'PARTIAL_COMPARISON'].includes(String(c.comparisonKind))
      || !points(c.comparison) || !points(c.subsequentReference) || !strings(c.missingFeatures)
      || !strings(c.missingGroups) || !strings(c.similarReasons) || !strings(c.differences)) return false;
    ids.add(c.snapshotId);
  }
  const f = v.forecast;
  return object(f) && typeof f.status === 'string' && f.horizonSessions === horizon
    && ['UNVALIDATED', 'VALIDATED'].includes(String(f.validationStatus))
    && points(f.line) && Array.isArray(f.band) && f.band.length <= 21
    && f.band.every(p => object(p) && finite(p.offsetSessions) && finite(p.lower) && finite(p.upper)
      && p.lower > 0 && p.lower <= p.upper)
    && finite(f.sampleCount) && Number.isInteger(f.sampleCount) && f.sampleCount >= 0
    && finite(f.flatThresholdPct) && f.flatThresholdPct >= 0 && validCounts(f.counts, f.sampleCount);
}

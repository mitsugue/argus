const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText, filename);
const { validJapanMarketComparison } = require('../src/lib/japanMarketComparison.ts');
const document = {
  schemaVersion: 'jp-market-comparison-v1', informationCutoff: '2026-09-11T08:00:00Z',
  anchorDate: '2026-09-11', actualAnchorPrice: 40000, unit: 'ANCHOR_100',
  actual: [{ offsetSessions: 0, value: 100 }], candidates: [],
  forecast: { status: 'INSUFFICIENT_COMPLETE_ANALOGS', line: [], band: [],
    horizonSessions: 5, validationStatus: 'UNVALIDATED', sampleCount: 0,
    counts: { up: 0, flat: 0, down: 0 }, flatThresholdPct: .5 },
  scaleExplanation: '基準日100の形状比較', limitations: ['未検証'],
};
assert(validJapanMarketComparison(document, 5));
assert(!validJapanMarketComparison(document, 20), 'a previous horizon must not impersonate the selection');
for (const mutate of [
  d => { d.actual[0].value = NaN; },
  d => { d.actual[0].value = '100'; },
  d => { d.forecast.counts.up = 1; },
  d => { d.forecast.band = [{ offsetSessions: 1, lower: 102, upper: 99 }]; },
  d => { d.candidates = [{ comparison: null }]; },
  d => { d.actual = []; },
  d => { d.informationCutoff = 'unknown'; },
]) {
  const invalid = structuredClone(document); mutate(invalid);
  assert(!validJapanMarketComparison(invalid, 5));
}
console.log('Japan comparison response validation PASS');
const withScale = { ...document, unit: 'JPY_INDEX_POINTS', valuationEvidence: {
  date: document.anchorDate, eps: 2000, per: 20,
  epsKind: 'DERIVED_FROM_INDEX_CLOSE_AND_INDEX_BASED_PER', knownAt: '2026-09-11T07:30:00Z',
  publishedAt: null, sourceRef: 'https://indexes.nikkei.co.jp/nkave/archives/summary/', sourceResponseSha256: 'a'.repeat(64),
} };
assert(validJapanMarketComparison(withScale, 5));
for (const patch of [{ eps: NaN }, { per: 0 }, { knownAt: '2026-09-12T00:00:00Z' },
  { date: '2026-09-10' }, { sourceRef: 'javascript:void(0)' }, { epsKind: 'PUBLISHED_EPS' },
  { publishedAt: '2026-09-11T07:30:00Z' }, { sourceResponseSha256: null }]) {
  assert(!validJapanMarketComparison({ ...withScale, valuationEvidence: { ...withScale.valuationEvidence, ...patch } }, 5));
}
console.log('Index valuation evidence validation PASS');

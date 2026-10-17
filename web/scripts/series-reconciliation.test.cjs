const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText, filename);
const { validSeriesReconciliation, SERIES_LABEL_JA, STATUS_JA } = require('../src/lib/seriesReconciliation.ts');
const { comparisonReply, retainComparisonReply } = require('../src/lib/japanMarketComparisonReply.ts');
const row = { status: 'GAPS_FOUND', expected: 2441, actual: 2440, missing: 1, unexpected: 0, duplicated: 0, invalidValues: 0 };
const doc = { measuredAt: '2026-10-18T00:00:00Z', gapsFound: ['price_series:nikkei'],
  series: { 'price_series:nikkei': row, 'price_series:sp500': { ...row, status: 'EXPECTED_CALENDAR_UNAVAILABLE', expected: null, missing: null, unexpected: null },
    'future_series': { status: 'NEW_STATUS' } } };
assert.ok(validSeriesReconciliation(doc), 'an unknown series is skipped');
for (const bad of [null, {}, { ...doc, gapsFound: null }, { ...doc, series: { 'price_series:nikkei': { ...row, missing: -1 } } },
  { ...doc, series: { 'price_series:nikkei': { ...row, status: 'OK' } } }, { ...doc, series: { 'price_series:nikkei': { ...row, actual: '2440' } } }])
  assert.equal(validSeriesReconciliation(bad), false);
assert.ok(Object.keys(STATUS_JA).includes('EXPECTED_CALENDAR_UNAVAILABLE') && Object.keys(SERIES_LABEL_JA).length === 13);
const reply = comparisonReply({ status: 'unavailable', comparison: null, reason: 'x', automaticAiCalls: 0, actionAuthority: false,
  marketFeatureAcquisition: { seriesReconciliation: doc } }, 5);
assert.deepEqual(reply.seriesReconciliation, doc);
const failed = comparisonReply({ status: 'unavailable', comparison: null, reason: 'x', automaticAiCalls: 0, actionAuthority: false,
  marketFeatureAcquisition: { seriesReconciliation: { status: 'FAILED', actionAuthority: false } } }, 5);
assert.equal(failed.seriesReconciliation, null);
assert.deepEqual(retainComparisonReply(failed, reply).seriesReconciliation, doc, 'the last good table stays');
console.log('series reconciliation display contract PASS');

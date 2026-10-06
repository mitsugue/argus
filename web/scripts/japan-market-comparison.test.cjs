const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText, filename);
const { validForecastTrackRecord, validJapanMarketComparison } = require('../src/lib/japanMarketComparison.ts');
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
const withReview = structuredClone(document);
withReview.reviewConditionsJa = ['基準日や市場条件を更新したら比較し直します。'];
assert(validJapanMarketComparison(withReview, 5));
for (const review of [null, [], [''], ['  '], [1], ['a'.repeat(201)], ['a', 'b', 'c', 'd']]) {
  assert(!validJapanMarketComparison({ ...document, reviewConditionsJa: review }, 5));
}
assert(!Object.hasOwn(document, 'reviewConditionsJa'), 'the older response remains compatible');
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
// 2026-09-30: walk-forward validation metrics travel with the forecast.
const validation = { method: 'jp-analog-walk-forward-v1', evaluationStart: '2017-10-02', evaluationEnd: '2026-08-28',
  stepSessions: 5, evaluations: 400, directionalEvaluations: 300, hits: 160, hitRate: 160 / 300,
  hitRateWilsonLower95: 0.477, naiveMajorityRate: 0.55, bandCoverage: 0.48, meanAbsoluteError: 2.1,
  naiveNoChangeMeanAbsoluteError: 2.0, validationStatus: 'UNVALIDATED',
  reasons: ['direction_not_better_than_naive_majority'], scaleRule: 'yearly', predictiveProbabilities: null };
const withValidation = structuredClone(document); withValidation.forecast.validation = validation;
assert(validJapanMarketComparison(withValidation, 5));
for (const patch of [{ predictiveProbabilities: 0.6 }, { hitRate: 1.2 }, { hits: 301 }, { validationStatus: 'VALIDATED' },
  { reasons: [] }, { evaluations: 10 }]) {
  const invalid = structuredClone(withValidation); Object.assign(invalid.forecast.validation, patch);
  assert(!validJapanMarketComparison(invalid, 5), JSON.stringify(patch));
}
console.log('Japan comparison walk-forward validation shape PASS');
const weightSearch = { gridSize: 12, chosenWeights: { priceShape: 1, marketState: 2, conditionOrder: 0.5 },
  choiceHorizon: 5, adopted: false, trainStart: '2017-11-06', trainEnd: '2022-02-01', testStart: '2022-02-08',
  testEnd: '2026-08-24', trainHitRate: 0.55, trainNaiveRate: 0.5, testHitRate: 0.46, testNaiveRate: 0.49,
  testWilsonLower95: 0.37, equalWeightsTestHitRate: 0.45, predictiveProbabilities: null };
const withSearch = structuredClone(withValidation); withSearch.forecast.weightSearch = weightSearch;
assert(validJapanMarketComparison(withSearch, 5));
for (const patch of [{ predictiveProbabilities: 0.5 }, { testHitRate: 2 }, { trainEnd: '2023-01-01' }, { adopted: 'yes' }]) {
  const invalid = structuredClone(withSearch); Object.assign(invalid.forecast.weightSearch, patch);
  assert(!validJapanMarketComparison(invalid, 5), JSON.stringify(patch));
}
console.log('Japan comparison weight search shape PASS');
// 2026-10-02: the seven warning conditions' event study rides the forecast.
const signMetrics = (evaluated, falls, baseline) => ({ evaluated, falls,
  fallShare: evaluated ? falls / evaluated : null, fallShareWilsonLower95: evaluated ? 0.3 : null,
  riseShare: evaluated ? (evaluated - falls) / evaluated : null, meanReturnPct: evaluated ? -0.4 : null,
  baselineSessions: 900, baselineFallShare: baseline, baselineMeanReturnPct: 0.1,
  hits: falls, hitShare: evaluated ? falls / evaluated : null, hitShareWilsonLower95: evaluated ? 0.3 : null,
  baselineHitShare: baseline });
const signCondition = (family, status, activations) => ({ family, seriesId: family === 'D07' ? null : 'series',
  activationValue: family === 'D07' ? null : 1, expects: family === 'D07' ? null : 'FALL', status, reason: null, rawActivations: activations + 2,
  activations, overlappingMerged: 2, firstActivation: activations ? '2017-01-05' : null,
  lastActivation: activations ? '2026-08-03' : null, coverageStart: '2016-10-04', coverageEnd: '2026-09-03',
  horizons: status === 'NOT_EVALUABLE' ? {} : { 5: signMetrics(activations, Math.floor(activations / 2), 0.45),
    20: signMetrics(activations, Math.floor(activations / 3), 0.4) },
  falseAlarms: 1, falseAlarmShare: activations ? 1 / activations : null,
  periods: status === 'NOT_EVALUABLE' ? [] : ['design', 'confirm', 'report'].map(name => ({ name, start: '2017-01-04',
    end: '2019-12-30', activations: Math.floor(activations / 3), horizons: { 5: signMetrics(Math.floor(activations / 3), Math.min(1, Math.floor(activations / 3)), 0.45) } })),
  predictiveProbabilities: null, actionAuthority: false });
const signEventStudy = { schemaVersion: 'jp-sign-event-study-v1', method: 'jp-sign-event-study-v1',
  informationCutoff: '2026-09-11T08:00:00Z', status: 'AVAILABLE', cooldownSessions: 20, horizons: [5, 20],
  primaryHorizon: 5, minimumActivations: 20, historicalVintageVerified: false, validationStatus: 'UNVALIDATED',
  predictiveProbabilities: null, actionAuthority: false, conditions: {
    D01: signCondition('D01', 'NOT_ABOVE_BASELINE', 31), D02: signCondition('D02', 'INSUFFICIENT_SAMPLE', 4),
    D03: signCondition('D03', 'ABOVE_BASELINE', 40), D04: signCondition('D04', 'INSUFFICIENT_SAMPLE', 0),
    D05: signCondition('D05', 'INSUFFICIENT_SAMPLE', 12), D06: signCondition('D06', 'NOT_ABOVE_BASELINE', 25),
    D07: signCondition('D07', 'NOT_EVALUABLE', 0) } };
const withSigns = structuredClone(withSearch); withSigns.forecast.signEventStudy = signEventStudy;
assert(validJapanMarketComparison(withSigns, 5));
for (const mutate of [
  s => { s.predictiveProbabilities = 0.6; },
  s => { s.actionAuthority = true; },
  s => { s.conditions.D01.predictiveProbabilities = 0.55; },
  s => { s.conditions.D01.horizons[5].fallShare = 1.4; },
  s => { s.conditions.D01.horizons[5].falls = 99; },
  s => { s.conditions.D02.status = 'ABOVE_BASELINE'; },            // 4 activations cannot beat the baseline
  s => { s.conditions.D01.status = 'INSUFFICIENT_SAMPLE'; },       // 31 is not insufficient
  s => { s.conditions.D01.status = 'PROBABLE'; },
  s => { delete s.conditions.D07; },
  s => { s.conditions.D08 = s.conditions.D01; },
  s => { s.conditions.D03.family = 'D04'; },
  s => { s.conditions.D03.periods = s.conditions.D03.periods.slice(1); },
  s => { s.conditions.D01.firstActivation = 'yesterday'; },
  s => { s.conditions.D01.activations = 40; },                       // more than raw activations
  s => { s.schemaVersion = 'other'; },
]) {
  const invalid = structuredClone(withSigns); mutate(invalid.forecast.signEventStudy);
  assert(!validJapanMarketComparison(invalid, 5), mutate.toString());
}
console.log('Japan comparison seven warning conditions event study shape PASS');
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
const withProxy = { ...withScale, valuationEvidence: {
  date: document.anchorDate, eps: 3006.25, per: 21.78,
  epsKind: 'PROXY_FROM_CONSTITUENT_FORECAST_EPS', knownAt: '2026-09-11T07:30:00Z',
  publishedAt: null, sourceRef: 'argus:index-valuation-proxy:jquants+nikkei-weights', sourceResponseSha256: null,
} };
assert(validJapanMarketComparison(withProxy, 5));
for (const patch of [{ sourceResponseSha256: 'a'.repeat(64) }, { sourceRef: 'https://indexes.nikkei.co.jp/nkave/archives/summary/' },
  { sourceRef: 'argus:index-valuation-proxy:javascript:alert(1)' }, { epsKind: 'DERIVED_FROM_INDEX_CLOSE_AND_INDEX_BASED_PER' }]) {
  assert(!validJapanMarketComparison({ ...withProxy, valuationEvidence: { ...withProxy.valuationEvidence, ...patch } }, 5));
}
console.log('Index valuation evidence validation PASS (official and ARGUS proxy shapes)');
const withCoverage = { ...document, historyCoverage: {
  sourceBars: 2450, sourceStart: '2016-09-16', sourceEnd: '2026-09-11',
  candidateCount: 2300, candidateStart: '2016-10-20', candidateEnd: '2026-08-10',
  calendarStart: '2016-09-16', calendarEnd: '2026-09-11',
  candidatesByYear: { '2016': 30, '2017': 240 },
  excluded: { missingCalendarOrPriceSession: 2, incompleteEpisode: 0 },
  maximumSelected: 3, selectedCount: 0, admittedCount: 0,
  allMarketFeaturesTenYearsVerified: false,
} };
assert(validJapanMarketComparison(withCoverage, 5));
for (const patch of [{ sourceBars: NaN }, { candidateCount: -1 },
  { candidatesByYear: { invalid: 2 } }, { sourceStart: 'unknown' }]) {
  assert(!validJapanMarketComparison({ ...withCoverage,
    historyCoverage: { ...withCoverage.historyCoverage, ...patch } }, 5));
}
console.log('Historical comparison coverage validation PASS');
const withSources = { ...document, sourceAcquisition: {
  sources: { jp_yield_curve: { observations: 2698, firstDate: '2015-09-01', lastDate: '2026-09-17',
    nativeFrequency: 'DAILY', originalVintageVerified: false, latestRawId: 'a'.repeat(64),
    lastKnownAt: '2026-09-20T02:00:00Z', expectedCalendarCoverageVerified: false } },
  historicalVintageVerified: false, full10yAllIndicatorsComplete: false,
} };
assert(validJapanMarketComparison(withSources, 5));
for (const patch of [{ historicalVintageVerified: true }, { full10yAllIndicatorsComplete: true },
  { sources: { unknown: {} } }]) {
  assert(!validJapanMarketComparison({ ...withSources, sourceAcquisition: { ...withSources.sourceAcquisition, ...patch } }, 5));
}

// 2026-10-02: record of the forecasts actually issued, judged against the majority direction.
const horizon = (h, patch = {}) => ({ horizonSessions: h, scoredForecasts: 30, directionalForecasts: 25, hits: 14,
  hitRate: 0.56, hitRateWilsonLower95: 0.37, naiveMajorityRate: 0.6, status: 'NOT_ABOVE_BASELINE',
  firstTargetDate: '2026-09-14', lastTargetDate: '2026-10-30', ...patch });
const record = { schemaVersion: 'argus-forecast-track-record-v1', instrumentId: 'NIKKEI_225_INDEX',
  minimumDirectionalForecasts: 20, predictiveProbabilities: null, actionAuthority: false,
  horizons: { 1: horizon(1), 5: horizon(5, { scoredForecasts: 3, directionalForecasts: 2, hits: 1, hitRate: 0.5,
    hitRateWilsonLower95: 0.09, naiveMajorityRate: 0.5, status: 'INSUFFICIENT_SAMPLE' }) } };
assert(validForecastTrackRecord(record));
for (const mutate of [
  r => { r.predictiveProbabilities = 0.56; },
  r => { r.actionAuthority = true; },
  r => { r.horizons[1].hits = 26; },
  r => { r.horizons[1].hitRate = 1.4; },
  r => { r.horizons[1].status = 'INSUFFICIENT_SAMPLE'; },
  r => { r.horizons[5].status = 'ABOVE_BASELINE'; },
  r => { r.horizons[5].horizonSessions = 10; },
  r => { r.horizons[1].directionalForecasts = 0; r.horizons[1].hits = 0; },
]) {
  const invalid = structuredClone(record); mutate(invalid);
  assert(!validForecastTrackRecord(invalid));
}
console.log('Issued forecast track record shape PASS');

// A fresh close remains usable while the independent analog calculation is unavailable.
const {comparisonReply, retainComparisonReply, comparisonReadInterval} = require('../src/lib/japanMarketComparisonReply.ts');
const levelMap = {schemaVersion:'jp-market-level-map-state-v1', actionAuthority:false, latest:null,
 missedMornings:[], chart:{schemaVersion:'jp-market-chart-layers-v1',today:'2026-10-06',start:'2026-04-05',end:'2027-01-06',
 points:[{date:'2026-10-06',close:70000,eps:4000,epsDate:'2026-10-05'}], current:null,
 pivots:[],pending:null,candidates:[],nearest:[],actionAuthority:false,automaticAiCalls:0}};
const fresh = comparisonReply({status:'unavailable',comparison:null,reason:'index_research_preparing',
 automaticAiCalls:0,actionAuthority:false,levelMap},5);
assert.equal(fresh.document,null);
assert.equal(fresh.levelMap.chart.points.at(-1).close,70000);
const retained = retainComparisonReply(fresh,{document,reason:null,lastSuccessfulAcquisitionAt:null,
 levelMap:{...levelMap,chart:{...levelMap.chart,points:[]}}});
assert.equal(retained.document,document);
assert.equal(retained.levelMap,fresh.levelMap,'新しい終値を端末の古い応答で上書きしない');
assert.throws(()=>comparisonReply({status:'unavailable',comparison:null,automaticAiCalls:1,actionAuthority:false,levelMap},5));
const malformed = comparisonReply({status:'unavailable',comparison:null,automaticAiCalls:0,actionAuthority:false,
 levelMap:{...levelMap,chart:{...levelMap.chart,points:[{date:'2026-10-06',close:'70000'}]}}},5);
assert.equal(malformed.levelMap,null);
assert.equal(retainComparisonReply(malformed,fresh).levelMap,fresh.levelMap,'不正な値で保存済みの表示を壊さない');
assert.equal(comparisonReadInterval(fresh,Date.parse('2026-10-06T06:31:00Z')),60_000);
assert.equal(comparisonReadInterval(fresh,Date.parse('2026-10-06T07:05:00Z')),600_000);
const pendingReply = {...fresh,levelMap:{...levelMap,chart:{...levelMap.chart,closePending:true}}};
assert.equal(comparisonReadInterval(pendingReply,Date.parse('2026-10-06T11:00:00Z')),60_000);
assert.equal(comparisonReadInterval(pendingReply,Date.parse('2026-10-06T16:00:00Z')),600_000);
assert.equal(comparisonReadInterval(pendingReply,Date.parse('2026-10-10T07:00:00Z')),600_000);
console.log('日経の新しい終値・過去比較の独立更新・引け後の読取間隔 PASS');

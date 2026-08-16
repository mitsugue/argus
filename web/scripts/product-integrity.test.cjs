#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const ts = require('typescript');

require.extensions['.ts'] = (m, filename) => {
  const src = fs.readFileSync(filename, 'utf8');
  const out = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText;
  m._compile(out, filename);
};

const semantics = require(path.join(__dirname, '..', 'src', 'domain', 'decisionView.ts'));
const desk = require(path.join(__dirname, '..', 'src', 'domain', 'assetDesk.ts'));
const probabilityTruth = require(path.join(__dirname, '..', 'src', 'domain', 'probabilityTruth.ts'));
let failed = 0;
function check(name, condition) {
  if (condition) console.log(`  ok  ${name}`);
  else { failed += 1; console.error(`FAIL  ${name}`); }
}

check('S1 semantic aliases resolve to the same key',
  semantics.semanticDecisionKey('様子見') === semantics.semanticDecisionKey('WAIT'));
check('S2 duplicate primary conclusions are detected',
  semantics.duplicateDecisionKeys(['WAIT', '様子見', '需給を確認']).includes('wait'));
check('S3 owner and entry actions remain separate contract fields',
  new Set(['ownerAction', 'entryAction']).size === 2);
check('S4 verified fact requires source and asOf',
  semantics.evidenceTruth({ state: 'VERIFIED_FACT' }).state === 'UNRESOLVED');
check('S5 stale evidence requires asOf',
  semantics.evidenceTruth({ state: 'STALE' }).state === 'UNAVAILABLE');
check('S6 unknown-state text budget is bounded',
  semantics.evidenceTruth({
    state: 'UNRESOLVED',
    confirmed: ['指数比', '同業比', '出来高', '余分'],
    missing: ['個別開示', '大口フロー', '決算', '余分'],
  }).confirmed.length === 3);
check('S7 unsupported probability never renders percent',
  semantics.probabilityDisplay(50, null).showPercent === false);
check('S8 complete probability provenance permits percent',
  semantics.probabilityDisplay(62, {
    method: 'walk-forward-v1',
    sampleSize: 64,
    calibration: 'BSS=0.075',
    outcomeDefinition: '5d positive close return',
    asOf: '2026-07-24T15:00:00+09:00',
  }).percentText === '62%');
check('S8b out-of-range probability is rejected instead of clamped',
  semantics.probabilityDisplay(140, {
    method: 'walk-forward-v1',
    sampleSize: 64,
    calibration: 'BSS=0.075',
    outcomeDefinition: '5d positive close return',
    asOf: '2026-07-24T15:00:00+09:00',
  }).reason === 'invalid_probability'
  && semantics.probabilityDisplay(140, {
    method: 'walk-forward-v1', sampleSize: 64, calibration: 'BSS=0.075',
    outcomeDefinition: '5d positive close return',
    asOf: '2026-07-24T15:00:00+09:00',
  }).showPercent === false);
check('S8c unresolved evidence never also claims a best hypothesis',
  semantics.evidenceTruth({
    state: 'UNRESOLVED',
    alternative: '決算が原因の有力候補',
    nextCheck: 'TDnetを確認',
  }).alternative === null);
check('S8d unknown evidence text is concise and deduplicated',
  (() => {
    const long = '未確認'.repeat(40);
    const truth = semantics.evidenceTruth({
      state: 'UNAVAILABLE',
      confirmed: [long, long],
      missing: [long, long, '追加不足'],
      nextCheck: long,
    });
    return truth.confirmed.length === 1 && truth.missing.length === 2
      && [...truth.confirmed, ...truth.missing, truth.nextCheck]
        .filter(Boolean).every((line) => line.length <= 64);
  })());
check('S8e breadth probability gate fails closed when holdout/freshness proof is missing',
  probabilityTruth.evaluateProbabilityTruth(
    probabilityTruth.unavailableProbabilityEvidence({
      serverEligible: true, oosEffectiveN: 150, ruleEffectiveN: 80,
    }),
    { UP: 45, RANGE: 35, DOWN: 20 },
  ).exactPercentageAllowed === false);

const base = {
  name: 'Example', market: 'JP', held: false, priceText: '¥100',
  priority: 'WATCH', dataStatus: 'live', rank: 7,
  whyCandidates: ['需給を確認'], nextCandidates: ['次の終値'],
  changeCandidates: ['出来高増加'],
};
const views = [
  desk.buildDecisionFirstView({ ...base, symbol: 'A', signalCode: 'EXIT', rank: 0 }),
  desk.buildDecisionFirstView({ ...base, symbol: 'B', signalCode: 'REVIEW', rank: 2 }),
  desk.buildDecisionFirstView({ ...base, symbol: 'C', signalCode: 'PAUSE', rank: 7 }),
  desk.buildDecisionFirstView({ ...base, symbol: 'D', held: true, signalCode: 'HOLD_ONLY', rank: 6 }),
];
const counters = desk.buildPortfolioCommand(views).counters;
check('S9 portfolio counters are mutually exclusive',
  counters.reduce((sum, counter) => sum + counter.count, 0) === views.length);
check('S10 DecisionView contract is populated once',
  views.every((view) => view.primaryAction === view.currentActionJa
    && view.reason === view.whyJa && view.nextCheck === view.nextJa));
check('S10b canonical views have zero duplicate primary decision keys',
  views.every((view) => semantics.duplicateDecisionViewKeys(view).length === 0));
check('S10c canonical views have zero contradictory states',
  views.every((view) => semantics.contradictoryDecisionStates(view).length === 0));
check('S10d incident override governs owner and entry actions',
  (() => {
    const view = desk.buildDecisionFirstView({
      ...base, symbol: 'E', held: true, signalCode: 'ENTER',
      actionOverride: 'EXIT_WATCH', ownerLabel: '保有継続・追加可', rank: 0,
    });
    return view.ownerAction === '撤退検討' && view.entryAction === '新規停止'
      && semantics.contradictoryDecisionStates(view).length === 0;
  })());

const scenarioSource = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'assetDesk', 'AssetScenarioPanel.tsx',
), 'utf8');
check('S11 scenario percent is gated by provenance',
  scenarioSource.includes('display.showPercent') && !scenarioSource.includes('{s.probability}%'));
const aiReviewSource = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'assetDesk', 'AssetAIReview.tsx',
), 'utf8');
const scoutSource = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'assetDesk', 'AssetEntryScout.tsx',
), 'utf8');
const incidentSource = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'dashboard', 'DownsideIncidentCard.tsx',
), 'utf8');
const alertCardSource = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'dashboard', 'AlertCard.tsx',
), 'utf8');
const researchSource = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'assetDesk', 'AssetResearchPanel.tsx',
), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'App.tsx'), 'utf8');
const notificationSource = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'NotificationPanel.tsx',
), 'utf8');
const settingsSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'routes', 'Settings.tsx'), 'utf8');
check('S12 uncalibrated AI and cause confidence never renders percent',
  aiReviewSource.includes('confidenceJa') && !aiReviewSource.includes('confidencePct')
  && scoutSource.includes('probabilityDisplay(v * 100).qualitative')
  && !scoutSource.includes('Math.round(v * 100)')
  && incidentSource.includes('probabilityDisplay(b.probability * 100).qualitative')
  && !incidentSource.includes('Math.round(b.probability * 100)')
  && researchSource.includes('probabilityDisplay(value * 100).qualitative')
  && !researchSource.includes('Math.round(p.newLongAccumulation * 100)'));
check('S12b legacy alert and downside surfaces are visibly evidence-only',
  alertCardSource.includes('data-authority-role="EVIDENCE_ONLY"')
  && alertCardSource.includes('EVIDENCE ONLY')
  && !alertCardSource.includes('<ActionPill')
  && incidentSource.includes('<b>RISK EVIDENCE:</b>')
  && incidentSource.includes('SDAのPrimary Actionを上書きしません')
  && !incidentSource.includes('<b>判断:</b>')
  && !incidentSource.includes('OVERRIDE_LABEL_JA'));
check('S13 navigation commits route state and canonical primary or asset hashes',
  appSource.includes('const commitLocation =')
  && appSource.includes('routeRef.current = target.route')
  && appSource.includes('history.pushState')
  && appSource.includes('routeHash(route)')
  && appSource.includes('assetDetailHash(symbol, section)'));
check('S14 shared controls expose their selected and close semantics',
  settingsSource.includes('aria-pressed={locale === value}')
  && notificationSource.includes('aria-label="通知"')
  && notificationSource.includes('DEVICE LOCAL'));

if (failed) {
  console.error(`\nproduct-integrity tests: ${failed} FAILED`);
  process.exit(1);
}
console.log('\nproduct-integrity tests: all passed');

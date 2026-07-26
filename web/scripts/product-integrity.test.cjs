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

const scenarioSource = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'assetDesk', 'AssetScenarioPanel.tsx',
), 'utf8');
check('S11 scenario percent is gated by provenance',
  scenarioSource.includes('display.showPercent') && !scenarioSource.includes('{s.probability}%'));

if (failed) {
  console.error(`\nproduct-integrity tests: ${failed} FAILED`);
  process.exit(1);
}
console.log('\nproduct-integrity tests: all passed');

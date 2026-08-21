#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};
const root = path.join(__dirname, '..');
const decision = require(path.join(root, 'src/domain/assetDecision.ts'));
const desk = require(path.join(root, 'src/domain/assetDesk.ts'));
let failed = 0;
function check(name, ok) { if (ok) console.log(`  ok  ${name}`); else { failed++; console.error(`FAIL  ${name}`); } }

const NOW = Date.parse('2026-08-16T03:00:00Z');
const aiMeta = decision.assessAi({ status: 'live', freshness: 'fresh',
  asOf: '2026-08-16T02:59:00Z', models: { primary: 'gpt', checker: 'gemini' } }, NOW);
const result = (action = 'WAIT', status = 'EVALUATED') => ({
  primaryAction: action, status, decisionId: `sda-${'1'.repeat(64)}`,
  confidence: { valueBps: 5500, status: 'BOUNDED' },
  guidance: { riskConstraint: 'WAIT_REQUIRED' }, missingReasonCodes: [], conflictReasonCodes: [],
});
const projected = decision.projectCanonicalAssetDecision({ symbol: '7203', result: result('EXIT'),
  ruleLabel: { symbol: '7203', action: 'ENTER', reasonJa: 'legacy' },
  aiLabel: { symbol: '7203', aiFinalAction: 'BUY', reasonJa: 'challenge' }, meta: aiMeta });
check('canonical SDA action owns the asset decision', projected.judgmentSource === 'sda'
  && projected.sourceTagEn === 'SDA PRIMARY' && projected.reasonJa.includes('EXIT'));
check('AI and rule remain dissent evidence only', projected.ai.authorityRole === 'EVIDENCE_ONLY'
  && projected.ai.finalDecisionAuthorityActive === false
  && projected.rule.authorityRole === 'EVIDENCE_ONLY'
  && projected.rule.disagreementJa.includes('SDA=EXIT'));
check('removed AI merge APIs cannot be called', decision.mergeAiPrimary === undefined
  && decision.resolveAssetDecision === undefined);

const view = desk.buildDecisionFirstView({ symbol: '7203', name: 'Toyota', market: 'JP', held: true,
  canonicalPrimaryAction: 'REDUCE', canonicalDecisionId: `sda-${'2'.repeat(64)}`,
  canonicalDecisionStatus: 'EVALUATED', canonicalConfidenceBps: 6200,
  sevenSignStatus: 'SHADOW', sevenSignLevel: 2,
  targets: [{ value: '3000', unit: 'PRICE' }],
  invalidation: { value: '2500', unit: 'PRICE' }, freshness: 'FRESH',
  priceText: '¥2,700', changePct: -2, pnlPct: -5, priority: 'P0', dataStatus: 'LIVE', rank: 0,
  whyCandidates: ['risk'], nextCandidates: ['review'], changeCandidates: ['invalidate'],
  actionOverride: 'EXIT_WATCH', signalCode: 'ENTER', ownerLabel: 'small_add_allowed',
});
check('legacy override fields cannot alter canonical asset action', view.canonicalPrimaryAction === 'REDUCE'
  && view.currentActionJa.includes('REDUCE') && view.signalCode === 'DEFEND');
check('Seven Sign and decision levels remain projected, not recomputed', view.sevenSignLevel === 2
  && view.sevenSignStatus === 'SHADOW' && view.targets[0].value === '3000'
  && view.invalidation.value === '2500');
const missing = desk.buildDecisionFirstView({ symbol: 'AAPL', name: 'Apple', market: 'US', held: false,
  priceText: '$200', priority: 'WATCH', dataStatus: 'unknown', rank: 9,
  whyCandidates: [], nextCandidates: [], changeCandidates: [] });
check('missing canonical action fails closed to WAIT', missing.canonicalPrimaryAction === 'WAIT'
  && missing.currentActionJa === 'WAIT');

const list = fs.readFileSync(path.join(root, 'src/components/assetDesk/AssetDeskList.tsx'), 'utf8');
const card = fs.readFileSync(path.join(root, 'src/components/assetDesk/AssetDecisionCard.tsx'), 'utf8');
const summary = fs.readFileSync(path.join(root, 'src/components/assetDesk/AssetDecisionSummary.tsx'), 'utf8');
check('Asset Desk consumes one SDA map and no primary stance map', list.includes('intel.sdaBySymbol')
  && !list.includes('stanceBySymbol') && !fs.existsSync(path.join(root, 'src/domain/primaryStance.ts')));
check('Entry Scout action surface is retired', !fs.existsSync(path.join(root, 'src/components/assetDesk/AssetEntryScout.tsx'))
  && !card.includes('EntryScout'));
check('compact card exposes canonical action without priority or seven-vote clutter',
  summary.includes('canonicalPrimaryAction') && !summary.includes('Calibration pending')
  && !summary.includes('ad-prio'));
check('owner list is grouped and long-press ordered instead of priority sorted',
  list.includes('delay: 450') && !list.includes('sortMode')
  && !list.includes('AssetPortfolioCommand'));

if (failed) process.exit(1);
console.log('asset-desk.test: all checks passed');

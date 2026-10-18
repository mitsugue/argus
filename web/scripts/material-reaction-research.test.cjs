const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText, filename);
const { validMaterialReactionResearch } = require('../src/lib/japanMarketComparison.ts');
const m = { directionalEvaluations: 120, hits: 66, hitRate: .55, naiveMajorityRate: .57, meanAbsoluteError: 1.9 };
const block = { adopted: false, reason: 'not_better_in_decision_period', horizon: 5, decisionStart: '2018-01-05',
  decisionEnd: '2024-03-01', reportStart: '2024-03-08', reportEnd: '2026-09-04', decisionWith: m, decisionWithout: m,
  heldOutWith: m, heldOutWithout: { ...m, hitRate: null }, researchReactionRows: 1440, candidatesWithReactions: 2100,
  predictiveProbabilities: null };
assert.ok(validMaterialReactionResearch(block));
for (const bad of [null, { ...block, adopted: 'yes' }, { ...block, predictiveProbabilities: .6 },
  { ...block, decisionWith: { ...m, hitRate: -1 } }, { ...block, researchReactionRows: 1.5 }, { ...block, heldOutWith: null }])
  assert.equal(validMaterialReactionResearch(bad), false);
const chart = fs.readFileSync('src/components/chart/JapanMarketComparisonChart.tsx', 'utf8');
assert.ok(chart.includes('実際の公表時刻は確認していません') && chart.includes('将来の確率ではありません'));
assert.ok(chart.includes('判断に使っていない期間'));
console.log('material reaction research display contract PASS');

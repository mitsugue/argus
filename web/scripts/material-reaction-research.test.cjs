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
const chart = fs.readFileSync('src/components/chart/MaterialReactionLine.tsx', 'utf8');
for (const host of ['JapanMarketComparisonChart.tsx', 'NikkeiResearchChart.tsx'])
  assert.ok(fs.readFileSync('src/components/chart/' + host, 'utf8').includes('<MaterialReactionLine research='), host);
// 2026-10-18 (owner): one plain line, adopted or not, with the before/after rate.
assert.ok(chart.includes('経済指標の発表反応：') && chart.includes('使用中') && chart.includes('不使用'));
assert.ok(chart.includes('r.heldOutWithout') && chart.includes('r.decisionWithout') && chart.includes('差が偶然の範囲'));
const line = require('react-dom/server').renderToStaticMarkup;
const React = require('react');
const tsx = (f) => { const m = { exports: {} }; new Function('exports', 'require', 'module', ts.transpileModule(fs.readFileSync(f, 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText)(m.exports,
  n => n.startsWith('../../lib/') ? require('../src/lib/' + n.slice(10) + '.ts') : require(n), m); return m.exports; };
const parts = tsx('src/components/chart/MaterialReactionLine.tsx');
const reason = '今週は過去10年に似た局面がありません（最も近い2024-07-22でも距離1.02・上限1）。主な違い：日本10年金利の変化幅・NT倍率の変化率。';
assert.ok(line(React.createElement(parts.NoAnalogLine, { document: { noAnalogExplanation: { textJa: reason } } })).includes('主な違い'));
assert.equal(parts.noAnalogText({ noAnalogExplanation: { textJa: 'x'.repeat(201) } }), null);
assert.equal(parts.noAnalogText({}), null);
const chartSource = fs.readFileSync('src/components/chart/JapanMarketComparisonChart.tsx', 'utf8');
assert.ok(chartSource.includes('noAnalogText(document) ??') && chartSource.includes('<YardstickLine'));
const y = { adopted: false, decisionWith: { hitRate: .45 }, decisionWithout: { hitRate: .44 }, heldOutWith: { hitRate: .5 }, heldOutWithout: { hitRate: .5 } };
assert.ok(line(React.createElement(parts.YardstickLine, { research: y })).includes('不採用'));
assert.ok(line(React.createElement(parts.YardstickLine, { research: { ...y, adopted: true } })).includes('採用（'));
assert.equal(line(React.createElement(parts.YardstickLine, { research: { adopted: 'yes' } })), '');
console.log('material reaction research display contract PASS');

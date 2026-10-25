// 2026-10-19: in the existing comparison chart, one or two admitted episodes are labelled as a thin basis.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ts = require('typescript');
const ctx = { exports: {}, require: name => name.endsWith('.css') ? {}
  : name === '../../hooks/useJapanMarketComparison' ? { useForecastTrackRecord: () => null }
  : name === './MaterialReactionLine' ? { MaterialReactionLine: () => null, YardstickLine: () => null, noAnalogText: () => null }
  : require(name), Number, Array, Math, Object, JSON, Date };
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/chart/JapanMarketComparisonChart.tsx', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true, target: ts.ScriptTarget.ES2022 } }).outputText, ctx);
const { fewAnalogsText } = ctx.exports;
const base = { candidates: [{ anchorDate: '2024-07-22' }], selectionPolicy: { maximumDistance: 1 },
  selectionAudit: { 2024: { closest: { anchorDate: '2024-07-22', distance: 0.9595, rank: 1, status: 'SELECTED' } } } };
const one = fewAnalogsText(base);
assert.match(one, /似た局面は1件（2024-07-22・距離0\.96／上限1）/);
assert.ok(!/ありません/.test(one), 'no disclaimer (owner 2026-10-25)');
assert.match(fewAnalogsText({ ...base, candidates: [{ anchorDate: '2024-07-22' }, { anchorDate: '2019-05-07' }] }), /2件（2024-07-22・距離0\.96、2019-05-07／上限1）/);
assert.equal(fewAnalogsText({ ...base, candidates: [] }), null);
assert.equal(fewAnalogsText({ ...base, candidates: [1, 2, 3].map(i => ({ anchorDate: `201${i}-01-04` })) }), null);
const source = fs.readFileSync('src/components/chart/JapanMarketComparisonChart.tsx', 'utf8');
assert.ok(source.includes('なし（1件）'), '線が出ない時は件数で示す');
assert.ok(source.includes('data-comparison-few='), '件数の1行を表示する');
console.log('few analogs: ok');

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
// 2026-10-27 (owner): with no similar window, the closest three are drawn as references with their distance.
const React = require('react'), { renderToStaticMarkup } = require('react-dom/server');
const { JapanMarketComparisonChart } = ctx.exports;
const pts = (v) => [{ offsetSessions: -1, value: v }, { offsetSessions: 0, value: 100 }];
const after = (v) => [{ offsetSessions: 0, value: 100 }, { offsetSessions: 5, value: v }];
const near = [['2018-12-20', 1.1056, 98], ['2022-03-07', 1.148, 103], ['2023-01-06', 1.1667, 101]]
  .map(([anchorDate, distance, v], i) => ({ snapshotId: 's' + i, anchorDate, distance, comparison: pts(99 + i), subsequentReference: after(v) }));
const doc = { schemaVersion: 'jp-market-comparison-v1', informationCutoff: '2026-10-26T08:00:00Z', anchorDate: '2026-10-26',
  actualAnchorPrice: 62189.65, unit: 'ANCHOR_100', actual: pts(101), candidates: [], nearestReferences: near,
  selectionPolicy: { maximumDistance: 1, stateScales: {} },
  forecast: { status: 'NO_STRONG_ANALOG', line: [], band: [], horizonSessions: 5, validationStatus: 'UNVALIDATED',
    sampleCount: 0, counts: { up: 0, flat: 0, down: 0 }, flatThresholdPct: .5 },
  scaleExplanation: 'x', limitations: [] };
const html = renderToStaticMarkup(React.createElement(JapanMarketComparisonChart, { document: doc }));
assert.equal((html.match(/data-series="nearest-reference"/g) || []).length, 3, '最も近い3つを描く');
assert.equal((html.match(/data-series="nearest-subsequent-reference"/g) || []).length, 3, 'その後も描く');
assert.match(html, /参考 2018-12-20・距離1\.11/); assert.match(html, /参考 2023-01-06・距離1\.17/);
assert.match(html, /似た局面なし（上限1）・最も近い3つを参考に表示/);
// 2026-10-27 (owner): each reference has its own colour and its year-month at the line's end.
assert.equal((html.match(/data-nearest-label=/g) || []).length, 3, '線の端に年と月');
assert.match(html, />2018\/12</); assert.match(html, />2022\/3</);
assert.equal(new Set((html.match(/data-series="nearest-reference"[^>]*stroke="(#[0-9a-f]{6})"/g) || [])).size, 3, '3本は別の色');
assert.ok(!html.includes('data-series="current-forecast"'), '予想の線にはしない');
const withCandidate = renderToStaticMarkup(React.createElement(JapanMarketComparisonChart, { document: { ...doc,
  candidates: [{ snapshotId: 'c', anchorDate: '2019-05-07', comparisonKind: 'MARKET_ANALOG', comparison: pts(99),
    subsequentReference: after(100), missingFeatures: [], missingGroups: [], similarReasons: [], differences: [] }] } }));
assert.ok(!withCandidate.includes('nearest-reference'), '似た局面がある時は参考を描かない');
const lib = fs.readFileSync('src/lib/japanMarketComparison.ts', 'utf8');
assert.ok(lib.includes('v.candidates.length) return false'), '参考は候補が無い時だけ受け付ける');
console.log('few analogs: ok');

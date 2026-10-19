// Future lines (2026-10-19): validation, drawing frame and the two new chart tabs.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ts = require('typescript'), React = require('react'), {renderToStaticMarkup} = require('react-dom/server');
function load(file, requireModule = require) {
  const ctx = {exports:{}, require:requireModule, Date, Number, Array, Math, Object, JSON, ResizeObserver: undefined};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'), {
    compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true,target:ts.ScriptTarget.ES2022}
  }).outputText, ctx); return ctx.exports;
}
const lib = load('src/lib/futureLines.ts');
const line = (rec, pts) => ({rec, recordedAt:'2026-10-19T11:03:57+09:00', eps:3826.848, points:pts});
const doc = {schemaVersion:'argus-future-lines-public-v1', availability:'AVAILABLE', updatedAt:'2026-10-24T09:40:00+09:00', dataEnd:'2026-10-23',
  lines:{commentator: line('2026-10-16',[{kind:'L',date:'2026-10-30',price:61230},{kind:'H',date:'2026-11-10',price:65056.4}]),
         machine: line('2026-10-16',[{kind:'H',date:'2026-10-19',price:68883.3},{kind:'L',date:'2026-10-29',price:65056.4}]),
         machine2: line('2026-10-16',[{kind:'L',date:'2026-10-23',price:65056.4},{kind:'H',date:'2026-11-11',price:68883.3}])},
  history:{commentator:[line('2026-10-09',[{kind:'L',date:'2026-10-20',price:63000}])]},
  wave:{pub:'2026-10-22',recordedAt:'2026-10-24T09:40:00+09:00',dir:'up',target:71540,stop:64946,result:'pending',settledBeforeRecord:false},
  record:{commentator:{records:1,strict:{hit:0,n:0,pending:5,randomMean:null},standard:{hit:0,n:0,pending:5,randomMean:null},
    loose:{hit:1,n:2,pending:3,randomMean:0.6},timing:{hit:0,n:0,pending:5,randomMean:null},reach:{reach:0,stop:0,expire:0,pending:1,'n/a':0}}},
  retroRecord:{commentator:{records:21,strict:{hit:5,n:28,pending:15,randomMean:3.08},standard:{hit:9,n:28,pending:15,randomMean:5.91},
    loose:{hit:20,n:28,pending:15,randomMean:10.97},timing:{hit:12,n:28,pending:15,randomMean:9.12},reach:{reach:11,stop:7,expire:0,pending:0,'n/a':3}}},
  closes:[{date:'2026-10-15',close:64425.95},{date:'2026-10-16',close:65324.29}], actionAuthority:false, argusValidated:false};
assert.equal(lib.validFutureLines(doc), true);
assert.equal(lib.validFutureLines({...doc, actionAuthority:true}), false);
assert.equal(lib.validFutureLines({...doc, lines:{other: doc.lines.machine}}), false, '決まった線だけ');
assert.equal(lib.validFutureLines({...doc, lines:{machine: line('2026-10-16',[{kind:'L',date:'2026-10-29',price:1},{kind:'H',date:'2026-10-20',price:2}])}}), false, '日付は先へ進む順');
assert.equal(lib.validFutureLines({...doc, wave:{...doc.wave, target:60000}}), false);
const frame = lib.linesFrame(doc, ['commentator']);
assert.equal(frame.shown.length, 2, '最新と前の週');
assert.ok(frame.low < 61230 && frame.high > 71540, '目標・崩れ・点がすべて入る範囲');
assert.equal(JSON.stringify(frame.multiples.slice(0, 2)), '[16,17]');
assert.equal(JSON.stringify(lib.pathPoints(doc.lines.commentator, doc.closes)[0]), JSON.stringify({date:'2026-10-16', price:65324.29}), '線は記録した日の終値から');
const chartModule = load('src/components/chart/FutureLinesChart.tsx', name => {
  if (name === '../../lib/futureLines') return lib;
  if (name === '../../hooks/useFutureLines') return {useFutureLines: () => ({doc, status:'ready'})};
  if (name.endsWith('.css')) return {};
  return require(name);
});
const html = renderToStaticMarkup(React.createElement(chartModule.FutureLinesChartView, {doc}));
assert.match(html, /動画解説の線/); assert.match(html, /谷 10\/30 61,230円/); assert.match(html, /波動の公開予想の目標 71,540円/);
assert.match(html, /20\/28/, '後から読み取った分の参考の成績');
assert.match(html, />11月</, '月の目盛り'); assert.match(html, /まだ事前の記録がありません/);
assert.doesNotMatch(html, /src_[abc]/, '出どころの記号を出さない(名前は配信前の命名の検査で確かめる)');
assert.match(html, /機械1（2018年の暦）/); assert.match(html, /機械2（直近の間隔）/, '3本の線を1つのチャートに');
assert.match(html, /日付の当たりは機械1・機械2ともでたらめと同じ/);
const panel = fs.readFileSync('src/components/chart/JapanMarketComparisonPanel.tsx','utf8');
for (const label of ['価格の目盛りと参考予測','従来の過去比較','未来の線の記録']) assert.ok(panel.includes(`>${label}</button>`), label);
assert.equal((panel.match(/onClick=\{\(\) => setMode\(/g) || []).length, 3, '日経のチャートの切り替えは3つ(足したのは1つ)');
console.log('future lines: ok');

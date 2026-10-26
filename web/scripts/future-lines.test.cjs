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
// 2026-10-25 (owner, simplified view): short names, a next-turn table with a one-line score,
// everything else behind one fold.
// 2026-10-26 (owner): only the video's line is drawn and tabled; the machine lines are yardsticks in the fold.
assert.match(html, /動画の線（毎週の山・谷の予想）/);
assert.doesNotMatch(html.slice(0, html.indexOf('fl-details')), /2018年の暦|山谷の間隔/, '線は1本');
assert.doesNotMatch(html, /機械1|機械2|動画解説の線|白＝動画の予想線/, '長い説明と古い名前は出さない');
assert.match(html, /次の転換点（10\/16の終値まで・毎週土曜に更新）/);
const next = html.slice(html.indexOf('future-lines-next-v1'), html.indexOf('fl-details'));
assert.match(next, /谷 10\/30<\/td><td>61,230円/, '動画の線の次は10/23より後の最初の点');
assert.equal(lib.nextTurn(doc.lines.machine2, '2026-10-23').date, '2026-11-11', '過ぎた点(10/23)は飛ばす');
const later = renderToStaticMarkup(React.createElement(chartModule.FutureLinesChartView, {doc:{...doc, dataEnd:'2026-10-22', closes:[...doc.closes, {date:'2026-10-23', close:62693}]}}));
assert.doesNotMatch(later.slice(later.indexOf('future-lines-next-v1')), /谷 10\/23<\/td>/, '手元の終値の日までの点は次に出さない');
assert.match(next, /当たり 1\/2（偶然なら0.6）|判定前/);
assert.match(next, /判定前/, '標準の物差しで判定が無ければ判定前');
assert.equal(lib.scoreJa({records:2, standard:{hit:3,n:5,pending:1,randomMean:1.6}}), '当たり 3/5（偶然なら1.6）');
assert.match(next, /波動の公開予想（10\/22）：上向き・目標 71,540円・崩れ 64,946円 → 判定待ち/);
const fold = html.slice(html.indexOf('fl-details'));
assert.match(fold, /<summary>線の全部の点・成績の詳しい見方<\/summary>/);
assert.match(fold, /谷 10\/30 61,230円/); assert.match(fold, /20\/28/, '後から読み取った分の参考の成績');
assert.match(fold, /比べる物差し（2018年の暦・山谷の間隔）は、2010〜2025年の検証で日付の当たりがでたらめと同じ/); assert.match(fold, /波動の公開予想：記録なし/);
assert.match(html, /波動の公開予想の目標 71,540円/); assert.match(html, />11月</, '月の目盛り');
assert.doesNotMatch(html, /src_[abc]/, '出どころの記号を出さない(名前は配信前の命名の検査で確かめる)');
assert.equal((html.match(/class="fl-point-label"/g) || []).length, 2, '点の文字は動画の線だけ');
const panel = fs.readFileSync('src/components/chart/JapanMarketComparisonPanel.tsx','utf8');
// 2026-10-26 (owner): the past similar periods chart is offered again; the future lines view is
// removed because the reference forecast carries the newest drawn line.
for (const label of ['価格の目盛りと<wbr />参考予測','過去の似た局面']) assert.ok(panel.includes(`>${label}</button>`), label);
assert.ok(!panel.includes('未来の線') && !panel.includes('FutureLinesChart'), '未来の線の切り替えは外す(2026-10-26 オーナー)');
assert.ok(panel.includes('<JapanMarketComparisonPanel key={horizon} horizon={horizon} />'));
assert.ok(panel.includes('jp-comparison-periods jp-comparison-views'), '切り替えは1行に並べる');
assert.equal((panel.match(/onClick=\{\(\) => setMode\(/g) || []).length, 2, '日経のチャートの切り替えは2つ(2026-10-26 オーナー)');
console.log('future lines: ok');

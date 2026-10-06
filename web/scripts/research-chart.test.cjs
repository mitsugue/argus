const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ts = require('typescript'), React = require('react'), {renderToStaticMarkup} = require('react-dom/server');
function load(file, requireModule = require) {
  const ctx = {exports:{}, require:requireModule, Date, Number, Array};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'), {
    compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true,target:ts.ScriptTarget.ES2022}
  }).outputText, ctx);return ctx.exports;
}
const levelLib = load('src/lib/levelMap.ts');
const lib = load('src/lib/researchChart.ts', name => name === './levelMap' ? levelLib : require(name));
const chart = {schemaVersion:'jp-market-chart-layers-v1',today:'2026-10-05',start:'2026-04-04',end:'2027-01-05',
 points:[{date:'2026-10-01',close:68957,eps:3900,epsDate:'2026-09-30'}, {date:'2026-10-02',close:68309,eps:null,epsDate:null}],
 current:{morningOf:'2026-10-05',eps:3932.61,epsDate:'2026-10-02',previousClose:68309,previousSession:'2026-10-02',atr14:1235},
 pivots:[],pending:{date:'2026-10-01',kind:'TOP',price:68957,confirmPrice:66198.72},candidates:[],nearest:[],actionAuthority:false,automaticAiCalls:0};
assert.equal(lib.validResearchChart(chart),true);
const recentWindow=lib.chartWindow(chart,true);
assert.equal(recentWindow.start,Date.parse('2026-09-05T00:00:00Z'));
assert.equal(recentWindow.end,Date.parse('2026-12-04T00:00:00Z'));
assert.equal(lib.chartWindow(chart,true,9999).end,lib.dayNumber(chart.end));
assert.equal(lib.chartWindow(chart,true,-9999).start,lib.dayNumber(chart.start));
assert.equal(lib.chartWindow(chart,false).start,lib.dayNumber(chart.start));
const view=lib.researchViewport(chart);
const zoomed=lib.zoomResearchViewport(chart,view,2,.25);
assert.equal(zoomed.end-zoomed.start,(view.end-view.start)/2);
assert.equal(zoomed.start+.25*(zoomed.end-zoomed.start),view.start+.25*(view.end-view.start),'指を置いた日付を保つ');
assert.equal(lib.researchViewport(chart,1).end-lib.researchViewport(chart,1).start,14*86400000);
assert.equal(lib.researchViewport(chart,90,0).start,lib.dayNumber(chart.start));
assert.equal(lib.researchViewport(chart,90,Infinity).end,lib.dayNumber(chart.end));
assert.equal(lib.validResearchChart({...chart,actionAuthority:true}),false);
assert.equal(lib.validResearchChart({...chart,points:[{...chart.points[0],epsDate:'2026-10-01'}]}),false);
assert.equal(lib.validResearchChart({...chart,candidates:[{id:'c',label:'R1',start:'2026-10-05',end:'2026-10-01',target:100,stop:200}]}),false);
const segments=lib.perSegments(chart,18);
assert.equal(segments.length,2,'欠測をまたいでPER線をつながない');
assert.equal(segments[0][0].value,70200);
assert.equal(segments[1][0].value,3932.61*18);
const future={rows:[{id:'a',start:'2026-10-30',end:'2026-10-30',level:{low:63300,high:63300},tag:'谷'},
 {id:'b',start:'2026-11-21',end:'2026-11-24',level:{low:63500,high:63700},tag:'底'},
 {id:'old',start:'2026-10-01',end:'2026-10-02',level:{low:60000,high:60000},tag:'過去'},
 {id:'missing',start:'2026-11-01',end:'2026-11-02',level:null,tag:'水準なし'},
 {id:'bad',start:'2026-11-01',end:'2026-11-02',level:{low:70000,high:60000},tag:'逆転'},
 {id:'far',start:'2027-05-01',end:'2027-05-01',level:{low:70000,high:70000},tag:'範囲外'}]};
const points=lib.externalPoints(future,chart);
assert.equal(points.length,2);assert.equal(points[0].value,63300);assert.equal(points[1].value,63600);
assert.equal(points[1].at,(Date.parse('2026-11-21T00:00:00Z')+Date.parse('2026-11-24T00:00:00Z'))/2);
const currentPeriod={rows:[{id:'current',start:'2026-10-01',end:'2026-10-10',level:{low:69700,high:72000},tag:'天井圏'}]};
assert.equal(lib.externalPoints(currentPeriod,{...chart,today:'2026-10-07'}).length,1,'中央の日を過ぎても予測期間中は消さない');
assert.equal(lib.externalPoints(currentPeriod,{...chart,today:'2026-10-11'}).length,0,'期間終了後は最新の参考予測から外す');
const components=load('src/components/chart/NikkeiResearchChart.tsx',name=>name.endsWith('.css')?{}:
 name.includes('/researchChart')?lib:name.includes('/hooks/')?{}:require(name));
const html=renderToStaticMarkup(React.createElement(components.NikkeiResearchChartView,{chart,future}));
assert.ok(html.includes('PER18 70,787円'));
assert.ok(html.includes('参考予測（未検証）'));
assert.ok(html.includes('決算データから計算したARGUS推計'));
assert.ok(html.includes('公式は日経の予想利益') && html.includes('公式PERから引いた線ではありません'));
assert.ok(html.includes('1 谷')&&html.includes('2 底'));
assert.ok(html.includes('EPSがない日はPER線を途切れさせています'));
assert.ok(html.includes('aria-label="拡大"')&&html.includes('今日へ戻る'));
assert.ok(html.includes('前日終値より下')&&html.includes('10/30〜10/30'));
assert.ok(html.includes('特定の日の到達予想ではありません'));
assert.ok(!html.includes('NaN')&&!html.includes('Infinity'));
assert.ok(html.includes('10/1の山は未確定'),'高値・安値は初期状態で表示する');
assert.ok(!html.includes('aria-label="チャートに重ねる情報"'),'不要な線の切り替えは出さない');
assert.ok(html.includes('今日10/5の現在値は、この図には含まれていません'));
console.log('研究チャートの日付・水準・欠測・未検証表示 PASS');

const latestClose = {...chart,points:[...chart.points,{date:'2026-10-05',close:70000,eps:3932.61,epsDate:'2026-10-02'}]};
const closeHtml = renderToStaticMarkup(React.createElement(components.NikkeiResearchChartView,{chart:latestClose,future}));
assert.ok(closeHtml.includes('当日終値 70,000円'));
assert.ok(!closeHtml.includes('前日終値 68,309円'));
assert.ok(closeHtml.includes('当日終値より下'));
assert.ok(!closeHtml.includes('今日10/5の現在値は'));

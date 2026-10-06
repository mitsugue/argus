const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(
  fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022 }, fileName: filename }).outputText, filename);
const d = require('../src/lib/todayDecision.ts');

// The tone's own record: no tone beats the all-days base rate, so it is never a direction call.
assert(Math.abs(d.TONE_HISTORY.upAfter.tail - d.TONE_HISTORY.baseUpPct) <= 3);
assert(d.TONE_HISTORY.upAfter.head >= 50, 'after a headwind tone the index still rose more often than not');

// Alert cut points and the 80% band come from the 2003-2014 fit.
assert.equal(d.alertLevel(0.10), 'low');
assert.equal(d.alertLevel(0.20), 'normal');
assert.equal(d.alertLevel(0.2608), 'high');
const band = d.fiveDayBand(0.198);
assert(band.lower < 0 && band.upper > 0 && Math.abs(band.lower + 3.58) < 0.05 && Math.abs(band.upper - 3.84) < 0.05, JSON.stringify(band));

// A flat path has no volatility; 21 points are required.
const flat = Array.from({ length: 21 }, (_, i) => ({ offsetSessions: i - 20, value: 100 }));
assert.equal(d.realisedVol20(flat), 0);
assert.equal(d.realisedVol20(flat.slice(1)), null);

const path = Array.from({ length: 21 }, (_, i) => ({ offsetSessions: i - 20, value: 100 * (1 + 0.01 * Math.sin(i)) }));
path[20].value = 104; path[19].value = 101; path[15].value = 100;
const features = [
  { seriesId: 'vix.level', date: '2026-09-30', value: 16.34 },
  { seriesId: 'vix.change5', date: '2026-09-30', value: 1.16 },
  { seriesId: 'foreign_flow.net4w', date: '2026-09-25', value: -349857010000 },
  { seriesId: 'margin1570.ratio', date: '2026-09-30', value: 5.7376 },
  { seriesId: 'rate.us10y_change5', date: '2026-09-29', value: 0.30 },
  { seriesId: 'fx.usdjpy_change5', date: '2026-09-30', value: -0.04 },
  { seriesId: 'event.sq_sessions', date: '2026-10-01', value: 5 },
];
const s = d.decisionStrip(path, features);
assert.equal(s.close, 104);
assert(Math.abs(s.dayChangePct - (104 / 101 - 1) * 100) < 1e-9);
assert(Math.abs(s.fiveDayChangePct - 4) < 1e-9);
assert(s.sigma > 0 && ['low', 'normal', 'high'].includes(s.alert));
assert.equal(s.momentum, 'strong');
const ids = s.rows.map(r => r.id);
assert.deepEqual(ids, ['foreign', 'us10y', 'm1570', 'vix', 'trend', 'sq'], 'small FX moves are left out');
assert(s.rows.find(r => r.id === 'foreign').title.includes('約3,499億円の売り越し'));
assert.equal(s.rows.find(r => r.id === 'm1570').lean, 'soft-head');
assert(s.rows.every(r => r.what && r.now && r.soWhat), 'every row explains what, now and so what');
assert.equal(s.rows.find(r => r.id === 'us10y').lean, 'neutral', 'the 10-year yield has no measured direction');
assert(s.rows.find(r => r.id === 'us10y').soWhat.includes('61%'));
assert.equal(s.tone, 'wait', 'one headwind and a soft headwind against one tailwind');
assert.equal(s.overnightGapPct, null);

// Overnight future (owner check 2026-10-03): its own record, double weight, band shifted by the gap.
const night = d.decisionStrip(path, features, 2.2);
assert.equal(night.rows[0].id, 'futures');
assert.equal(night.rows[0].lean, 'tail');
assert(night.rows[0].meaning.includes('86%') && night.rows[0].soWhat.includes('+4.1%'));
assert.equal(night.tone, 'tail', 'a +2.2% night outweighs the mixed inputs');
assert(Math.abs(night.band.lower - (s.band.lower + 2.2)) < 1e-9 && Math.abs(night.band.upper - (s.band.upper + 2.2)) < 1e-9);
assert.equal(d.overnightRecord(-2.5).upPct, 17);
assert.equal(d.overnightRecord(0.3).upPct, 57);
assert.equal(d.decisionStrip(path, features, 0.4).rows[0].lean, 'neutral');
const closeAt = Date.parse('2026-10-02T06:30:00Z');
const fut = { price: 69785, tradedAt: '2026-10-02T20:59:00Z' };
assert(Math.abs(d.overnightGap(fut, 68309.46, closeAt, false) - (69785 / 68309.46 - 1) * 100) < 1e-9);
assert.equal(d.overnightGap(fut, 68309.46, closeAt, true), null, 'ignored while Tokyo trades');
assert.equal(d.overnightGap({ ...fut, tradedAt: '2026-10-02T05:00:00Z' }, 68309.46, closeAt, false), null, 'before the close');
assert.equal(d.overnightGap({ ...fut, tradedAt: '2026-10-07T05:00:00Z' }, 68309.46, closeAt, false), null, 'stale');
assert.equal(d.overnightGap(null, 68309.46, closeAt, false), null);

// Missing inputs never invent values.
const empty = d.decisionStrip(null, []);
assert.equal(empty.close, null); assert.equal(empty.alert, null); assert.equal(empty.band, null);
assert.deepEqual(empty.rows, []); assert.equal(empty.tone, 'wait');
assert.equal(d.decisionStrip(null, [], 2).band, null, 'no band without volatility, even with a future');

// Machine sentences become readable numbers, without the repeated disclaimer.
assert.equal(d.friendlyFactText('2026-09-25時点、海外投資家の4週純売買合計（円）: -349857010000.0000。観測値からの記述計算であり、予測力は未検証。'),
  '2026-09-25時点、海外投資家の4週純売買合計（円）: -3,499億円。');
assert.equal(d.friendlyFactText('2026-09-30時点、VIX終値: 16.3400。観測値からの記述計算であり、予測力は未検証。'),
  '2026-09-30時点、VIX終値: 16.34。');
console.log('Today decision strip PASS');
const at = new Date('2026-10-02T01:00:00Z'); // 10:00 JST
assert.equal(d.friendlyEventText('US Employment Situation（2026-10-02 21:30（日本時間））・D', at), '米雇用統計 今夜21:30');
assert.equal(d.friendlyEventText('US Treasury 10-Year Auction（2026/10/07・時刻未公表・D-7）', at), '米国債入札 10/7');
assert.equal(d.friendlyEventText('FOMC（2026-10-03 03:00（日本時間））', at), 'FOMC 明日03:00');
assert.equal(d.friendlyEventText('日銀会合', at), '日銀会合');
console.log('Next-event wording PASS');

// 重大ニュースは数字３枚と並べ、元の見出し・理由・確認状態を保つ。
const vm = require('node:vm'), React = require('react'), {renderToStaticMarkup} = require('react-dom/server');
const wordingCode = ts.transpileModule(fs.readFileSync('src/lib/marketWording.ts','utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const wordingContext = {exports:{},require,Date}; vm.runInNewContext(wordingCode,wordingContext);
const stripContext = {exports:{},localStorage:{getItem:()=>null},require(name){
  if(name.endsWith('.css')) return {};
  if(name.includes('/todayDecision')) return d;
  if(name.includes('/marketWording')) return wordingContext.exports;
  if(name.includes('/hooks/')) return {useNikkeiLive:()=>({quote:null,futures:null})};
  return require(name);
}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/today/TodayDecisionStrip.tsx','utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,stripContext);
const brief={calculationSnapshots:{'5':{comparison:{actual:path,anchorDate:'2026-10-02'},
  marketFeatureSnapshot:{features:[{seriesId:'vix.level',date:'2026-10-02',value:15.3}]}}},chips:{nextEvent:'SQ 10/9'}};
const renderStrip=criticalNews=>renderToStaticMarkup(React.createElement(stripContext.exports.TodayDecisionStrip,{brief,criticalNews}));
const normalStrip=renderStrip([]);
assert.ok(normalStrip.includes('次の山場')&&normalStrip.includes('前後に株価が大きく上下することも'));
const urgent=renderStrip([{id:'test',title:'検査用：重要な政策発表',why:'価格への影響は未確認です。',meta:'10/5 01:30 · 確認待ち'}]);
assert.equal((urgent.split('today-strip__tiles')[1].split('</div>')[0].match(/<button /g)||[]).length,4);
assert.ok(urgent.includes('重大ニュース・市場変化 1件')&&urgent.includes('検査用：重要な政策発表'));
assert.ok(urgent.includes('価格への影響は未確認です。')&&urgent.includes('10/5 01:30 · 確認待ち'));
assert.ok(!urgent.includes('次の山場'),'重大ニュースがある時は４枚目に優先表示');
console.log('重大ニュースのトップカード PASS');
assert.equal(d.friendlyEventText('US Treasury 10-Year Auctio 10/7', at), '米国債入札 10/7');
assert.equal(d.friendlyEventText('US CPI (Consumer Price Index) 10/14 21:30', at), '米消費者物価 10/14 21:30');
assert.equal(s.rows.find(r=>r.id==='sq').lean,'neutral');
assert.ok(s.rows.find(r=>r.id==='sq').meaning.includes('上下へ大きく振れることがあります'));
assert.ok(s.rows.find(r=>r.id==='sq').soWhat.includes('寄付後も続くかを確認'));

const unavailableStrip=renderToStaticMarkup(React.createElement(stripContext.exports.TodayDecisionStrip,
 {brief:{chips:{nextEvent:''}}}));
assert.equal((unavailableStrip.split('today-strip__tiles')[1].split('</div>')[0].match(/<button /g)||[]).length,4,
 'missing inputs keep all four positions visible');
assert.ok(unavailableStrip.includes('確認中'));
assert.ok(!unavailableStrip.includes('過去の同じ段階で'),'missing data never gets a calculated alert');
console.log('欠測中も４カードを維持し数字を捏造しない PASS');

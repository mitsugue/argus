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
assert.equal(s.tone, 'head', 'two headwinds and a soft headwind outweigh one tailwind');

// Missing inputs never invent values.
const empty = d.decisionStrip(null, []);
assert.equal(empty.close, null); assert.equal(empty.alert, null); assert.equal(empty.band, null);
assert.deepEqual(empty.rows, []); assert.equal(empty.tone, 'wait');

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

// Today's "PER水準の地図": the stored morning map, upper rows above the close,
// past-frequency bands only, the fixed notes, and the pre-registered record
// kept apart from the counts made afterwards. No probability or trading words.
const assert = require('node:assert/strict'), path = require('node:path'), esbuild = require('esbuild'), Module = require('node:module');
const React = require('react'), { renderToStaticMarkup } = require('react-dom/server');
const entry = path.resolve('src/components/today/LevelMapCard.tsx');
const code = esbuild.buildSync({ entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs',
  jsx: 'automatic', external: ['react', 'react-dom', 'react/jsx-runtime'], loader: { '.css': 'empty' },
  define: { 'import.meta.env': JSON.stringify({ VITE_ARGUS_BACKEND_URL: '' }) }, logLevel: 'silent' }).outputFiles[0].text;
const mod = new Module(entry, module); mod.filename = entry; mod.paths = module.paths; mod._compile(code, entry);
const { LevelMapView } = mod.exports;
const row = (side, kinds, price, pct, atr, multiple, band, reach, med, q25, q75) => ({ side, kinds, price, distancePct: pct,
  distanceAtr: atr, multiple, tier: 'MAP', bandJa: band, pastFrequencyPct: 18, reachedWithin10SessionsPct: reach,
  sessionsMedian: med, sessions25: q25, sessions75: q75 });
const latest = { schemaVersion: 'jp-market-level-map-v1', morningOf: '2026-10-05', createdAt: '2026-10-04T12:00:00Z',
  previousClose: 68309.46, previousSession: '2026-10-02', atr14: 1235, eps: 3932.61, epsDate: '2026-10-02', per: 17.37,
  epsJumped: false, epsLabelJa: 'ARGUS推計（構成銘柄の時価総額加重の予想EPS。公式値ではありません）',
  epsCoverage: { members: 225, filledFromTrailing: 22, negativeForecast: 1 }, constituentsAsOf: '2026-08-31',
  rows: [row('UP', ['SAME_MULTIPLE'], 70330, 3.0, 1.6, 17.884, '2割前後', 56, 6, 2, 14),
         row('UP', ['PER_LINE'], 70787, 3.6, 2.0, 18, '2割前後', 38, 10, 4, 21),
         row('DOWN', ['PER_LINE'], 66854, -2.1, -1.2, 17, '1〜2割', 64, 3, 0, 9)],
  atrGuides: { UP: [69544, 70779, 72014], DOWN: [67074, 65839, 64604] },
  fixedNotesJa: ['水準を見ずに今の値±2ATRと言うのと同じ精度です。', '数字は過去の頻度であり、確率ではありません。'], actionAuthority: false };
const tally = { STOPPED: 0, BROKE: 0, UNDECIDED: 0, OPEN: 0 };
const score = (pre, mornings) => ({ firstMorning: pre ? '2026-10-05' : '2026-06-01', mornings, phases: 0, phaseOutcomes: tally,
  fakeLineOutcomes: tally, preRegisteredOnly: pre, turningPoints: { evaluated: 8, perLineHits: 6, atr2Hits: 1, chanceExpected: 2.86 } });
const state = { schemaVersion: 'jp-market-level-map-state-v1', status: 'AVAILABLE', latest, morningCount: 1,
  missedMornings: [], score: score(true, 1), retrospective: score(false, 84), actionAuthority: false };
const html = renderToStaticMarkup(React.createElement(LevelMapView, { state }));
assert.ok(html.includes('日経平均の価格の目盛り') && html.includes('2026-10-05 朝') && html.includes('寄付前に固定保存'));
assert.ok(html.includes('企業の利益に対して、日経平均が何倍の値段になっているか'));
assert.ok(html.includes('約17.37倍') && html.includes('70,787円まで上がると18倍、66,854円まで下がると17倍'));
assert.ok(html.includes('PER18倍線（EPS更新で動く）') && html.includes('直前の天井と同じ倍率 17.884倍'));
const table = html.split('<tbody>')[1];
assert.ok(table.indexOf('70,787') < table.indexOf('前日終値</td>') && table.indexOf('前日終値</td>') < table.indexOf('66,854'),
  'upper rows above the close, lower rows below');
assert.ok(html.includes('公式値ではありません') && html.includes('実績で補った社 22') && html.includes('2026-08-31 時点'));
assert.ok(html.includes('確率ではありません') && html.includes('±2ATR'));
assert.ok(html.includes('答え合わせ（2026-10-05からの事前記録）') && html.includes('判定には使いません'));
assert.ok(html.includes('件数が少ないうちは'));
for (const banned of ['BUY', 'SELL', '買い', '売り', '必ず', '止まる水準', '反発する']) assert.ok(!html.includes(banned), banned);
assert.equal(renderToStaticMarkup(React.createElement(LevelMapView, { state: null })), '');
assert.equal(renderToStaticMarkup(React.createElement(LevelMapView, { state: { ...state, latest: null } })), '');
const singleSide = renderToStaticMarkup(React.createElement(LevelMapView, { state: { ...state,
  latest: { ...latest, rows: latest.rows.filter(r => r.side === 'DOWN') } } }));
assert.ok(singleSide.includes('日経平均が66,854円まで下がると17倍になります。'));
console.log('Level map card PASS');

const history = {basis:'ARGUS_ESTIMATE_MARKET_CAP_WEIGHTED_FORWARD',firstDate:'2024-01-04',lastDate:'2026-10-02',
 count:600,missingSessions:12,sufficient:true,median:16.9,minimum:12.5,maximum:21.2,upperMultiple:18,atOrAboveUpper:210,retrospective:true,actionAuthority:false};
const renderHistory = value => renderToStaticMarkup(React.createElement(LevelMapView,{state:{...state,chart:{valuationHistory:value}}}));
assert.ok(renderHistory(history).includes('中央値16.9倍より上'));
assert.ok(renderHistory(history).includes('210 / 600営業日'));
assert.ok(renderHistory(history).includes('未集計12日'));
for (const invalid of [{...history,basis:'INDEX_WEIGHTED'},{...history,lastDate:'2026-10-06'},
 {...history,atOrAboveUpper:601},{...history,sufficient:false}]) {
 assert.ok(!renderHistory(invalid).includes('210 / 600営業日'));
}

const closing = {...latest,displayOnly:true,asOf:'2026-10-05',morningOf:'2026-10-06',
 previousSession:'2026-10-05',previousClose:70000,epsDate:'2026-10-02',valuationPending:true,per:17.8,
 rows:latest.rows.map(r=>({...r,distancePct:(r.price/70000-1)*100}))};
const closingHtml=renderToStaticMarkup(React.createElement(LevelMapView,{state:{...state,chart:{displayMap:closing}}}));
assert.ok(closingHtml.includes('最新終値')&&closingHtml.includes('70,000'));
assert.ok(closingHtml.includes('当日分の入力待ち'));
assert.ok(closingHtml.includes('2026-10-05 朝')&&closingHtml.includes('68,309'));
assert.deepEqual(state.latest,latest);
const freshHtml=renderToStaticMarkup(React.createElement(LevelMapView,{state:{...state,chart:{displayMap:{...closing,epsDate:'2026-10-05',valuationPending:false}}}}));
assert.ok(freshHtml.includes('当日分のPER・価格の目盛りを再計算済み'));
const invalidHtml=renderToStaticMarkup(React.createElement(LevelMapView,{state:{...state,chart:{displayMap:{...closing,epsDate:'2026-10-06'}}}}));
assert.ok(!invalidHtml.includes('最新終値'));

// The visible prices and expanded calculation table must share the close.
const enriched = {...closing, epsCoverage:{filledFromTrailing:3,negativeForecast:2}, constituentsAsOf:'2026-09-30',
 rows:closing.rows.map(r=>({...r,reachedWithin10SessionsPct: r.side==='UP'?82:45,sessionsMedian:2}))};
const scaleHtml=renderToStaticMarkup(React.createElement(LevelMapView,{state:{...state,chart:{displayMap:enriched}}}));
const calculations=scaleHtml.split('<details class="lm-all-levels">')[1].split('</details>')[0];
assert.ok(calculations.includes('70,000')&&!calculations.includes('68,309'),'expanded table uses latest close');
assert.ok(calculations.includes('+1.1%')&&!calculations.includes('+3.6%'),'expanded distances use latest close');
assert.ok(calculations.includes('82%')&&calculations.includes('実績で補った社 3'),'fresh stats and EPS coverage');
assert.ok(scaleHtml.includes('朝の固定記録を見る')&&scaleHtml.includes('68,309'),'fixed record remains separate');
const pendingHtml=renderToStaticMarkup(React.createElement(LevelMapView,{state:{...state,chart:{today:'2026-10-06',closePending:true}}}));
assert.ok(pendingHtml.includes('10/06の終値は取得待ち')&&pendingHtml.includes('10/02の終値を表示'),'missing close is visibly dated');

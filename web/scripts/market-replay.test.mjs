import assert from 'node:assert/strict';
import fs from 'node:fs';

const replay = fs.readFileSync(new URL('../src/components/marketReplay/MarketContextReplay.tsx', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../src/components/marketReplay/MarketContextReplay.css', import.meta.url), 'utf8');
const today = fs.readFileSync(new URL('../src/components/today/ArgusTodayPanel.tsx', import.meta.url), 'utf8');
const route = fs.readFileSync(new URL('../src/routes/MarketRegime.tsx', import.meta.url), 'utf8');
const chartHook = fs.readFileSync(new URL('../src/hooks/useChartIntelligence.ts', import.meta.url), 'utf8');

for (const tab of ['OVERVIEW', 'REPLAY', 'LEDGER']) assert.match(replay, new RegExp(`'${tab}'`));
for (const symbol of ['1321', '1306', 'SPY', 'QQQ']) assert.match(replay, new RegExp(symbol));
for (const horizon of ['1', '5', '20']) assert.match(replay, new RegExp(horizon));
for (const tool of ['horizontal', 'trend', 'zone', 'arrow', 'text', 'select']) {
  assert.match(replay, new RegExp(`'${tool}'`));
}
assert.match(replay, /argus\.marketReplay\.drawings\.v1:/);
assert.match(replay, /localStorage\.setItem\(key/);
assert.doesNotMatch(replay, /fetch\s*\(/, 'component delegates only to GET hooks');
assert.match(chartHook, /fetch\(url, \{ method: 'GET'/);
assert.doesNotMatch(chartHook, /method:\s*'POST'/);
assert.match(chartHook, /dataUrl === url \? data : null/,
  'instrument switches must fail closed instead of relabeling stale data');
assert.match(today, /argus\.replayContext/);
assert.match(today, /finalAction: view\.finalAction/);
assert.match(route, /MarketContextReplay/);
assert.doesNotMatch(route, /MarketEventsSections|ChartIntelligencePanel|MarketLedgerPanel/);
assert.match(css, /\.mr-chart\{width:100%;height:100%/);
assert.doesNotMatch(css, /min-width:\s*6[0-9]{2}px/);
assert.match(replay, /layoutReplayPriceLabels/);
assert.match(replay, /slice\(-20\)/);
assert.match(replay, /slice\(-10\)/);
assert.match(replay, /AI POST 0/);
console.log('market-replay.test: ok');

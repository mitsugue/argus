import assert from 'node:assert/strict';
import fs from 'node:fs';

const replay = fs.readFileSync(new URL('../src/components/marketReplay/MarketContextReplay.tsx', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../src/components/marketReplay/MarketContextReplay.css', import.meta.url), 'utf8');
const today = fs.readFileSync(new URL('../src/components/today/ArgusTodayPanel.tsx', import.meta.url), 'utf8');
const route = fs.readFileSync(new URL('../src/routes/MarketRegime.tsx', import.meta.url), 'utf8');
const chartHook = fs.readFileSync(new URL('../src/hooks/useChartIntelligence.ts', import.meta.url), 'utf8');
const vite = fs.readFileSync(new URL('../vite.config.ts', import.meta.url), 'utf8');
const theme = fs.readFileSync(new URL('../src/styles/theme.css', import.meta.url), 'utf8');
const types = fs.readFileSync(new URL('../src/types/chartIntelligence.ts', import.meta.url), 'utf8');

for (const tab of ['OVERVIEW', 'REPLAY', 'LEDGER']) assert.match(replay, new RegExp(`'${tab}'`));
for (const symbol of ['1321', '1306', 'SPY', 'QQQ']) assert.match(replay, new RegExp(symbol));
for (const horizon of ['1', '5', '20']) assert.match(replay, new RegExp(horizon));
for (const tool of ['horizontal', 'trend', 'zone', 'arrow', 'text', 'select']) {
  assert.match(replay, new RegExp(`'${tool}'`));
}
assert.match(replay, /argus\.marketReplay\.drawings\.v1:/);
assert.match(replay, /localStorage\.setItem\(key/);
assert.doesNotMatch(replay, /fetch\s*\(/, 'component delegates only to GET hooks');
assert.match(chartHook, /method: 'GET', cache: 'no-store'/);
assert.doesNotMatch(chartHook, /method:\s*'POST'/);
assert.match(chartHook, /dataUrl === url \? data : null/,
  'instrument switches must fail closed instead of relabeling stale data');
assert.match(chartHook, /instrument_mismatch/);
assert.match(chartHook, /instrumentMetadata\?\.symbol \?\? data\.symbol/);
assert.match(vite, /chart-intelligence[\s\S]+handler: 'NetworkFirst'/,
  'Market chart API must not use the broad stale-while-revalidate cache');
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
assert.match(replay, /label === 'MAE'/,
  'standard MAE remains explicitly labelled in the current UI');
assert.match(types, /derivedMetricMigration/);

for (const token of [
  '--chart-bg', '--chart-grid', '--chart-axis', '--chart-text-primary',
  '--chart-text-secondary', '--chart-bar-primary', '--chart-bar-positive',
  '--chart-bar-negative', '--chart-point', '--chart-chip-bg',
  '--chart-chip-text', '--chart-focus',
]) assert.match(theme, new RegExp(`${token}:\\s*[^;]+;`), `${token} must be centrally defined`);
assert.doesNotMatch(css, /var\(--accent\)|var\(--text\)/,
  'Market charts must not use undefined legacy color variables');
assert.match(css, /\.market-replay svg\{fill:none;stroke:none\}/,
  'SVG elements must inherit an explicit non-black default');
assert.match(css, /\.mr-dist rect\.is-positive[^}]+fill:var\(--chart-bar-positive\)/);
assert.match(css, /\.mr-dist rect\.is-negative[^}]+fill:var\(--chart-bar-negative\)/);
assert.match(css, /\.mr-calibration circle\{[^}]*fill:var\(--chart-point\)/);
assert.match(css, /\.mr-volume\.is-up\{fill:var\(--chart-volume-positive\)/);
assert.match(css, /\.mr-volume\.is-down\{fill:var\(--chart-volume-negative\)/);
assert.match(css, /\.mr-price-chip rect\{fill:var\(--chart-chip-bg\)/);
assert.match(css, /\.mr-price-chip text\{fill:var\(--chart-chip-text\)!important\}/);
assert.match(css, /\.mr-chart text\{fill:var\(--chart-axis\)/);
assert.match(css, /\.mr-dist-labels strong\{color:var\(--chart-text-primary\)/);
assert.match(css, /\.mr-selection-handle\{fill:var\(--chart-point-highlight\)!important/);
assert.match(replay, /className={`mr-volume \${tone}`}/);
assert.match(replay, /className="chip-label"/);
assert.match(replay, /className="chip-value"/);
assert.match(replay, /className="mr-dist-labels"/);
assert.match(replay, /<title>\{fmt\(row\.from\)}/, 'histograms expose bin tooltips');
assert.match(replay, /誤差 \{Math\.round/, 'calibration tooltip exposes error');
console.log('market-replay.test: ok');

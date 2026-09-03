// v13.5.50 — current intelligence is never painted from Cache Storage as current,
// hooks refresh on visibility/online, and a failed refresh never relabels
// retained data as current. Index charts are selectable on the market chart.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = path.join(__dirname, '..', 'src');
const vite = fs.readFileSync(path.join(__dirname, '..', 'vite.config.ts'), 'utf8');
const networkOnly = vite.match(/important-events\|dashboard-events\|news-intelligence\|market-news\|market-shock\|index-chart[^\n]*\n\s*handler: 'NetworkOnly'/);
assert.ok(networkOnly, 'current intelligence paths must be NetworkOnly in the service worker');
const swrIdx = vite.indexOf("handler: 'StaleWhileRevalidate'");
assert.ok(vite.indexOf('news-intelligence|market-news|market-shock') < swrIdx, 'NetworkOnly rule precedes the catch-all SWR rule');
for (const hook of ['useNewsIntelligence.ts', 'useMarketShock.ts']) {
  const text = fs.readFileSync(path.join(src, 'hooks', hook), 'utf8');
  assert.ok(!text.includes("status: memory ? 'data' : 'error'"), `${hook}: failed refresh must not relabel retained data as current`);
  assert.ok(text.includes("setState({ status: 'error', view: memory })"), `${hook}: failure marks status error`);
  assert.ok(text.includes("addEventListener('visibilitychange'"), `${hook}: refresh on visibility resume`);
  assert.ok(text.includes("addEventListener('online'"), `${hook}: refresh on online transition`);
  assert.ok(text.includes('setInterval'), `${hook}: periodic refresh`);
}
const panel = fs.readFileSync(path.join(src, 'components', 'chart', 'ChartIntelligencePanel.tsx'), 'utf8');
assert.ok(panel.includes('data-argus-contract="index-chart-selector-v1"'), 'index selector rendered on the market chart');
assert.ok(panel.includes('1321 ETF(検証済)'), 'verified ETF remains the default anchor');
const hookText = fs.readFileSync(path.join(src, 'hooks', 'useChartIntelligence.ts'), 'utf8');
assert.ok(hookText.includes('/api/argus/index-chart?index='), 'index chart hook calls the cached-only route');
assert.ok(hookText.includes("N225: '日経225', TOPIX: 'TOPIX', SPX: 'S&P500', NDX: 'ナスダック'"), 'index labels in Japanese');
console.log('live-intelligence-cache.test: NetworkOnly current surfaces, visibility/online refresh, stale never relabelled, index selector ok');

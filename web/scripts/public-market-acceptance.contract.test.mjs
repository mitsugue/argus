import assert from 'node:assert/strict';
import fs from 'node:fs';

const script = fs.readFileSync(
  new URL('./public-market-acceptance.mjs', import.meta.url), 'utf8');
const workflow = fs.readFileSync(
  new URL('../../.github/workflows/deploy-pages.yml', import.meta.url), 'utf8');
const manualWorkflow = fs.readFileSync(
  new URL('../../.github/workflows/market-public-acceptance.yml', import.meta.url), 'utf8');
const vite = fs.readFileSync(new URL('../vite.config.ts', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

for (const viewport of ['1440', '1280', '1024', '430', '390']) {
  assert.match(script, new RegExp(`width: ${viewport}`));
}
for (const value of ['OVERVIEW', 'REPLAY', 'LEDGER', '1321', '1306', 'SPY', 'QQQ',
  '1D', '5D', '20D']) {
  assert.match(script, new RegExp(`'${value}'`));
}
for (const artifact of ['screenshots', 'acceptance.json', 'console.json',
  'network.json', 'computed-styles.json', 'version.json']) {
  assert.match(script + workflow, new RegExp(artifact.replace('.', '\\.')));
}
for (const field of ['frontendVersion', 'frontendSha', 'backendVersion', 'backendSha',
  'datasetHash', 'blackFallbackCount', 'horizontalOverflow', 'aiPostCount']) {
  assert.match(script, new RegExp(field));
}
assert.match(script, /DATA_TIMEOUT_MS = 5_000/);
assert.match(script, /waitForData\(page, 30_000\)/,
  'pre-deploy seed must complete the real Market GET without weakening the formal gate');
assert.match(script, /BACKEND_READY_TIMEOUT_MS = 8 \* 60_000/);
assert.match(script, /MARKET_CACHE_READY_TIMEOUT_MS = 30 \* 60_000/);
assert.match(script, /waitForMarketCache\(page\.request\)/);
assert.match(script, /market cache did not become ready/);
assert.match(script, /body\.automaticAiCalls === 0/);
assert.match(script, /ARGUS_EXPECTED_BACKEND_VERSION/);
assert.match(script, /ARGUS_EXPECTED_BACKEND_SHA/);
assert.match(script, /marketProductStatus: evidence\.failures\.length \? 'NOT_FROZEN' : 'FROZEN'/);
assert.match(script, /page\.screenshot\(\{/);
assert.match(script, /fullPage: false/);
assert.match(script, /animations: 'disabled'/);
assert.match(script, /timeout: 10_000/);
assert.match(script, /tab === 'OVERVIEW' \|\| viewport\.width === 1280/);
assert.match(script, /screenshotCount/);
assert.match(script, /marketProductStatus: 'NOT_FROZEN'/);
assert.match(script, /process\.exit\(1\)/,
  'a failed acceptance must not leak Chromium until the workflow timeout');
assert.match(script, /\.mr-ledger-grid, \.mr-us-ledger/,
  'both JP and US ledger containers must count as visible chart data');
assert.doesNotMatch(script, /\.market-replay'\)\.screenshot\(/,
  'representative screenshots must remain viewport-bounded');
assert.doesNotMatch(script, /localStorage\./,
  'acceptance artifact must not read device-local owner data');
assert.match(workflow, /market-public-acceptance-/);
assert.match(workflow, /needs: \[build, seed-warm-profile\]/);
assert.match(workflow, /needs: \[scope, deploy, seed-warm-profile\]/);
assert.match(workflow, /if: needs\.scope\.outputs\.backend_deploy != 'true'/);
assert.match(workflow, /ARGUS_EXPECTED_BACKEND_VERSION: \$\{\{ steps\.release\.outputs\.backend_version \}\}/);
assert.doesNotMatch(workflow, /ARGUS_EXPECTED_BACKEND_SHA: \$\{\{ github\.sha \}\}/,
  'backend and frontend SHA must be independently observed');
assert.match(workflow, /ARGUS_EXPECTED_BACKEND_SHA: \$\{\{ needs\.scope\.outputs\.backend_sha \}\}/);
assert.match(workflow, /from scripts\.deploy_scope import classify/);
for (const input of ['pages_run_id', 'frontend_sha', 'backend_sha']) {
  assert.match(manualWorkflow, new RegExp(`${input}:`));
}
assert.match(manualWorkflow, /run-id: \$\{\{ inputs\.pages_run_id \}\}/);
assert.match(manualWorkflow, /github-token: \$\{\{ github\.token \}\}/);
assert.match(manualWorkflow, /ARGUS_EXPECTED_BACKEND_SHA: \$\{\{ inputs\.backend_sha \}\}/);
assert.match(workflow, /-name 'Local Storage'/);
assert.match(vite, /cleanupOutdatedCaches: true/);
assert.match(vite, /clientsClaim: true/);
assert.match(vite, /skipWaiting: true/);
assert.match(vite, /__ARGUS_BUILD_SHA__/);
assert.match(app, /'#market': 'regime'/);
console.log('public-market-acceptance.contract.test: ok');

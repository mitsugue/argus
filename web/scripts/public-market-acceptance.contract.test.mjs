import assert from 'node:assert/strict';
import fs from 'node:fs';

const script = fs.readFileSync(
  new URL('./public-market-acceptance.mjs', import.meta.url), 'utf8');
const workflow = fs.readFileSync(
  new URL('../../.github/workflows/deploy-pages.yml', import.meta.url), 'utf8');
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
assert.match(script, /BACKEND_READY_TIMEOUT_MS = 8 \* 60_000/);
assert.match(script, /ARGUS_EXPECTED_BACKEND_VERSION/);
assert.match(script, /ARGUS_EXPECTED_BACKEND_SHA/);
assert.match(script, /marketProductStatus: evidence\.failures\.length \? 'NOT_FROZEN' : 'FROZEN'/);
assert.match(script, /page\.screenshot\(\{/);
assert.match(script, /fullPage: false/);
assert.doesNotMatch(script, /\.market-replay'\)\.screenshot\(/,
  'representative screenshots must remain viewport-bounded');
assert.doesNotMatch(script, /localStorage\./,
  'acceptance artifact must not read device-local owner data');
assert.match(workflow, /market-public-acceptance-/);
assert.match(workflow, /needs: \[build, seed-warm-profile\]/);
assert.match(workflow, /ARGUS_EXPECTED_BACKEND_VERSION: \$\{\{ steps\.release\.outputs\.backend_version \}\}/);
assert.doesNotMatch(workflow, /ARGUS_EXPECTED_BACKEND_SHA: \$\{\{ github\.sha \}\}/,
  'backend and frontend SHA must be independently observed');
assert.match(workflow, /-name 'Local Storage'/);
assert.match(vite, /cleanupOutdatedCaches: true/);
assert.match(vite, /clientsClaim: true/);
assert.match(vite, /skipWaiting: true/);
assert.match(vite, /__ARGUS_BUILD_SHA__/);
assert.match(app, /'#market': 'regime'/);
console.log('public-market-acceptance.contract.test: ok');

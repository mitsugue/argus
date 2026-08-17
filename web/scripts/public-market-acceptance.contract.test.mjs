import assert from 'node:assert/strict';
import fs from 'node:fs';

const script = fs.readFileSync(
  new URL('./public-market-acceptance.mjs', import.meta.url), 'utf8');
const workflow = fs.readFileSync(
  new URL('../../.github/workflows/deploy-pages.yml', import.meta.url), 'utf8');
const manualWorkflow = fs.readFileSync(
  new URL('../../.github/workflows/market-public-acceptance.yml', import.meta.url), 'utf8');
const seedAction = fs.readFileSync(
  new URL('../../.github/actions/warm-profile-seed/action.yml', import.meta.url), 'utf8');
const consumerAction = fs.readFileSync(
  new URL('../../.github/actions/warm-profile-consumer/action.yml', import.meta.url), 'utf8');
const seedRunner = fs.readFileSync(
  new URL('./run-warm-profile-seed.sh', import.meta.url), 'utf8');
const vite = fs.readFileSync(new URL('../vite.config.ts', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const navigation = fs.readFileSync(
  new URL('../src/navigation.ts', import.meta.url), 'utf8');
const mobileAcceptance = fs.readFileSync(
  new URL('./mobile-today-acceptance.mjs', import.meta.url), 'utf8');
const today = fs.readFileSync(
  new URL('../src/components/today/ArgusTodayPanel.tsx', import.meta.url), 'utf8');

for (const viewport of ['1440', '1280', '1024', '430', '390']) {
  assert.match(script, new RegExp(`width: ${viewport}`));
}
for (const value of ['1321', '1306', 'SPY', 'QQQ', '1D', '5D', '20D']) {
  assert.match(script, new RegExp(`'${value}'`));
}
for (const artifact of ['screenshots', 'acceptance.json', 'console.json',
  'network.json', 'diagnostics.json', 'computed-styles.json', 'version.json']) {
  assert.match(script + workflow, new RegExp(artifact.replace('.', '\\.')));
}
for (const field of ['frontendVersion', 'frontendSha', 'backendVersion', 'backendSha',
  'datasetHash', 'responseSnapshotId', 'blackFallbackCount',
  'horizontalOverflow', 'aiPostCount']) {
  assert.match(script, new RegExp(field));
}

assert.match(script, /#today/);
assert.doesNotMatch(script, /#market|Market Context|\.market-replay|\.mr-/);
assert.match(script, /TODAY_URL/);
for (const source of [script, mobileAcceptance]) {
  assert.match(source, /canonical-market-snapshot-v1/);
  assert.match(source, /data-canonical-verification=\"verified\"/);
  assert.match(source, /data-canonical-snapshot-id/);
  assert.doesNotMatch(source, /\.at-chart-status\[data-snapshot-id\]/,
    'acceptance must not wait on the collapsed diagnostic panel');
}
assert.match(today, /data-argus-contract="canonical-market-snapshot-v1"/);
assert.match(today, /data-canonical-snapshot-id=\{chartLoad\.snapshotId \?\? undefined\}/);
assert.match(today, /data-canonical-snapshot-state=\{chartLoad\.snapshotState\}/);
assert.match(today, /data-canonical-verification=\{chartLoad\.snapshotId \? 'verified' : 'unverified'\}/);
assert.match(today, /data-canonical-instrument=\{projection\?\.symbol \?\? selectedSymbol\}/);
assert.match(today, /data-canonical-horizon=\{`\$\{projection\?\.horizonDays \?\? horizon\}D`\}/);
assert.match(script, /\.at-projection/);
assert.match(script, /\.at-index-strip button/);
assert.match(script, /getByRole\('group', \{ name: '予測期間' \}\)/);
assert.match(script, /DATA_TIMEOUT_MS = 5_000/);
assert.match(script, /BACKEND_READY_TIMEOUT_MS = 8 \* 60_000/);
assert.match(script, /MARKET_CACHE_READY_TIMEOUT_MS = 30 \* 60_000/);
assert.match(script, /waitForMarketCache\(page\.request\)/);
assert.match(script, /market cache did not become ready/);
assert.match(script, /view\.automaticAiCalls \?\? 0/);
assert.match(script, /const view = body\.payload \|\| body/);
assert.match(script, /marketReplay\?\.contexts/);
assert.match(script, /snapshot: 'verified'/);
assert.match(script, /scope: 'market'/);
assert.match(script, /horizon: HORIZONS\[1\]/,
  'warm-profile acceptance must use the canonical 5D horizon');
assert.doesNotMatch(script, /horizon:\s*['"]5['"]/,
  'canonical verified-snapshot acceptance must never request legacy horizon=5');
assert.match(script, /launchPersistentContext\(PROFILE_DIR/,
  'the producer and consumer must use the transferred persistent profile');
assert.match(script, /stabilizeWarmProfileRuntime/);
assert.match(script, /runtime-reload/);
assert.match(script, /serviceWorkerReady/);
assert.match(script, /writeWarmProfileManifest/);
assert.match(script, /validateWarmProfile/);
assert.match(script, /todayProductStatus/);
assert.match(script, /page\.screenshot\(\{/);
assert.match(script, /fullPage: false/);
assert.match(script, /animations: 'disabled'/);
assert.match(script, /timeout: 10_000/);
assert.match(script, /process\.exitCode = 1/);
assert.doesNotMatch(script, /localStorage\./,
  'acceptance must not read protected owner data');

assert.match(workflow, /uses: \.\/\.github\/actions\/warm-profile-seed/);
assert.match(workflow, /uses: \.\/\.github\/actions\/warm-profile-consumer/);
assert.match(manualWorkflow, /uses: \.\/\.github\/actions\/warm-profile-seed/);
assert.match(manualWorkflow, /uses: \.\/\.github\/actions\/warm-profile-consumer/);
assert.match(seedAction, /bash scripts\/run-warm-profile-seed\.sh/);
assert.match(seedRunner, /node scripts\/public-market-acceptance\.mjs/);
assert.match(consumerAction, /node scripts\/public-market-acceptance\.mjs/);
assert.match(workflow, /node scripts\/mobile-today-acceptance\.mjs/);
assert.match(workflow, /market-public-acceptance-/);
assert.match(workflow, /verified_snapshot_release_gate\.py/);
assert.match(workflow,
  /--expected-backend-sha '\$\{\{ needs\.scope\.outputs\.backend_sha \}\}'/);
assert.doesNotMatch(workflow,
  /ARGUS_EXPECTED_BACKEND_SHA: \$\{\{ github\.sha \}\}/);
for (const input of ['pages_run_id', 'frontend_sha', 'backend_sha']) {
  assert.match(manualWorkflow, new RegExp(`${input}:`));
}
assert.match(manualWorkflow, /expected-backend-sha: \$\{\{ inputs\.backend_sha \}\}/);
assert.match(seedRunner, /warm-profile-contract\.mjs sanitize-validate/);
assert.match(consumerAction, /warm-profile-contract\.mjs validate/);
assert.match(workflow, /candidate-sha: \$\{\{ github\.sha \}\}/);
assert.match(manualWorkflow, /warm-profile-seed:/);
assert.match(manualWorkflow, /warm-profile-handoff:/);
assert.match(manualWorkflow, /warm-profile-seed-2:/);
assert.match(manualWorkflow, /warm-profile-handoff-2:/);
assert.match(manualWorkflow, /mode: profile/);
assert.match(workflow, /needs: \[build, backend-readiness\]/);
assert.match(workflow, /candidate-identity:/);
assert.match(workflow, /verify_public_candidate_release\.py/);
assert.match(workflow, /needs: \[scope, deploy, backend-readiness\]/);
assert.match(workflow, /needs: \[scope, candidate-identity\]/);
assert.match(workflow,
  /needs: \[scope, deploy, candidate-identity, seed-warm-profile, backend-readiness\]/);
assert.match(workflow, /enforce-public-candidate-identity: 'true'/);
assert.match(workflow,
  /expected-backend-sha: \$\{\{ needs\.candidate-identity\.outputs\.backend_sha \}\}/);
assert.doesNotMatch(workflow,
  /needs: \[build, seed-warm-profile, backend-readiness\]/);
assert.match(script, /candidate_frontend_not_live/);
assert.match(script, /candidate_backend_not_live/);
assert.match(script, /ARGUS_REQUIRE_LIVE_CANDIDATE/);
assert.match(seedAction, /continue-on-error: true/);
assert.match(seedAction, /Publish bounded seed evidence/);

assert.match(vite, /cleanupOutdatedCaches: true/);
assert.match(vite, /clientsClaim: true/);
assert.match(vite, /skipWaiting: true/);
assert.match(vite, /chart-intelligence[\s\S]+handler: 'NetworkOnly'/);
assert.match(app, /parseLocationHash/);
assert.match(app, /history\.pushState/);
assert.match(navigation, /export const HASH_ROUTES/);
assert.match(navigation, /export function assetDetailHash/);
assert.doesNotMatch(navigation, /#market|'regime'/);

assert.match(mobileAcceptance, /TODAY_URL/);
assert.match(mobileAcceptance, /rate-limit-cache-backoff-contract/);
assert.match(mobileAcceptance, /offline-snapshot-continuity/);
assert.match(mobileAcceptance, /responseTasks:\s*new Set\(\)/);
assert.match(mobileAcceptance, /Retry-After/);
assert.match(mobileAcceptance, /COMBINATION_PACE_MS = 1_000/);

console.log('public-market-acceptance.contract.test: ok (canonical Today evidence)');

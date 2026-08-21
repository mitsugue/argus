import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  dynamicProvisioningAudit,
  evaluateRuntimeAdmission,
  loadRuntimeSpec,
  sha256,
} from './acceptance-runtime.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const spec = loadRuntimeSpec();
const baseline = {
  runtimeAvailable: true,
  containerRef: `${spec.container.image}@${spec.container.digest}`,
  platform: 'linux', architecture: 'x64', nodeMajor: 22,
  playwrightVersion: '1.55.0', browserVersion: '140.0.7339.16',
  browserExecutable: '/ms-playwright/chromium-1187/chrome-linux/chrome',
  browserExecutableSha256: 'a'.repeat(64), browserLaunched: true,
  contextCreated: true, pageCreated: true, profileWritable: true,
  seedImportSucceeded: true, seedImplementationDigest: 'b'.repeat(64),
  noDynamicProvisioning: true,
};
assert.deepEqual(evaluateRuntimeAdmission({ spec, observed: baseline }), {
  pass: true, reasons: [],
});
for (const [field, value, reason] of [
  ['runtimeAvailable', false, 'runtime_unavailable'],
  ['browserLaunched', false, 'browser_launch_failed'],
  ['profileWritable', false, 'profile_write_failed'],
  ['seedImportSucceeded', false, 'seed_import_failed'],
  ['containerRef', 'wrong@sha256:' + '0'.repeat(64), 'container_identity_mismatch'],
  ['noDynamicProvisioning', false, 'dynamic_provisioning_detected'],
]) {
  const result = evaluateRuntimeAdmission({ spec, observed: { ...baseline, [field]: value } });
  assert.equal(result.pass, false);
  assert.ok(result.reasons.includes(reason), `${field}:${result.reasons}`);
}
assert.equal(dynamicProvisioningAudit(spec).pass, true);

const deploy = fs.readFileSync(path.join(root, '.github/workflows/deploy-pages.yml'), 'utf8');
const proof = fs.readFileSync(path.join(root, '.github/workflows/market-public-acceptance.yml'), 'utf8');
const releaseGate = fs.readFileSync(path.join(root, '.github/workflows/release-gate.yml'), 'utf8');
const rehearsal = fs.readFileSync(path.join(root, '.github/actions/v13-5-pre-mutation-rehearsal/action.yml'), 'utf8');
const rollback = fs.readFileSync(path.join(root, '.github/workflows/restore-safe-pages.yml'), 'utf8');
const seed = fs.readFileSync(path.join(root, '.github/actions/warm-profile-seed/action.yml'), 'utf8');
const consumer = fs.readFileSync(path.join(root, '.github/actions/warm-profile-consumer/action.yml'), 'utf8');
const forbidden = /(?:npx\s+playwright\s+install|playwright\s+install\s+--with-deps|apt(?:-get)?\s+install|browser\s+download)/i;
for (const [name, source] of Object.entries({ deploy, proof, releaseGate, rehearsal, seed, consumer, rollback })) {
  assert.doesNotMatch(source, forbidden, `${name} must be zero-install`);
}
assert.match(deploy, /acceptance-runtime-admission:[\s\S]*container:[\s\S]*b27e719e/);
assert.match(deploy, /build:[\s\S]*needs: \[scope, acceptance-runtime-admission\]/);
assert.match(deploy, /backend-infrastructure-readiness:[\s\S]*needs: \[scope, build, acceptance-runtime-admission\]/);
assert.match(deploy, /deploy:[\s\S]*needs: \[build, backend-infrastructure-readiness, acceptance-runtime-admission\]/);
assert.ok(deploy.indexOf('acceptance-runtime-admission:') < deploy.indexOf('  deploy:'));
assert.match(proof, /full_release_simulation_1:[\s\S]*container:[\s\S]*b27e719e/);
assert.match(proof, /full_release_simulation_2:[\s\S]*container:[\s\S]*b27e719e/);
assert.match(proof, /generate-admission[\s\S]*v13_5_source_provenance[\s\S]*verify-admission/);
assert.match(proof, /v13-5-premerge-admission-\$\{\{ github\.event\.pull_request\.head\.sha \}\}-\$\{\{ github\.run_id \}\}-\$\{\{ github\.run_attempt \}\}/);
assert.match(releaseGate, /premerge_admission:[\s\S]*container:[\s\S]*b27e719e/);
assert.match(releaseGate, /premerge_admission:[\s\S]*collect-authority[\s\S]*fetch-admission[\s\S]*acceptance-runtime-preflight[\s\S]*v13-5-pre-mutation-rehearsal/);
assert.match(rehearsal, /v13_5_source_provenance[\s\S]*verify-admission[\s\S]*npm ci[\s\S]*npm run build[\s\S]*v13_5_pre_mutation_rehearsal/);
assert.match(releaseGate, /gate:[\s\S]*needs: \[release_checks, premerge_admission\]/);
assert.match(deploy, /acceptance-runtime-admission:[\s\S]*collect-checks[\s\S]*collect-authority[\s\S]*fetch-admission[\s\S]*acceptance-runtime-preflight[\s\S]*v13-5-pre-mutation-rehearsal/);
assert.match(deploy, /--producer-authority artifacts\/v13-release-proof\/producer-authority\.json/);
assert.match(deploy, /retrieval-receipt\.json/);
const safeDirectoryAdmission = /git config --global --add safe\.directory "\$GITHUB_WORKSPACE"/g;
assert.equal(proof.match(safeDirectoryAdmission)?.length, 4,
  'every containerized preproduction tree pin must admit checkout ownership');
assert.ok((deploy.match(safeDirectoryAdmission)?.length ?? 0) >= 1,
  'production runtime admission must admit checkout ownership before binding the merge tree');
assert.match(rollback, /Build exact safe Pages artifact/);
assert.doesNotMatch(rollback, /warm-profile|acceptance-runtime|playwright|chromium/i);
assert.equal(sha256('argus').length, 64);
console.log('acceptance runtime contract tests passed');

import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  sanitizeWarmProfile,
  validateWarmProfile,
  WARM_PROFILE_MANIFEST,
  writeWarmProfileManifest,
} from './warm-profile-contract.mjs';

const CANDIDATE_SHA = 'a'.repeat(40);

async function fixture(root) {
  await fs.mkdir(path.join(root, 'Default', 'IndexedDB',
    'https_mitsugue.github.io_0.indexeddb.leveldb'), {
    recursive: true,
  });
  await fs.mkdir(path.join(root, 'Default', 'Service Worker', 'Database'), {
    recursive: true,
  });
  await fs.writeFile(path.join(root, 'Default', 'IndexedDB',
    'https_mitsugue.github.io_0.indexeddb.leveldb', 'CURRENT'),
  'MANIFEST-000001\n');
  await fs.writeFile(path.join(root, 'Default', 'IndexedDB',
    'https_mitsugue.github.io_0.indexeddb.leveldb', '000003.log'),
  'verified-snapshot-record');
  await fs.writeFile(path.join(root, 'Default', 'Service Worker', 'Database',
    'CURRENT'), 'MANIFEST-000001\n');
  await fs.writeFile(path.join(root, 'Default', 'Service Worker', 'Database',
    '000003.log'), 'service-worker-registration');
  await fs.mkdir(path.join(root, 'Default', 'Local Storage'), { recursive: true });
  await fs.writeFile(path.join(root, 'Default', 'Local Storage', 'private'), 'remove');
  await fs.writeFile(path.join(root, 'Default', 'Cookies'), 'remove');
  await fs.writeFile(path.join(root, 'SingletonLock'), 'remove');
  return writeWarmProfileManifest({
    profileDir: root,
    candidateSha: CANDIDATE_SHA,
    runtimeProof: {
      databaseNames: ['argus-verified-snapshots'],
      serviceWorkerReady: true,
      verifiedSnapshotRecordCount: 1,
    },
    source: {
      backendSha: 'b'.repeat(40),
      backendVersion: '13.4.13',
      frontendSha: 'c'.repeat(40),
      frontendVersion: '13.3.6',
      publicUrl: 'https://mitsugue.github.io/argus/#today',
      seededSnapshotId: 'snapshot-fixture',
    },
  });
}

const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'argus-warm-profile-'));
try {
  const validDir = path.join(temporary, 'valid');
  const produced = await fixture(validDir);
  assert.match(produced.artifactId, /^warm-profile-[0-9a-f]{64}$/);
  assert.equal((await validateWarmProfile({
    profileDir: validDir, expectedCandidateSha: CANDIDATE_SHA,
  })).artifactId, produced.artifactId);

  await sanitizeWarmProfile(validDir);
  assert.equal(await fs.stat(path.join(validDir, 'Default', 'Local Storage'))
    .then(() => true, () => false), false);
  assert.equal(await fs.stat(path.join(validDir, 'Default', 'Cookies'))
    .then(() => true, () => false), false);
  assert.equal(await fs.stat(path.join(validDir, 'SingletonLock'))
    .then(() => true, () => false), false);
  assert.equal((await validateWarmProfile({
    profileDir: validDir, expectedCandidateSha: CANDIDATE_SHA,
  })).artifactId, produced.artifactId);

  await assert.rejects(validateWarmProfile({
    profileDir: path.join(temporary, 'missing'), expectedCandidateSha: CANDIDATE_SHA,
  }), /warm_profile_manifest_missing/);

  const emptyDir = path.join(temporary, 'empty');
  await fs.mkdir(emptyDir);
  await fs.writeFile(path.join(emptyDir, WARM_PROFILE_MANIFEST), '{}');
  await assert.rejects(validateWarmProfile({
    profileDir: emptyDir, expectedCandidateSha: CANDIDATE_SHA,
  }), /warm_profile_manifest_identity_mismatch/);

  const malformedDir = path.join(temporary, 'malformed');
  await fs.mkdir(malformedDir);
  await fs.writeFile(path.join(malformedDir, WARM_PROFILE_MANIFEST), '{');
  await assert.rejects(validateWarmProfile({
    profileDir: malformedDir, expectedCandidateSha: CANDIDATE_SHA,
  }), /warm_profile_manifest_malformed/);

  await assert.rejects(validateWarmProfile({
    profileDir: validDir, expectedCandidateSha: 'd'.repeat(40),
  }), /warm_profile_manifest_identity_mismatch/);

  await fs.writeFile(path.join(validDir, 'Default', 'IndexedDB',
    'https_mitsugue.github.io_0.indexeddb.leveldb', 'CURRENT'), 'tampered');
  await assert.rejects(validateWarmProfile({
    profileDir: validDir, expectedCandidateSha: CANDIDATE_SHA,
  }), /warm_profile_content_mismatch/);
} finally {
  await fs.rm(temporary, { recursive: true, force: true });
}

const script = await fs.readFile(new URL('./public-market-acceptance.mjs',
  import.meta.url), 'utf8');
const deploy = await fs.readFile(new URL('../../.github/workflows/deploy-pages.yml',
  import.meta.url), 'utf8');
const acceptance = await fs.readFile(new URL(
  '../../.github/workflows/market-public-acceptance.yml', import.meta.url), 'utf8');
const seedAction = await fs.readFile(new URL(
  '../../.github/actions/warm-profile-seed/action.yml', import.meta.url), 'utf8');
const consumerAction = await fs.readFile(new URL(
  '../../.github/actions/warm-profile-consumer/action.yml', import.meta.url), 'utf8');
const seedRunner = await fs.readFile(new URL('./run-warm-profile-seed.sh',
  import.meta.url), 'utf8');

assert.match(script, /launchPersistentContext\(PROFILE_DIR/);
assert.match(script, /MODE === 'seed'/);
assert.match(script, /MODE === 'profile'/);
assert.match(script, /horizon: HORIZONS\[1\]/);
assert.doesNotMatch(script, /horizon:\s*['"]5['"]/);
assert.match(deploy, /candidate-sha: \$\{\{ github\.sha \}\}/);
assert.match(deploy, /\.\/\.github\/actions\/warm-profile-seed/);
assert.match(deploy, /\.\/\.github\/actions\/warm-profile-consumer/);
assert.match(seedRunner, /warm-profile-contract\.mjs sanitize-validate/);
assert.match(consumerAction, /warm-profile-contract\.mjs validate/);
assert.match(seedAction, /if-no-files-found: error/);
assert.match(acceptance, /warm-profile-seed:/);
assert.match(acceptance, /warm-profile-handoff:/);
assert.match(acceptance, /needs: warm-profile-seed/);
assert.match(acceptance, /warm-profile-seed-2:/);
assert.match(acceptance, /warm-profile-handoff-2:/);
assert.match(acceptance, /mode: profile/);
assert.match(consumerAction, /actions\/download-artifact@v5/);

console.log('warm-profile-contract.test: ok (real profile, closed cross-runner identity)');

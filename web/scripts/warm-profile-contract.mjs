import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const WARM_PROFILE_SCHEMA = 'argus-market-warm-profile-v1';
export const WARM_PROFILE_MANIFEST = 'argus-warm-profile.json';

const SHA_RE = /^[0-9a-f]{40}$/;
const REQUIRED_FILES = [
  'Default/IndexedDB/https_mitsugue.github.io_0.indexeddb.leveldb/CURRENT',
  'Default/Service Worker/Database/CURRENT',
];
const INDEXED_DB_DIR = 'Default/IndexedDB';
const SERVICE_WORKER_DIR = 'Default/Service Worker';
const PRIVATE_DIRECTORIES = new Set(['Local Storage', 'Session Storage']);
const PRIVATE_FILES = new Set([
  'Cookies', 'Cookies-journal', 'History', 'History-journal',
  'Login Data', 'Login Data-journal', 'Web Data', 'Web Data-journal',
]);

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort()
      .map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function canonicalBytes(value) {
  return Buffer.from(JSON.stringify(canonical(value)));
}

function digest(value) {
  return crypto.createHash('sha256').update(canonicalBytes(value)).digest('hex');
}

function exactKeys(value, expected) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expected].sort());
}

function requireSha(value, label) {
  if (typeof value !== 'string' || !SHA_RE.test(value)) {
    throw new Error(`invalid_${label}`);
  }
  return value;
}

async function fileProof(profileDir, relativePath) {
  const absolute = path.join(profileDir, relativePath);
  const stat = await fs.stat(absolute).catch(() => null);
  if (!stat?.isFile() || stat.size <= 0) {
    throw new Error(`warm_profile_required_file_invalid:${relativePath}`);
  }
  const bytes = await fs.readFile(absolute);
  return {
    path: relativePath,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    sizeBytes: bytes.length,
  };
}

async function directoryProof(profileDir, relativePath) {
  const absolute = path.join(profileDir, relativePath);
  const stat = await fs.stat(absolute).catch(() => null);
  if (!stat?.isDirectory()) {
    throw new Error(`warm_profile_required_directory_invalid:${relativePath}`);
  }
  const pending = [absolute];
  let fileCount = 0;
  let totalBytes = 0;
  while (pending.length) {
    const current = pending.pop();
    const entries = await fs.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const target = path.join(current, entry.name);
      if (entry.isDirectory()) pending.push(target);
      if (entry.isFile()) {
        const child = await fs.stat(target);
        fileCount += 1;
        totalBytes += child.size;
      }
    }
  }
  if (fileCount < 1 || totalBytes < 1) {
    throw new Error(`warm_profile_required_directory_empty:${relativePath}`);
  }
  return { path: relativePath, fileCount, totalBytes };
}

async function profileProof(profileDir) {
  const root = await fs.stat(profileDir).catch(() => null);
  if (!root?.isDirectory()) throw new Error('warm_profile_directory_missing');
  const requiredFiles = [];
  for (const relativePath of REQUIRED_FILES) {
    requiredFiles.push(await fileProof(profileDir, relativePath));
  }
  return {
    requiredFiles,
    indexedDb: await directoryProof(profileDir, INDEXED_DB_DIR),
    serviceWorker: await directoryProof(profileDir, SERVICE_WORKER_DIR),
  };
}

function validateSource(source) {
  if (!exactKeys(source, [
    'backendSha', 'backendVersion', 'frontendSha', 'frontendVersion',
    'publicUrl', 'seededSnapshotId',
  ])) throw new Error('warm_profile_source_invalid');
  requireSha(source.frontendSha, 'source_frontend_sha');
  requireSha(source.backendSha, 'source_backend_sha');
  for (const key of ['backendVersion', 'frontendVersion', 'publicUrl',
    'seededSnapshotId']) {
    if (typeof source[key] !== 'string' || !source[key]) {
      throw new Error(`warm_profile_source_${key}_invalid`);
    }
  }
}

function validateRuntimeProof(runtimeProof) {
  if (!exactKeys(runtimeProof, [
    'databaseNames', 'serviceWorkerReady', 'verifiedSnapshotRecordCount',
  ])) throw new Error('warm_profile_runtime_proof_invalid');
  if (runtimeProof.serviceWorkerReady !== true
      || !Array.isArray(runtimeProof.databaseNames)
      || !runtimeProof.databaseNames.includes('argus-verified-snapshots')
      || !Number.isInteger(runtimeProof.verifiedSnapshotRecordCount)
      || runtimeProof.verifiedSnapshotRecordCount < 1) {
    throw new Error('warm_profile_runtime_proof_unusable');
  }
}

export async function writeWarmProfileManifest({
  profileDir, candidateSha, source, runtimeProof,
}) {
  requireSha(candidateSha, 'candidate_sha');
  validateSource(source);
  validateRuntimeProof(runtimeProof);
  const body = {
    candidateSha,
    profile: await profileProof(profileDir),
    runtimeProof,
    schemaVersion: WARM_PROFILE_SCHEMA,
    source,
  };
  const manifest = {
    ...body,
    artifactId: `warm-profile-${digest(body)}`,
  };
  await fs.writeFile(path.join(profileDir, WARM_PROFILE_MANIFEST),
    `${JSON.stringify(canonical(manifest), null, 2)}\n`);
  return manifest;
}

export async function validateWarmProfile({ profileDir, expectedCandidateSha }) {
  requireSha(expectedCandidateSha, 'expected_candidate_sha');
  const raw = await fs.readFile(path.join(profileDir, WARM_PROFILE_MANIFEST), 'utf8')
    .catch(() => { throw new Error('warm_profile_manifest_missing'); });
  let manifest;
  try { manifest = JSON.parse(raw); } catch { throw new Error('warm_profile_manifest_malformed'); }
  if (!exactKeys(manifest, [
    'artifactId', 'candidateSha', 'profile', 'runtimeProof', 'schemaVersion', 'source',
  ]) || manifest.schemaVersion !== WARM_PROFILE_SCHEMA
      || manifest.candidateSha !== expectedCandidateSha) {
    throw new Error('warm_profile_manifest_identity_mismatch');
  }
  validateSource(manifest.source);
  validateRuntimeProof(manifest.runtimeProof);
  const expectedProfile = await profileProof(profileDir);
  if (JSON.stringify(canonical(manifest.profile))
      !== JSON.stringify(canonical(expectedProfile))) {
    throw new Error('warm_profile_content_mismatch');
  }
  const { artifactId, ...body } = manifest;
  if (artifactId !== `warm-profile-${digest(body)}`) {
    throw new Error('warm_profile_artifact_id_mismatch');
  }
  return manifest;
}

export async function sanitizeWarmProfile(profileDir) {
  const root = await fs.stat(profileDir).catch(() => null);
  if (!root?.isDirectory()) throw new Error('warm_profile_directory_missing');
  async function visit(directory) {
    const entries = await fs.readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      const target = path.join(directory, entry.name);
      if (entry.name.startsWith('Singleton')) {
        await fs.rm(target, { force: true, recursive: entry.isDirectory() });
      } else if (entry.isDirectory() && PRIVATE_DIRECTORIES.has(entry.name)) {
        await fs.rm(target, { force: true, recursive: true });
      } else if (entry.isDirectory()) {
        await visit(target);
      } else if (PRIVATE_FILES.has(entry.name)) {
        await fs.rm(target, { force: true });
      }
    }
  }
  await visit(profileDir);
}

async function cli() {
  const [command, profileDir, expectedCandidateSha] = process.argv.slice(2);
  if (!['sanitize-validate', 'validate'].includes(command)
      || !profileDir || !expectedCandidateSha) {
    throw new Error('usage: warm-profile-contract.mjs (sanitize-validate|validate) PROFILE_DIR CANDIDATE_SHA');
  }
  if (command === 'sanitize-validate') {
    await sanitizeWarmProfile(path.resolve(profileDir));
  }
  const manifest = await validateWarmProfile({
    profileDir: path.resolve(profileDir), expectedCandidateSha,
  });
  process.stdout.write(`${JSON.stringify({
    artifactId: manifest.artifactId,
    candidateSha: manifest.candidateSha,
    schemaVersion: manifest.schemaVersion,
    status: 'valid',
  })}\n`);
}

if (process.argv[1]
    && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await cli();
}

import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from 'playwright';

export const RUNTIME_SPEC_SCHEMA = 'argus-acceptance-runtime-spec-v1';
export const RUNTIME_PROOF_SCHEMA = 'argus-zero-install-runtime-proof-v1';
export const RUNTIME_IDENTITY_SCHEMA = 'argus-acceptance-runtime-identity-v1';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '../..');
const defaultSpecPath = path.join(repoRoot, 'release/v13-acceptance-runtime.json');
const SHA256 = /^[0-9a-f]{64}$/;
const GIT_SHA = /^[0-9a-f]{40}$/;

const sorted = (value) => {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .map(([key, child]) => [key, sorted(child)]));
  }
  return value;
};
export const canonical = (value) => JSON.stringify(sorted(value));
export const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');

const exactKeys = (value, keys, label) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || canonical(Object.keys(value).sort()) !== canonical([...keys].sort())) {
    throw new Error(`invalid_${label}_shape`);
  }
};
const exactPath = (relative) => {
  if (typeof relative !== 'string' || !relative || path.isAbsolute(relative)) {
    throw new Error('invalid_runtime_relative_path');
  }
  const resolved = path.resolve(repoRoot, relative);
  if (!resolved.startsWith(`${repoRoot}${path.sep}`)) throw new Error('runtime_path_escape');
  return resolved;
};

export function validateRuntimeSpec(value) {
  exactKeys(value, [
    'schemaVersion', 'runtimeId', 'runner', 'container', 'node', 'playwright',
    'browser', 'seedImplementationPaths', 'criticalReleasePaths',
    'forbiddenDynamicProvisioningPatterns',
  ], 'runtime_spec');
  if (value.schemaVersion !== RUNTIME_SPEC_SCHEMA
      || value.runtimeId !== 'playwright-1.55.0-noble-zero-install-v1') {
    throw new Error('invalid_runtime_spec_identity');
  }
  exactKeys(value.runner, ['os', 'architecture', 'family'], 'runtime_runner');
  exactKeys(value.container, ['image', 'digest', 'amd64ManifestDigest'], 'runtime_container');
  exactKeys(value.node, ['major'], 'runtime_node');
  exactKeys(value.playwright, ['version', 'browsersPath'], 'runtime_playwright');
  exactKeys(value.browser, [
    'name', 'revision', 'version', 'executablePathPrefix',
  ], 'runtime_browser');
  if (value.runner.os !== 'linux' || value.runner.architecture !== 'x64'
      || value.runner.family !== 'ubuntu-noble'
      || value.container.image !== 'mcr.microsoft.com/playwright:v1.55.0-noble'
      || value.container.digest !== 'sha256:b27e719ecbfef153e13fd24e8341736733bf2658b229677eb21ff57ff5d7fb29'
      || value.container.amd64ManifestDigest !== 'sha256:ffc33305f7b4b04057ae4a0caa70aad4fde87454fb403a1a22e7f931707dfcf9'
      || value.node.major !== 22
      || value.playwright.version !== '1.55.0'
      || value.playwright.browsersPath !== '/ms-playwright'
      || value.browser.name !== 'chromium' || value.browser.revision !== '1187'
      || value.browser.version !== '140.0.7339.16'
      || value.browser.executablePathPrefix !== '/ms-playwright/chromium-1187/') {
    throw new Error('invalid_runtime_spec_value');
  }
  for (const key of ['seedImplementationPaths', 'criticalReleasePaths',
    'forbiddenDynamicProvisioningPatterns']) {
    if (!Array.isArray(value[key]) || value[key].length === 0
        || value[key].some((item) => typeof item !== 'string' || !item)) {
      throw new Error(`invalid_runtime_spec_${key}`);
    }
  }
  value.seedImplementationPaths.forEach((relative) => fs.accessSync(exactPath(relative)));
  value.criticalReleasePaths.forEach((relative) => fs.accessSync(exactPath(relative)));
  return value;
}

export function loadRuntimeSpec(specPath = defaultSpecPath) {
  return validateRuntimeSpec(JSON.parse(fs.readFileSync(specPath, 'utf8')));
}

export function sourceSetDigest(paths) {
  const rows = paths.map((relative) => ({
    path: relative,
    sha256: sha256(fs.readFileSync(exactPath(relative))),
  }));
  return { digest: sha256(canonical(rows)), rows };
}

export function dynamicProvisioningAudit(spec) {
  const matches = [];
  for (const relative of spec.criticalReleasePaths) {
    const text = fs.readFileSync(exactPath(relative), 'utf8');
    for (const pattern of spec.forbiddenDynamicProvisioningPatterns) {
      if (new RegExp(pattern, 'i').test(text)) matches.push({ path: relative, pattern });
    }
  }
  return { pass: matches.length === 0, scannedPaths: [...spec.criticalReleasePaths], matches };
}

export function evaluateRuntimeAdmission({ spec, observed }) {
  const reasons = [];
  if (observed.runtimeAvailable !== true) reasons.push('runtime_unavailable');
  if (observed.containerRef !== `${spec.container.image}@${spec.container.digest}`) {
    reasons.push('container_identity_mismatch');
  }
  if (observed.platform !== spec.runner.os || observed.architecture !== spec.runner.architecture) {
    reasons.push('runner_identity_mismatch');
  }
  if (observed.nodeMajor !== spec.node.major) reasons.push('node_version_mismatch');
  if (observed.playwrightVersion !== spec.playwright.version) reasons.push('playwright_version_mismatch');
  if (observed.browserVersion !== spec.browser.version
      || typeof observed.browserExecutable !== 'string'
      || !observed.browserExecutable.startsWith(spec.browser.executablePathPrefix)
      || !SHA256.test(observed.browserExecutableSha256 ?? '')) {
    reasons.push('browser_identity_mismatch');
  }
  if (observed.browserLaunched !== true) reasons.push('browser_launch_failed');
  if (observed.contextCreated !== true || observed.pageCreated !== true) {
    reasons.push('browser_context_page_failed');
  }
  if (observed.profileWritable !== true) reasons.push('profile_write_failed');
  if (observed.seedImportSucceeded !== true || !SHA256.test(observed.seedImplementationDigest ?? '')) {
    reasons.push('seed_import_failed');
  }
  if (observed.noDynamicProvisioning !== true) reasons.push('dynamic_provisioning_detected');
  return { pass: reasons.length === 0, reasons };
}

const hashFile = async (target) => new Promise((resolve, reject) => {
  const digest = crypto.createHash('sha256');
  const stream = fs.createReadStream(target);
  stream.on('data', (chunk) => digest.update(chunk));
  stream.once('error', reject);
  stream.once('end', () => resolve(digest.digest('hex')));
});

export async function probeRuntime({ candidateSha, candidateTree, outPath,
  expectedRuntimeIdentityDigest = '' }) {
  if (!GIT_SHA.test(candidateSha ?? '') || !GIT_SHA.test(candidateTree ?? '')) {
    throw new Error('invalid_runtime_candidate_identity');
  }
  const spec = loadRuntimeSpec();
  const specDigest = sha256(canonical(spec));
  const seed = sourceSetDigest(spec.seedImplementationPaths);
  const provisioning = dynamicProvisioningAudit(spec);
  const packageValue = JSON.parse(fs.readFileSync(
    path.join(repoRoot, 'web/node_modules/playwright/package.json'), 'utf8'));
  const executable = fs.realpathSync(chromium.executablePath());
  const observed = {
    runtimeAvailable: true,
    containerRef: process.env.ARGUS_ACCEPTANCE_CONTAINER_REF ?? '',
    platform: process.platform,
    architecture: process.arch,
    nodeVersion: process.version,
    nodeMajor: Number(process.versions.node.split('.')[0]),
    playwrightVersion: packageValue.version,
    browserExecutable: executable,
    browserExecutableSha256: await hashFile(executable),
    browserVersion: null,
    browserLaunched: false,
    contextCreated: false,
    pageCreated: false,
    profileWritable: false,
    seedImportSucceeded: false,
    seedImplementationDigest: seed.digest,
    noDynamicProvisioning: provisioning.pass,
  };
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'argus-acceptance-runtime-'));
  let browser;
  let persistent;
  try {
    const marker = path.join(profile, 'write-proof.txt');
    fs.writeFileSync(marker, 'argus-runtime-profile-ready\n');
    observed.profileWritable = fs.readFileSync(marker, 'utf8') === 'argus-runtime-profile-ready\n';
    for (const relative of [
      'web/scripts/warm-profile-runtime.mjs',
      'web/scripts/warm-profile-contract.mjs',
      'web/scripts/canonical-snapshot-selection.mjs',
      'web/scripts/release-state-machine.mjs',
    ]) await import(`${pathToFileURL(exactPath(relative)).href}?runtime=${Date.now()}`);
    const syntax = spawnSync('bash', ['-n', exactPath('web/scripts/run-warm-profile-seed.sh')], {
      encoding: 'utf8', timeout: 10_000,
    });
    observed.seedImportSucceeded = syntax.status === 0;
    browser = await chromium.launch({ headless: true });
    observed.browserLaunched = true;
    observed.browserVersion = browser.version();
    const context = await browser.newContext();
    observed.contextCreated = true;
    const page = await context.newPage();
    observed.pageCreated = true;
    await page.goto('data:text/html,<title>ARGUS acceptance runtime</title>');
    assert.equal(await page.title(), 'ARGUS acceptance runtime');
    await context.close();
    await browser.close(); browser = null;
    persistent = await chromium.launchPersistentContext(profile, { headless: true });
    const profilePage = persistent.pages()[0] ?? await persistent.newPage();
    await profilePage.goto('data:text/html,<title>ARGUS profile</title>');
    assert.equal(await profilePage.title(), 'ARGUS profile');
    await persistent.close(); persistent = null;
  } finally {
    if (persistent) await persistent.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
    fs.rmSync(profile, { recursive: true, force: true });
  }
  const admission = evaluateRuntimeAdmission({ spec, observed });
  if (!admission.pass) throw new Error(`acceptance_runtime_rejected:${admission.reasons.join(',')}`);
  const runtimeIdentity = {
    schemaVersion: RUNTIME_IDENTITY_SCHEMA,
    specDigest,
    runtimeId: spec.runtimeId,
    runner: { os: observed.platform, architecture: observed.architecture,
      family: spec.runner.family },
    container: { image: spec.container.image, digest: spec.container.digest,
      amd64ManifestDigest: spec.container.amd64ManifestDigest },
    nodeVersion: observed.nodeVersion,
    playwrightVersion: observed.playwrightVersion,
    browser: { name: spec.browser.name, revision: spec.browser.revision,
      version: observed.browserVersion, executable: observed.browserExecutable,
      executableSha256: observed.browserExecutableSha256 },
    seedImplementationDigest: observed.seedImplementationDigest,
    candidate: { commitSha: candidateSha, treeSha: candidateTree },
  };
  const runtimeIdentityDigest = sha256(canonical(runtimeIdentity));
  if (expectedRuntimeIdentityDigest && runtimeIdentityDigest !== expectedRuntimeIdentityDigest) {
    throw new Error('acceptance_runtime_identity_differs_from_preproduction');
  }
  const proof = {
    schemaVersion: RUNTIME_PROOF_SCHEMA,
    status: 'PASS',
    candidate: runtimeIdentity.candidate,
    runtimeIdentity,
    runtimeIdentityDigest,
    checks: {
      runtimeAvailable: observed.runtimeAvailable,
      browserLaunched: observed.browserLaunched,
      contextCreated: observed.contextCreated,
      pageCreated: observed.pageCreated,
      profileWritable: observed.profileWritable,
      seedImportSucceeded: observed.seedImportSucceeded,
      noDynamicProvisioning: observed.noDynamicProvisioning,
    },
    noDynamicProvisioningAudit: provisioning,
  };
  proof.proofDigest = sha256(canonical(proof));
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, `${JSON.stringify(proof, null, 2)}\n`);
  return proof;
}

const args = Object.fromEntries(process.argv.slice(3).reduce((rows, value, index, all) => {
  if (value.startsWith('--')) rows.push([value.slice(2), all[index + 1]]);
  return rows;
}, []));
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const command = process.argv[2];
  if (command !== 'probe') throw new Error('acceptance_runtime_command_invalid');
  const proof = await probeRuntime({
    candidateSha: args['candidate-sha'], candidateTree: args['candidate-tree'],
    outPath: path.resolve(args.out),
    expectedRuntimeIdentityDigest: args['expected-runtime-identity'] ?? '',
  });
  console.log(`ARGUS_ACCEPTANCE_RUNTIME_IDENTITY=${proof.runtimeIdentityDigest}`);
  console.log('ZERO_INSTALL_ACCEPTANCE_RUNTIME=PASS');
}

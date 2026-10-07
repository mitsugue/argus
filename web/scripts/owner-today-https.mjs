// Complete existing Today engine on synthetic data through real owner auth.
// Run from web/; neither production endpoints nor user browser profiles used.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import { spawn, execFileSync } from 'node:child_process';
import { verifyOwnerModes } from './owner-mode-consistency.mjs';
import { startFixtureTarget } from './release-fixture-target.mjs';
import { loadSnapshotContract, validateSnapshotContract, triggerBusinessSnapshots } from './release-state-machine.mjs';

const mode = process.argv[2]; assert.ok(['0', '1'].includes(mode));
const scenario = process.argv[4] || 'today';
assert.ok(['today', 'passkey', 'migration'].includes(scenario));
assert.ok(scenario === 'today' || mode === '1');
const out = path.resolve(process.argv[3]); await fs.mkdir(out);
const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const tree = execFileSync('git', ['rev-parse', 'HEAD^{tree}'], { encoding: 'utf8' }).trim();
const clean = !execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
const root = await fs.mkdtemp(path.join(os.tmpdir(), 'argus-owner-today-'));
const dist = path.join(root, 'dist');
const password = crypto.randomBytes(32).toString('base64url');
const admin = crypto.randomBytes(32).toString('base64url');
const cert = path.join(root, 'cert.pem'), key = path.join(root, 'key.pem');
let target, front, proxy, python;
let activeRoot = root, backupHash;
let activeMode = scenario === 'migration' ? '0' : mode, authStarts = 0;
const temporaryRoots = [root];
const tunnels = new Set();
const report = { schema: 'argus-owner-today-https-v1', mode, scenario, sha, tree, clean, status: 'FAIL', syntheticOnly: true };
async function child(command, args, env, log, control, cwd) {
  const handle = await fs.open(path.join(out, log), 'wx');
  try {
    const p = spawn(command, args, { env, cwd, stdio: ['ignore', handle.fd, handle.fd, ...(control ? ['ipc'] : [])] });
    let controlError;
    let processing = false;
    if (control) p.on('message', async message => {
      if (processing) { controlError = new Error('fixture_control_overlap'); p.kill(); return; }
      processing = true;
      try { const result = await control(message); p.send({ ok: true, result }); }
      catch { controlError = new Error('fixture_control_failed'); p.kill(); }
      finally { processing = false; }
    });
    const code = await new Promise((resolve, reject) => { p.once('error', reject); p.once('exit', resolve); });
    if (controlError) throw controlError;
    assert.equal(code, 0, log);
  } finally { await handle.close(); }
}
try {
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key,
    '-out', cert, '-days', '1', '-subj', '/CN=argus-fixture.test', '-addext', 'subjectAltName=DNS:argus-fixture.test,IP:127.0.0.1'], { stdio: 'ignore' });
  await fs.chmod(key, 0o600);
  const ca = await fs.readFile(cert);
  const pub = execFileSync('openssl', ['x509', '-in', cert, '-pubkey', '-noout']);
  const der = execFileSync('openssl', ['pkey', '-pubin', '-outform', 'DER'], { input: pub });
  const spki = crypto.createHash('sha256').update(der).digest('base64');
  const env = { ...process.env, DEPLOY_BASE: '/argus/', VITE_ARGUS_OWNER_AUTH_REQUIRED: mode,
    VITE_ARGUS_BACKEND_URL: 'https://argus-fixture.test', VITE_ARGUS_BUILD_SHA: sha };
  await child('npm', ['run', 'build', '--', '--outDir', dist], env, 'build.log');
  let candidateDist;
  if (scenario === 'migration') {
    candidateDist = path.join(root, 'candidate-dist');
    await fs.rename(dist, candidateDist);
    const legacy = path.join(root, 'legacy'); await fs.mkdir(legacy);
    const legacySha = '22478dce1c7fa23304d36b0800d1edf54d3440fc';
    const archive = execFileSync('git', ['archive', legacySha, 'web', 'product-version.json'], { cwd: path.resolve('..'), maxBuffer: 32 * 1024 * 1024 });
    execFileSync('tar', ['-x', '-C', legacy], { input: archive });
    await fs.symlink(await fs.realpath('node_modules'), path.join(legacy, 'web/node_modules'));
    await child('npm', ['run', 'build', '--', '--outDir', dist], { ...env, VITE_ARGUS_OWNER_AUTH_REQUIRED: '0' }, 'legacy-build.log', undefined, path.join(legacy, 'web'));
    report.legacySourceSha = legacySha;
    report.sameBuildIdentityFixture = true;
  }
  const contract = validateSnapshotContract(loadSnapshotContract(new URL('../../release/v13-snapshot-readiness-contract.json', import.meta.url)));
  target = await startFixtureTarget({ distDir: dist, backendPort: 4399, frontendPort: 4373,
    candidateSha: sha, contract, adminToken: admin, seedSalt: 'owner-https-' + mode });
  await triggerBusinessSnapshots({ baseUrl: target.backendUrl, adminToken: admin, contract,
    expectedBuildSha: sha, producerTriggerId: 'owner-today-' + mode + '-' + sha.slice(0, 12) });
  assert.equal(target.fixture.snapshots.size, 12);
  front = https.createServer({ cert: ca, key: await fs.readFile(key) }, (req, res) => {
    const api = req.url.startsWith('/api/') || ['/healthz', '/readyz'].includes(req.url);
    const relay = (api ? https : http).request({ hostname: '127.0.0.1', port: api ? 4499 : 4373, ca,
      path: req.url, method: req.method, headers: req.headers }, reply => {
      res.writeHead(reply.statusCode, reply.headers); reply.pipe(res);
    });
    relay.on('error', () => { res.writeHead(502); res.end(); }); req.pipe(relay);
  });
  await new Promise((resolve, reject) => { front.once('error', reject); front.listen(4473, '127.0.0.1', resolve); });
  proxy = http.createServer((_req, res) => { res.writeHead(403); res.end(); });
  proxy.on('connect', (req, socket, head) => {
    // Fixed logical HTTPS authority only. No external network forwarding.
    if (req.url !== 'argus-fixture.test:443') { socket.end('HTTP/1.1 403 Forbidden\r\n\r\n'); return; }
    const upstream = net.connect(4473, '127.0.0.1', () => {
      socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head.length) upstream.write(head); socket.pipe(upstream); upstream.pipe(socket);
    });
    for (const stream of [socket, upstream]) { tunnels.add(stream); stream.on('close', () => tunnels.delete(stream)); }
    socket.on('error', () => upstream.destroy()); upstream.on('error', () => socket.destroy());
    socket.on('close', () => upstream.destroy()); upstream.on('close', () => socket.destroy());
  });
  await new Promise((resolve, reject) => { proxy.once('error', reject); proxy.listen(4480, '127.0.0.1', resolve); });
  async function startAuth() {
    const pylog = await fs.open(path.join(out, `fixture-${authStarts++}.log`), 'wx');
    python = spawn(process.env.ARGUS_TEST_PYTHON || 'python3', ['-B', 'scripts/owner-today-fixture.py'], { stdio: ['pipe', 'pipe', pylog.fd] });
    python.stdin.end(JSON.stringify({ mode: activeMode, root: activeRoot, password, admin, cert, key, origin: 'https://argus-fixture.test', upstream: target.backendUrl }) + '\n');
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('fixture_start_timeout')), 15000);
      python.stdout.once('data', data => { clearTimeout(timer); data.toString().includes('READY') ? resolve() : reject(new Error('fixture_start')); });
      python.once('exit', () => { clearTimeout(timer); reject(new Error('fixture_exit')); });
    }); await pylog.close();
  }
  await startAuth();
  report.anonymousStatus = await new Promise((resolve, reject) => {
    https.get('https://127.0.0.1:4473/api/argus/chart-intelligence?scope=market&symbol=1321&horizon=5D&snapshot=verified', { ca }, res => { res.resume(); resolve(res.statusCode); }).on('error', reject);
  }); assert.equal(report.anonymousStatus, activeMode === '1' ? 401 : 200);
  const acceptanceEnv = { ...process.env, NODE_EXTRA_CA_CERTS: cert, HTTPS_PROXY: 'http://127.0.0.1:4480', HTTP_PROXY: 'http://127.0.0.1:4480', NO_PROXY: '', https_proxy: '', http_proxy: '', no_proxy: '',
    ARGUS_PUBLIC_URL: 'https://argus-fixture.test/argus/', ARGUS_BACKEND_URL: 'https://argus-fixture.test',
    ARGUS_EXPECTED_SHA: sha, ARGUS_EXPECTED_VERSION: '13.8.74',
    ARGUS_ACCEPTANCE_OWNER_AUTH: mode, ARGUS_ACCEPTANCE_OWNER_ORIGIN: 'https://argus-fixture.test',
    ARGUS_ACCEPTANCE_OWNER_PASSWORD: password, ARGUS_FIXTURE_SPKI: spki, ARGUS_SYNTHETIC_OWNER_TODAY: '1',
    ARGUS_MOBILE_ACCEPTANCE_OUT: path.join(out, 'mobile') };
  // The Node process uses its generated CA; resolve only the fixed loopback fixture.
  const preflightFetch = async raw => {
    const logical = new URL(raw); assert.equal(logical.origin, 'https://argus-fixture.test');
    return new Promise((resolve, reject) => {
      https.get({ hostname: '127.0.0.1', port: 4473, path: logical.pathname + logical.search, ca }, res => {
        const chunks = []; res.on('data', bytes => chunks.push(bytes)); res.on('end', () => resolve(new Response(Buffer.concat(chunks), { status: res.statusCode })));
      }).on('error', reject);
    });
  };
  if (scenario !== 'migration') {
  report.modePreflight = await verifyOwnerModes({ publicUrl: acceptanceEnv.ARGUS_PUBLIC_URL,
    baseUrl: acceptanceEnv.ARGUS_BACKEND_URL, expectedSha: sha, mode, fetchImpl: preflightFetch });
  await assert.rejects(verifyOwnerModes({ publicUrl: acceptanceEnv.ARGUS_PUBLIC_URL,
    baseUrl: acceptanceEnv.ARGUS_BACKEND_URL, expectedSha: sha, mode: mode === '1' ? '0' : '1', fetchImpl: preflightFetch }), /owner_mode:mismatch/);
  }
  if (scenario === 'migration') {
    let activated = false;
    await child(process.execPath, ['--use-env-proxy', '--import', './scripts/owner-today-browser-preload.mjs', 'scripts/owner-pwa-migration-acceptance.mjs'],
      { ...acceptanceEnv, ARGUS_MIGRATION_OUT: path.join(out, 'migration.json'), ARGUS_MIGRATION_PROFILE: path.join(root, 'profile') }, 'migration.log', async message => {
        assert.deepEqual(message, { operation: 'activate' }); assert.equal(activated, false);
        python.kill('SIGTERM'); await new Promise(resolve => python.once('exit', resolve));
        // Keep old asset URLs available until existing documents finish updating.
        await fs.cp(candidateDist, dist, { recursive: true });
        activeMode = '1'; await startAuth(); activated = true;
        return { mode: '1' };
      });
    assert.equal(activated, true);
    report.acceptance = JSON.parse(await fs.readFile(path.join(out, 'migration.json'), 'utf8'));
    assert.equal(report.acceptance.status, 'PASS');
  } else if (scenario === 'passkey') {
    const backup = path.join(root, 'backup.sqlite3');
    const databaseCounts = database => JSON.parse(execFileSync(process.env.ARGUS_TEST_PYTHON || 'python3', ['-B', '-c',
      "import sqlite3,json,sys; c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(json.dumps({t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('owner_passkeys','owner_sessions','owner_challenges')}))", database], { encoding: 'utf8' }));
    const backupCLI = (operation, source, destination) => JSON.parse(execFileSync(process.env.ARGUS_TEST_PYTHON || 'python3',
      ['-B', '../scripts/owner_auth_backup.py', operation, '--source', source, '--destination', destination], { encoding: 'utf8' }));
    let checkpointed = false, restored = false;
    await child(process.execPath, ['--use-env-proxy', '--import', './scripts/owner-today-browser-preload.mjs',
      'scripts/owner-passkey-recovery-acceptance.mjs'], { ...acceptanceEnv, ARGUS_PASSKEY_OUT: path.join(out, 'passkey.json') }, 'passkey.log', async message => {
      assert.deepEqual(Object.keys(message), ['operation']);
      if (message.operation === 'checkpoint' && !checkpointed) {
        const counts = databaseCounts(path.join(root, 'owner.sqlite3'));
        assert.equal(counts.owner_passkeys, 1); assert.ok(counts.owner_sessions > 0);
        assert.equal(backupCLI('backup', path.join(root, 'owner.sqlite3'), backup).passkeys, 1);
        backupHash = crypto.createHash('sha256').update(await fs.readFile(backup)).digest('hex');
        checkpointed = true; return { counts, backupHash };
      }
      assert.equal(message.operation, 'restore'); assert.ok(checkpointed && !restored);
      const before = databaseCounts(path.join(root, 'owner.sqlite3'));
      assert.equal(before.owner_passkeys, 1); assert.ok(before.owner_sessions > 0);
      python.kill('SIGTERM'); await new Promise(resolve => python.once('exit', resolve));
      activeRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'argus-owner-today-'));
      temporaryRoots.push(activeRoot);
      const destination = path.join(activeRoot, 'owner.sqlite3');
      assert.equal(backupCLI('prepare-restore', backup, destination).passkeys, 0);
      assert.equal((await fs.stat(destination)).mode & 0o777, 0o600);
      assert.deepEqual(databaseCounts(destination), { owner_passkeys: 0, owner_sessions: 0, owner_challenges: 0 });
      assert.deepEqual(databaseCounts(path.join(root, 'owner.sqlite3')), before);
      assert.equal(crypto.createHash('sha256').update(await fs.readFile(backup)).digest('hex'), backupHash);
      await startAuth(); restored = true;
      return { originalPreserved: true, backupHash, restored: true, sessions: 0, challenges: 0, passkeys: 0 };
    });
    assert.ok(checkpointed && restored);
    report.acceptance = JSON.parse(await fs.readFile(path.join(out, 'passkey.json'), 'utf8'));
    assert.equal(report.acceptance.status, 'PASS');
  } else {
  await child(process.execPath, ['--use-env-proxy', '--import', './scripts/owner-today-browser-preload.mjs', 'scripts/mobile-today-acceptance.mjs'], acceptanceEnv, 'mobile.log');
  const result = JSON.parse(await fs.readFile(path.join(out, 'mobile', 'acceptance.json'), 'utf8'));
  assert.equal(result.verdict, 'PASS'); assert.equal(result.gateInventory.length, 15);
  assert.equal(result.combinationCount, 12); assert.deepEqual(result.failures, []);
  report.acceptance = { gates: result.gateInventory.map(x => x.id), combinations: result.combinationCount,
    offline: result.offline, frontendSha: result.frontendSha };
  }
  report.status = 'PASS';
} finally {
  if (python && python.exitCode === null) { python.kill('SIGTERM'); await new Promise(resolve => python.once('exit', resolve)); }
  for (const stream of tunnels) stream.destroy();
  if (proxy?.listening) await new Promise(resolve => proxy.close(resolve));
  if (front?.listening) await new Promise(resolve => front.close(resolve));
  if (target) await target.close();
  await fs.writeFile(path.join(out, 'result.json'), JSON.stringify(report, null, 2) + '\n');
  for (const directory of temporaryRoots) await fs.rm(directory, { recursive: true, force: true });
}
console.log(`owner-today-https: ${report.status}; mode=${mode}; scenario=${scenario}`);

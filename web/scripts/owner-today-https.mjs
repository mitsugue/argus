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
import { startFixtureTarget } from './release-fixture-target.mjs';
import { loadSnapshotContract, validateSnapshotContract, triggerBusinessSnapshots } from './release-state-machine.mjs';

const mode = process.argv[2]; assert.ok(['0', '1'].includes(mode));
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
const tunnels = new Set();
const report = { schema: 'argus-owner-today-https-v1', mode, sha, tree, clean, status: 'FAIL', syntheticOnly: true };
async function child(command, args, env, log) {
  const handle = await fs.open(path.join(out, log), 'wx');
  try {
    const p = spawn(command, args, { env, stdio: ['ignore', handle.fd, handle.fd] });
    const code = await new Promise((resolve, reject) => { p.once('error', reject); p.once('exit', resolve); });
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
  const pylog = await fs.open(path.join(out, 'fixture.log'), 'wx');
  python = spawn(process.env.ARGUS_TEST_PYTHON || 'python3', ['-B', 'scripts/owner-today-fixture.py'], { stdio: ['pipe', 'pipe', pylog.fd] });
  python.stdin.end(JSON.stringify({ mode, root, password, admin, cert, key, origin: 'https://argus-fixture.test', upstream: target.backendUrl }) + '\n');
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('fixture_start_timeout')), 15000);
    python.stdout.once('data', data => { clearTimeout(timer); data.toString().includes('READY') ? resolve() : reject(new Error('fixture_start')); });
    python.once('exit', () => { clearTimeout(timer); reject(new Error('fixture_exit')); });
  }); await pylog.close();
  report.anonymousStatus = await new Promise((resolve, reject) => {
    https.get('https://127.0.0.1:4473/api/argus/chart-intelligence?scope=market&symbol=1321&horizon=5D&snapshot=verified', { ca }, res => { res.resume(); resolve(res.statusCode); }).on('error', reject);
  }); assert.equal(report.anonymousStatus, mode === '1' ? 401 : 200);
  const acceptanceEnv = { ...process.env, NODE_EXTRA_CA_CERTS: cert, HTTPS_PROXY: 'http://127.0.0.1:4480', HTTP_PROXY: 'http://127.0.0.1:4480', NO_PROXY: '', https_proxy: '', http_proxy: '', no_proxy: '',
    ARGUS_PUBLIC_URL: 'https://argus-fixture.test/argus/', ARGUS_BACKEND_URL: 'https://argus-fixture.test',
    ARGUS_EXPECTED_SHA: sha, ARGUS_EXPECTED_VERSION: '13.7.51',
    ARGUS_ACCEPTANCE_OWNER_AUTH: mode, ARGUS_ACCEPTANCE_OWNER_ORIGIN: 'https://argus-fixture.test',
    ARGUS_ACCEPTANCE_OWNER_PASSWORD: password, ARGUS_FIXTURE_SPKI: spki, ARGUS_SYNTHETIC_OWNER_TODAY: '1',
    ARGUS_MOBILE_ACCEPTANCE_OUT: path.join(out, 'mobile') };
  await child(process.execPath, ['--use-env-proxy', '--import', './scripts/owner-today-browser-preload.mjs', 'scripts/mobile-today-acceptance.mjs'], acceptanceEnv, 'mobile.log');
  const result = JSON.parse(await fs.readFile(path.join(out, 'mobile', 'acceptance.json'), 'utf8'));
  assert.equal(result.verdict, 'PASS'); assert.equal(result.gateInventory.length, 15);
  assert.equal(result.combinationCount, 12); assert.deepEqual(result.failures, []);
  report.acceptance = { gates: result.gateInventory.map(x => x.id), combinations: result.combinationCount,
    offline: result.offline, frontendSha: result.frontendSha };
  report.status = 'PASS';
} finally {
  if (python && python.exitCode === null) { python.kill('SIGTERM'); await new Promise(resolve => python.once('exit', resolve)); }
  for (const stream of tunnels) stream.destroy();
  if (proxy?.listening) await new Promise(resolve => proxy.close(resolve));
  if (front?.listening) await new Promise(resolve => front.close(resolve));
  if (target) await target.close();
  await fs.writeFile(path.join(out, 'result.json'), JSON.stringify(report, null, 2) + '\n');
  await fs.rm(root, { recursive: true, force: true });
}
console.log(`owner-today-https: ${report.status}; mode=${mode}; full M01-M15`);

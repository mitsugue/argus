import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { build } from 'esbuild';
import { chromium } from 'playwright';
import { createBrowserOwner, verifiedStoreFingerprint, assertNoSecrets, isOwnerCeremony } from './owner-browser-acceptance.mjs';

// Dedicated synthetic origin/profile only. No real user browser or data.
const root = await fs.mkdtemp(path.join(os.tmpdir(), 'argus-owner-browser-fixture-'));
const password = 'synthetic-' + crypto.randomBytes(24).toString('hex');
const tokens = new Set(), sessions = new Set(), requests = [];
let origin, bundle, invalidProof = false, holdProof = false, releaseProof, context;
const data = { key: 'fixture', snapshotId: 'preserved-snapshot-001', history: ['original'], settings: { theme: 'dark' } };
execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-keyout', path.join(root, 'key.pem'), '-out', path.join(root, 'cert.pem'), '-subj', '/CN=localhost'], { stdio: 'ignore' });
const html = '<!doctype html><html><body><div id="root"></div><script type="module" src="/app.js"></script></body></html>';
const sw = `self.addEventListener('install',e=>e.waitUntil(caches.open('synthetic-shell').then(c=>c.addAll(['/','/app.js']))));self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',e=>{if(e.request.method==='GET'&&!new URL(e.request.url).pathname.startsWith('/api/'))e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});`;
const server = https.createServer({ key: await fs.readFile(path.join(root, 'key.pem')), cert: await fs.readFile(path.join(root, 'cert.pem')) }, async (req, res) => {
  const send = (status, body, headers = {}) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...headers }); res.end(JSON.stringify(body)); };
  if (req.url.startsWith('/api/')) {
    requests.push({ path: req.url, method: req.method });
    if (req.url.endsWith('/password')) {
      let body = ''; for await (const part of req) body += part;
      if (req.headers.origin !== origin || JSON.parse(body).password !== password) return send(401, { error: 'owner_auth_required' });
      const token = crypto.randomBytes(32).toString('base64url'); tokens.add(token); sessions.add(token);
      return send(200, { token, expiresAt: Date.now() + 1800000 });
    }
    const token = req.headers['x-argus-owner-session'];
    if (!sessions.has(token)) return send(401, { error: 'owner_auth_required' });
    if (holdProof && req.url.endsWith('/session')) await new Promise(resolve => { releaseProof = resolve; });
    const headers = { 'X-ARGUS-OWNER-NONCE': (invalidProof ? 'old-cached-nonce' : req.headers['x-argus-owner-nonce']) || '' };
    if (req.url.endsWith('/logout')) { sessions.delete(token); return send(200, { loggedOut: true }, headers); }
    return send(200, { authenticated: true }, headers);
  }
  if (req.url === '/app.js') { res.writeHead(200, { 'Content-Type': 'text/javascript' }); res.end(bundle); return; }
  if (req.url === '/sw.js') { res.writeHead(200, { 'Content-Type': 'text/javascript', 'Cache-Control': 'no-store' }); res.end(sw); return; }
  res.writeHead(200, { 'Content-Type': 'text/html' }); res.end(html);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
origin = `https://127.0.0.1:${server.address().port}`;
const profile = path.join(root, 'profile');
const env = { ARGUS_ACCEPTANCE_OWNER_AUTH: '1', ARGUS_ACCEPTANCE_OWNER_ORIGIN: origin, ARGUS_ACCEPTANCE_OWNER_PASSWORD: password };
const owner = createBrowserOwner({ baseUrl: origin, publicUrl: origin, env });
let checks = 0;
const check = (value, message) => { assert.ok(value, message); checks++; };
try {
  bundle = (await build({ stdin: { contents: `
import React, {useEffect,useState} from 'react';import {createRoot} from 'react-dom/client';
import {OwnerAccess} from './src/components/OwnerAccess';import {installOwnerTransport} from './src/lib/ownerSession';
installOwnerTransport();navigator.serviceWorker.register('/sw.js');
async function open(){return new Promise((resolve,reject)=>{const r=indexedDB.open('argus-verified-snapshots',1);r.onupgradeneeded=()=>r.result.createObjectStore('snapshots',{keyPath:'key'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
const db=await open();await new Promise(resolve=>{const tx=db.transaction('snapshots','readwrite');const store=tx.objectStore('snapshots');const r=store.get('fixture');r.onsuccess=()=>{if(!r.result)store.put(${JSON.stringify(data)});};tx.oncomplete=resolve;});db.close();
function Body(){const [row,setRow]=useState(null);useEffect(()=>{open().then(db=>{const r=db.transaction('snapshots').objectStore('snapshots').get('fixture');r.onsuccess=()=>{setRow(r.result);db.close();};});},[]);return <main><nav className="nav__mobile">Today</nav><p data-argus-contract="canonical-market-snapshot-v1" data-canonical-snapshot-id={row?.snapshotId}>{row?.snapshotId}</p></main>;}
createRoot(document.getElementById('root')).render(<OwnerAccess><Body/></OwnerAccess>);
`, resolveDir: process.cwd(), loader: 'tsx' }, bundle: true, write: false, format: 'esm', target: 'es2022', loader: { '.css': 'empty' }, define: { 'import.meta.env': JSON.stringify({ VITE_ARGUS_OWNER_AUTH_REQUIRED: '1', VITE_ARGUS_BACKEND_URL: origin }) } })).outputFiles[0].text;
  const launch = () => chromium.launchPersistentContext(profile, { headless: true, ignoreHTTPSErrors: true, args: ['--ignore-certificate-errors'] });
  context = await launch(); let page = await context.newPage();
  await page.goto(origin); await owner.locked(page);
  check(!requests.length, 'locked app does not read business APIs');
  const before = await verifiedStoreFingerprint(page);
  await owner.login(page);
  await page.locator('[data-canonical-snapshot-id="preserved-snapshot-001"]').waitFor();
  check(sessions.size === 1, 'one server session after UI login');
  check(JSON.stringify(await verifiedStoreFingerprint(page)) === JSON.stringify(before), 'login preserves contents');
  await page.evaluate(() => navigator.serviceWorker.ready);
  await context.setOffline(true); await owner.locked(page);
  check(await page.getByText('オフラインです。保存データは残っています。接続後に本人確認をしてください。', { exact: true }).isVisible(), 'offline locks immediately');
  check(await page.getByRole('button', { name: 'パスワードで開く', exact: true }).isDisabled(), 'offline login disabled');
  await page.reload(); await owner.locked(page);
  check(JSON.stringify(await verifiedStoreFingerprint(page)) === JSON.stringify(before), 'offline reload preserves history/settings/snapshot');
  await context.setOffline(false); await owner.login(page);
  await page.locator('[data-canonical-snapshot-id="preserved-snapshot-001"]').waitFor();
  check(JSON.stringify(await verifiedStoreFingerprint(page)) === JSON.stringify(before), 'online restores original result');
  await owner.logout(page); await context.close(); context = null;
  await owner.scan(profile); checks++;
  context = await launch(); page = await context.newPage(); await page.goto(origin); await owner.locked(page);
  check(JSON.stringify(await verifiedStoreFingerprint(page)) === JSON.stringify(before), 'reopened profile locked with data');
  invalidProof = true;
  await page.getByLabel('復旧用パスワード', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'パスワードで開く', exact: true }).click();
  await page.getByText('操作を完了できませんでした。接続と認証情報を確認してください。', { exact: true }).waitFor();
  await owner.locked(page); checks++;
  check(await page.getByLabel('復旧用パスワード', { exact: true }).inputValue() === '', 'failed password cleared');
  invalidProof = false; holdProof = true;
  await page.getByLabel('復旧用パスワード', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'パスワードで開く', exact: true }).click();
  while (!releaseProof) await new Promise(resolve => setTimeout(resolve, 10));
  check(await page.locator('main').count() === 0, 'pending proof cannot mount content');
  await page.evaluate(() => window.dispatchEvent(new Event('offline')));
  holdProof = false; releaseProof();
  await page.getByText('操作を完了できませんでした。接続と認証情報を確認してください。', { exact: true }).waitFor();
  await owner.locked(page); checks++;
  await context.close(); context = null;
  await assertNoSecrets(profile, new Set([password, ...tokens])); checks++;
  const sample = path.join(root, 'scan.bin');
  await fs.writeFile(sample, Buffer.concat([Buffer.alloc(65530), Buffer.from(password)]));
  await assert.rejects(assertNoSecrets(sample, new Set([password])), /artifact_secret/); checks++;
  await fs.writeFile(sample, Buffer.from(password, 'utf16le'));
  await assert.rejects(assertNoSecrets(sample, new Set([password])), /artifact_secret/); checks++;
  await fs.unlink(sample); await fs.symlink(path.join(root, 'cert.pem'), sample);
  await assert.rejects(assertNoSecrets(sample, new Set([password])), /artifact_link/); checks++;
  assert.throws(() => createBrowserOwner({ baseUrl: origin, publicUrl: 'https://elsewhere.invalid', env }), /configuration/); checks++;
  check(!isOwnerCeremony(origin + '/api/argus/mission', origin, 'POST') && !isOwnerCeremony('https://elsewhere.invalid/api/argus/owner-auth/password', origin, 'POST'), 'ceremony exact origin/path');
  console.log(`owner-browser-continuity: PASS (${checks} checks; synthetic HTTPS, React UI, SW, IndexedDB and reopened profile)`);
} finally {
  if (context) await context.close();
  await new Promise(resolve => server.close(resolve));
  await fs.rm(root, { recursive: true, force: true });
}

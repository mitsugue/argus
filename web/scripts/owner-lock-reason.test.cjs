// The lock screen names why the previous login did not continue (owner,
// 2026-10-04): a fixed code kept for one app session, never a credential.
const assert = require('node:assert/strict'), Module = require('node:module'), path = require('node:path'), esbuild = require('esbuild');
Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {onLine: true}});
let sessionStatus = 200; const serverToken = 'y'.repeat(43);
const original = async (request) => {
  const headers = {'X-ARGUS-OWNER-NONCE': request.headers.get('X-ARGUS-OWNER-NONCE') ?? ''};
  if (request.url.endsWith('/password')) return Response.json({token: serverToken, expiresAt: Date.now() + 86400000});
  if (request.url.endsWith('/session') && sessionStatus === 401) return Response.json({error: 'owner_auth_required'}, {status: 401, headers});
  if (request.url.endsWith('/data-401')) return Response.json({error: 'owner_auth_required'}, {status: 401, headers});
  return Response.json({ok: true, authenticated: true}, {headers});
};
const stored = new Map(); let standalone = true;
global.sessionStorage = {getItem: k => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, String(v)), removeItem: k => stored.delete(k)};
global.window = {matchMedia: () => ({matches: standalone}), fetch: original, location: {origin: 'https://owner.example'},
  setInterval: () => 1, addEventListener: () => {}};
global.document = {hidden: false, documentElement: {dataset: {}}, addEventListener: () => {}};
const load = () => {
  const entry = path.resolve('src/lib/ownerSession.ts');
  const code = esbuild.buildSync({entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs',
    define: {'import.meta.env': JSON.stringify({VITE_ARGUS_OWNER_AUTH_REQUIRED: '1', VITE_ARGUS_BACKEND_URL: 'https://api.example'})},
    logLevel: 'silent'}).outputFiles[0].text;
  const mod = new Module(entry, module); mod.filename = entry; mod.paths = module.paths; mod._compile(code, entry);
  return mod.exports;
};
(async () => {
  let api = load(); api.installOwnerTransport(); global.fetch = window.fetch;
  await api.passwordLogin('fixture-password');
  assert.equal(api.ownerLockReason(), '', 'a fresh login clears the old reason');
  // A 401 on a page read ends the session; after a reload the reason is still there.
  await fetch('https://api.example/api/argus/data-401').catch(() => {});
  assert.equal(api.hasOwnerSession(), false);
  assert.match(api.ownerLockReason(), /^response_401:\/api\/argus\/data-401$/);
  api = load();                                                     // reload: module state is new
  assert.equal(await api.restoreOwnerSession(), false);
  assert.match(api.ownerLockReason(), /^response_401:/, 'the earlier, specific reason is kept');
  // Nothing saved in the app (a full quit): named as such.
  stored.clear(); api = load();
  assert.equal(await api.restoreOwnerSession(), false);
  assert.equal(api.ownerLockReason(), 'restore_nothing_saved');
  // A browser tab never keeps the login: named as such.
  stored.clear(); standalone = false; api = load();
  assert.equal(await api.restoreOwnerSession(), false);
  assert.equal(api.ownerLockReason(), 'restore_browser_tab');
  // The server rejects a kept login.
  stored.clear(); standalone = true; api = load(); api.installOwnerTransport(); global.fetch = window.fetch;
  await api.passwordLogin('fixture-password'); assert.equal(api.ownerLockReason(), '');
  sessionStatus = 401; api = load();
  assert.equal(await api.restoreOwnerSession(), false);
  assert.equal(api.ownerLockReason(), 'restore_server_rejected');
  // Only a fixed code is kept: never the credential.
  for (const value of stored.values()) assert.ok(!value.includes(serverToken) || value.includes('"token"'));
  assert.ok(![...stored.entries()].some(([k, v]) => k === 'argus.owner.lock.v1' && v.includes(serverToken)));
  console.log('Owner lock reason PASS'); process.exit(0);   // the 24-hour expiry timer would keep Node alive
})().catch(e => { console.error(e); process.exit(1); });

const assert = require('node:assert/strict'), Module = require('node:module'), path = require('node:path'), esbuild = require('esbuild');
// Supply browser state explicitly on every Node runtime used by CI.
const browserNavigator = {onLine: true};
Object.defineProperty(globalThis, 'navigator', {configurable: true, value: browserNavigator});
const calls = [], listeners = {}; const serverToken = 'x'.repeat(43); let pending;
const original = async (request) => {
  calls.push(request);
  const headers = {'X-ARGUS-OWNER-NONCE': request.headers.get('X-ARGUS-OWNER-NONCE') ?? ''};
  if (request.url.endsWith('/password')) return Response.json({token: serverToken, expiresAt: Date.now() + 86400000});
  if (request.url.endsWith('/logout')) return Response.json({loggedOut: true}, {headers});
  if (request.url.endsWith('/slow')) return new Promise(resolve => { pending = resolve; });
  if (request.url.endsWith('/session') && sessionStatus !== 200) {
    if (sessionStatus === 'network') throw new TypeError('Failed to fetch');
    return Response.json({error: sessionStatus === 401 ? 'owner_auth_required' : 'try_later'}, {status: sessionStatus, headers});
  }
  return Response.json({ok: true, authenticated: true}, request.url.endsWith('/old-cache') ? {} : {headers});
};
let validateTick = null; let sessionStatus = 200;
const stored = new Map();
global.sessionStorage = {getItem: k => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, String(v)), removeItem: k => stored.delete(k)};
let standalone = true;
global.window = {matchMedia: () => ({matches: standalone}), fetch: original, location: {origin: 'https://owner.example'}, setInterval: (f) => { validateTick = f; return 1; }, addEventListener: (n, f) => { listeners[n] = f; }};
global.document = {hidden: false, addEventListener: (n, f) => { listeners[n] = f; }};
const entry = path.resolve('src/lib/ownerSession.ts');
const code = esbuild.buildSync({entryPoints: [entry],bundle: true,write: false,platform: 'node',format: 'cjs', define: {'import.meta.env': JSON.stringify({VITE_ARGUS_OWNER_AUTH_REQUIRED: '1', VITE_ARGUS_BACKEND_URL: 'https://api.example'})},logLevel:'silent'}).outputFiles[0].text;
const mod = new Module(entry,module); mod.filename=entry;mod.paths=module.paths;mod._compile(code,entry);
const api=mod.exports; api.installOwnerTransport(); global.fetch=window.fetch;
(async () => {
  await assert.rejects(fetch('https://api.example/api/argus/data'), /owner_auth_required/); assert.equal(calls.length, 0);
  await api.passwordLogin('fixture-password'); assert.equal(api.hasOwnerSession(), true);
  await fetch('https://api.example/api/argus/data', {headers: {'X-Preserved': 'value'}});
  assert.equal(calls.at(-1).headers.get('X-ARGUS-OWNER-SESSION'), serverToken);
  assert.equal(calls.at(-1).headers.get('X-Preserved'), 'value');
  assert.equal(calls.at(-1).redirect, 'error'); assert.equal(calls.at(-1).cache, 'no-store');
  await fetch('https://elsewhere.example/api/data'); assert.equal(calls.at(-1).headers.has('X-ARGUS-OWNER-SESSION'), false);
  await fetch('https://api.example.evil.example/api/data'); assert.equal(calls.at(-1).headers.has('X-ARGUS-OWNER-SESSION'), false);
  const slow = fetch('https://api.example/api/argus/slow'); await api.logoutOwner();
  assert.equal(api.hasOwnerSession(), false); assert.equal(calls.at(-1).headers.get('X-ARGUS-OWNER-SESSION'), serverToken);
  pending(Response.json({secret: 'old-response'})); await assert.rejects(slow, /owner_session_changed/);
  await api.passwordLogin('fixture-password');
  await assert.rejects(fetch('https://api.example/api/argus/old-cache'), /owner_response_unverified/);
  assert.equal(api.hasOwnerSession(), false);
  // 2026-10-02: a reload keeps this app session's login (same build, server echo).
  await api.passwordLogin('fixture-password');
  assert.equal(listeners.pagehide, undefined, 'a reload or app switch does not lock');
  const saved = JSON.parse(stored.get('argus.owner.session.v1'));
  assert.equal(saved.token, serverToken); assert.equal(saved.build, 'unknown');
  // Simulate the reload: the page memory is gone, the app session's storage is not.
  api.clearOwnerSession(); stored.set('argus.owner.session.v1', JSON.stringify(saved));
  const fresh = new Module(entry, module); fresh.filename = entry; fresh.paths = module.paths; fresh._compile(code, entry);
  assert.equal(fresh.exports.hasOwnerSession(), false);
  assert.equal(await fresh.exports.restoreOwnerSession(), true, 'restored after a fresh server echo');
  assert.equal(fresh.exports.hasOwnerSession(), true);
  fresh.exports.clearOwnerSession(); // releases its expiry timer
  stored.set('argus.owner.session.v1', JSON.stringify({...saved, build: 'older-build'}));
  const updated = new Module(entry, module); updated.filename = entry; updated.paths = module.paths; updated._compile(code, entry);
  assert.equal(await updated.exports.restoreOwnerSession(), false, 'an app update requires a new login');
  assert.equal(stored.has('argus.owner.session.v1'), false);
  stored.set('argus.owner.session.v1', JSON.stringify(saved)); sessionStatus = 401;
  const revoked = new Module(entry, module); revoked.filename = entry; revoked.paths = module.paths; revoked._compile(code, entry);
  assert.equal(await revoked.exports.restoreOwnerSession(), false, 'a revoked session is not resumed');
  sessionStatus = 200;
  await api.passwordLogin('fixture-password'); assert.equal(stored.has('argus.owner.session.v1'), true);
  await api.logoutOwner(); assert.equal(stored.has('argus.owner.session.v1'), false, 'logout clears the saved login');
  // An ordinary browser tab never writes the credential to storage (its profile is on disk).
  standalone = false;
  await api.passwordLogin('fixture-password'); assert.equal(api.hasOwnerSession(), true);
  assert.equal(stored.has('argus.owner.session.v1'), false, 'a browser tab keeps the login in memory only');
  stored.set('argus.owner.session.v1', JSON.stringify(saved));
  const tab = new Module(entry, module); tab.filename = entry; tab.paths = module.paths; tab._compile(code, entry);
  assert.equal(await tab.exports.restoreOwnerSession(), false, 'a browser tab does not resume from storage');
  assert.equal(stored.has('argus.owner.session.v1'), false);
  await api.logoutOwner(); standalone = true;
  browserNavigator.onLine = false;
  await assert.rejects(api.passwordLogin('fixture-password'), /authentication_cancelled/);
  assert.equal(api.hasOwnerSession(), false);
  browserNavigator.onLine = true;
  await api.passwordLogin('fixture-password');
  assert.equal(listeners.offline, undefined, 'a network blip does not lock; the server still decides');
  // 2026-09-30: the periodic session ping locks only on a definite 401.
  await api.passwordLogin('fixture-password'); assert.equal(typeof validateTick, 'function');
  const tick = async () => { validateTick(); await new Promise(resolve => setTimeout(resolve, 20)); };
  for (const transient of [429, 503, 'network']) {
    sessionStatus = transient; const before = calls.length; await tick();
    assert.equal(calls.length, before + 1, `pinged during ${transient}`);
    assert.equal(api.hasOwnerSession(), true, `kept through ${transient}`);
  }
  sessionStatus = 401; await tick(); assert.equal(api.hasOwnerSession(), false);
  sessionStatus = 200;
  console.log('Owner transport: locked requests, exact origin, preserved headers, no-store, no redirects, logout and stale response isolation PASS');
})().catch(error => {api.clearOwnerSession(); console.error(error);process.exit(1);});

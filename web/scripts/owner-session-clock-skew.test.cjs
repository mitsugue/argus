// 2026-10-17: the session expiry is stamped with the server's clock. A device a
// second behind a newly started server rejected every valid sign-in
// (session_invalid). A few seconds of difference are accepted; a session
// longer than 24 hours plus five minutes is still refused.
const assert = require('node:assert/strict'), Module = require('node:module'), path = require('node:path'), esbuild = require('esbuild');
Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {onLine: true}});
let serverAheadMs = 0;
const respond = async (request) => {
  const headers = {'X-ARGUS-OWNER-NONCE': request.headers.get('X-ARGUS-OWNER-NONCE') ?? ''};
  if (request.url.endsWith('/password')) return Response.json({token: 'z'.repeat(43), expiresAt: Date.now() + serverAheadMs + 86_400_000});
  return Response.json({ok: true, authenticated: true}, {headers});
};
const stored = new Map();
global.sessionStorage = {getItem: k => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, String(v)), removeItem: k => stored.delete(k)};
global.window = {matchMedia: () => ({matches: false}), fetch: respond, location: {origin: 'https://owner.example'},
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
  for (const ahead of [0, 1_500, 90_000]) {
    serverAheadMs = ahead;
    const api = load(); api.installOwnerTransport(); global.fetch = window.fetch;
    await api.passwordLogin('fixture-password');
    assert.equal(api.hasOwnerSession(), true, `server ${ahead} ms ahead is accepted`);
  }
  serverAheadMs = 10 * 60_000;
  const api = load(); api.installOwnerTransport(); global.fetch = window.fetch;
  await assert.rejects(api.passwordLogin('fixture-password'), e => /session_invalid/.test(JSON.stringify(api.ownerLoginFailure(e))));
  console.log('ログインの有効期限: 時計のずれ5分まで受け付け、24時間を超えるものは拒否 PASS'); process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });

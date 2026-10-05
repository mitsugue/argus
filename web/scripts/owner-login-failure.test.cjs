const assert = require('node:assert/strict'), Module = require('node:module'), path = require('node:path'), esbuild = require('esbuild');
const secret = 'private-fixture-value';
let mode = 'ok';
Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {onLine: true,
  credentials: {get: async () => {throw new DOMException(secret, mode === 'unsupported' ? 'NotSupportedError' : 'NotAllowedError');}}}});
global.document = {hidden: false, documentElement: {dataset: {}}, addEventListener() {}};
global.window = {location: {origin: 'https://owner.example'}, matchMedia: () => ({matches: true}),
  setInterval() {}, addEventListener() {}, fetch: async () => {}};
global.fetch = async (url, init) => {
  if (mode === 'network') throw new TypeError(secret);
  if (mode === 'timeout') throw new DOMException(secret, 'TimeoutError');
  if (url.endsWith('/password') || url.endsWith('/login-options')) {
    if (url.endsWith('/login-options') && ['unsupported', 'device_cancelled'].includes(mode))
      return Response.json({challengeId: 'fixture', publicKey: {challenge: 'YQ', allowCredentials: []}});
    if (typeof mode === 'number') return Response.json({error: secret}, {status: mode});
    if (mode === 'invalid') return new Response(secret);
    return Response.json({token: 's'.repeat(43), expiresAt: Date.now() + 86400000});
  }
  if (mode === 'session_rejected') return Response.json({error: secret}, {status: 401});
  if (mode === 'session_unavailable') return Response.json({error: secret}, {status: 503});
  if (mode === 'session_unverified') return Response.json({authenticated: true});
  return Response.json({authenticated: true}, {headers: {'X-ARGUS-OWNER-NONCE': init.headers['X-ARGUS-OWNER-NONCE']}});
};
const entry = path.resolve('src/lib/ownerSession.ts');
const code = esbuild.buildSync({entryPoints: [entry], bundle: true, write: false, platform: 'node', format: 'cjs',
  define: {'import.meta.env': JSON.stringify({VITE_ARGUS_OWNER_AUTH_REQUIRED: '1', VITE_ARGUS_BACKEND_URL: 'https://api.example'})},
  logLevel: 'silent'}).outputFiles[0].text;
const mod = new Module(entry, module); mod.filename = entry; mod.paths = module.paths; mod._compile(code, entry);
const api = mod.exports;
async function expectFailure(value, expected, phrase, fn = () => api.passwordLogin(secret)) {
  mode = value;
  let caught;
  try { await fn(); } catch (error) { caught = error; }
  assert(caught, 'a failed login must remain locked');
  const result = api.ownerLoginFailure(caught);
  assert.equal(result.code, expected);
  assert(result.message.includes(phrase), result.message);
  assert(!JSON.stringify(result).includes(secret), 'never display raw exceptions or response data');
  assert.equal(api.hasOwnerSession(), false);
}
(async () => {
  await expectFailure(401, 'password_rejected', 'パスワード');
  await expectFailure(403, 'password_forbidden', 'サーバーに認められません');
  await expectFailure(429, 'password_limited', '1分ほど');
  await expectFailure(503, 'password_unavailable', '一時的');
  await expectFailure('network', 'password_network', '接続できません');
  await expectFailure('timeout', 'password_timeout', '時間内');
  await expectFailure('invalid', 'password_invalid', '読み取れません');
  await expectFailure('session_rejected', 'session_rejected', 'ログイン後');
  await expectFailure('session_unavailable', 'session_unavailable', '一時的');
  await expectFailure('session_unverified', 'session_unverified', '完了していません');
  await expectFailure(401, 'passkey_start_rejected', 'パスキーの開始', () => api.useOwnerPasskey(false));
  await expectFailure('unsupported', 'passkey_device_unsupported', 'この端末', () => api.useOwnerPasskey(false));
  await expectFailure('device_cancelled', 'passkey_device_incomplete', '端末での', () => api.useOwnerPasskey(false));
  assert.equal(api.ownerLoginFailure(new Error(secret)).code, 'unknown');
  assert(!JSON.stringify(api.ownerLoginFailure(new Error(secret))).includes(secret));
  mode = 'ok'; await api.passwordLogin(secret);
  assert.equal(api.hasOwnerSession(), true, 'the existing nonce-verified success path still unlocks');
  api.clearOwnerSession();
  console.log('本人確認の失敗段階・通信と拒否の区別・秘密情報非表示・成功経路 PASS');
})().catch(error => {api.clearOwnerSession(); console.error(error); process.exit(1);});

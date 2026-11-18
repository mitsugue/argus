// 2026-11-18 owner 「やはり作る」: a device whose notification registration
// expired says so on Today; nothing is shown without a definite answer.
import fs from 'node:fs'; import vm from 'node:vm'; import assert from 'node:assert/strict'; import ts from 'typescript';
const src = fs.readFileSync('src/lib/webPushHealth.ts', 'utf8').replace(/import\.meta\.env/g, '({})');
const mod = { exports: {} };
vm.runInNewContext(ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText,
  { exports: mod.exports, Promise, Error });
const state = mod.exports.pushRegistrationState;
const run = (registered, endpoint, answer) => state({ registered,
  subscriptionEndpoint: async () => { if (endpoint instanceof Error) throw endpoint; return endpoint; },
  serverAnswer: async () => { if (answer instanceof Error) throw answer; return answer; },
  digest: async text => 'h:' + text });
// The 10/8 case: this iPhone had registered, and now has no registration at all.
assert.equal(await run(true, null, 'enabled'), 'lost');
assert.equal(await run(true, 'https://push/x', 'disabled'), 'lost');
assert.equal(await run(true, 'https://push/x', 'missing'), 'lost');
assert.equal(await run(true, 'https://push/x', 'enabled'), 'ok');
assert.equal(await run(false, 'https://push/x', 'enabled'), 'ok');
// Never registered here, or turned off here: no notice.
assert.equal(await run(false, null, 'enabled'), 'none');
assert.equal(await run(false, 'https://push/x', 'disabled'), 'none');
// No definite answer (network, sign-in, no worker): no notice.
assert.equal(await run(true, 'https://push/x', 'unknown'), 'unknown');
assert.equal(await run(true, 'https://push/x', new Error('offline')), 'unknown');
assert.equal(await run(true, new Error('no_worker'), 'enabled'), 'unknown');
const notice = fs.readFileSync('src/components/today/PushRegistrationNotice.tsx', 'utf8');
assert.ok(notice.includes("state !== 'unknown'") && notice.includes("setLost(state === 'lost')"));
assert.ok(notice.includes('この端末の通知の登録が切れています。') && notice.includes('href="#settings"'));
assert.ok(fs.readFileSync('src/routes/CommandCenter.tsx', 'utf8').includes('<PushRegistrationNotice />'));
const panel = fs.readFileSync('src/components/settings/WebPushPanel.tsx', 'utf8');
assert.ok(panel.includes('rememberPushRegistered(true)') && panel.includes('rememberPushRegistered(false)'));
const health = fs.readFileSync('src/lib/webPushHealth.ts', 'utf8');
assert.ok(health.includes("operation: 'status'") && health.includes("data.error === 'push_subscription_missing'"));
// The server answers these exact shapes (argus_web_push / argus_owner_dialogue_api).
const py = ['../argus_web_push.py', '../argus_owner_dialogue_api.py'].map(f => fs.readFileSync(f, 'utf8')).join('\n');
for (const shape of ["raise ValueError('push_subscription_missing')", "'enabled': bool(row['enabled'])", "reason.startswith(('push_'"])
  assert.ok(py.includes(shape), shape);
console.log('通知の登録切れ: 切れた端末だけ Today に一行・答えがないときは出さない PASS');

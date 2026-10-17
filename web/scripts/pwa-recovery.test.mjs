import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/lib/pwaRecovery.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const removed = [], deleted = [];
const base = 'https://example.test/argus/';
const registration = (name, scope, file, subscription = null) => ({
  scope, active: { scriptURL: new URL(file, scope).href },
  pushManager: { getSubscription: async () => {
    if (subscription === 'error') throw new Error('lookup unavailable');
    return subscription;
  } },
  unregister: async () => { removed.push(name); return true; },
});
const sandbox = { exports: {}, URL, location: { href: base },
  navigator: { serviceWorker: { getRegistrations: async () => [
    registration('shell', base, 'sw.js'),
    registration('subscribed-shell', base, 'sw.js', { endpoint: 'test' }),
    registration('uncertain-shell', base, 'sw.js', 'error'),
    registration('notifications', base + 'notifications/', 'sw.js', { endpoint: 'test' }),
    registration('other-app', 'https://example.test/other/', 'sw.js'),
    registration('unknown-worker', base, 'custom-worker.js'),
  ] } },
  caches: { keys: async () => ['argus-api', 'fonts-cache', 'owner-data',
    'workbox-precache-v2-' + base, 'workbox-precache-v2-https://example.test/other/'],
    delete: async (key) => { deleted.push(key); return true; } },
};
vm.runInNewContext(compiled, sandbox);
await sandbox.exports.repairAppCaches('/argus/');
assert.deepEqual(removed, ['shell']);
assert.deepEqual(deleted, ['argus-api', 'workbox-precache-v2-' + base]);
// The pre-bundle recovery uses this same function without imported runtime helpers.
removed.length = 0;
await vm.runInNewContext(`(${sandbox.exports.repairAppCaches.toString()})('/argus/')`, sandbox);
assert.deepEqual(removed, ['shell']);
if (process.argv.includes('--built')) {
  const html = fs.readFileSync(new URL('../dist/index.html', import.meta.url), 'utf8');
  const bootstrap = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
    .map((match) => match[1]).find((text) => text.includes('argus_identity_purge_'));
  assert.ok(bootstrap, 'built recovery bootstrap exists');
  removed.length = 0;
  let reloads = 0;
  sandbox.localStorage = { getItem: () => 'previous-build' };
  sandbox.sessionStorage = { getItem: () => null, setItem: () => {} };
  sandbox.document = { documentElement: { style: {} } };
  sandbox.location.reload = () => { reloads++; };
  // The local build uses /. Exercise its emitted code with that exact scope.
  sandbox.navigator.serviceWorker.getRegistrations = async () => [
    registration('built-shell', 'https://example.test/', 'sw.js'),
    registration('built-push', 'https://example.test/notifications/', 'sw.js', { endpoint: 'test' }),
  ];
  vm.runInNewContext(bootstrap, sandbox);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(removed, ['built-shell']);
  assert.equal(reloads, 1);
}
console.log('pwa-recovery: shell repaired; push registrations, owner data and other apps preserved');

import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../src/lib/pwaIdentity.ts', import.meta.url), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { deployedPwaIdentity, authenticationOnlyUpdate, deployedEntryScript, deployedIsBehind, identityDiffersOnlyInBuildSha } = await import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`);
const html = mode => `__ARGUS_VERSION__="13.7.51";__ARGUS_PRODUCT_VERSION__="v13.7.51";__ARGUS_BUILD_SHA__="${'a'.repeat(40)}";__ARGUS_OWNER_AUTH_MODE__="${mode}";`;
const off = deployedPwaIdentity(html('0')), on = deployedPwaIdentity(html('1'));
assert.ok(off && on && off !== on);
assert.ok(authenticationOnlyUpdate(off, on)); assert.ok(authenticationOnlyUpdate(on, off));
assert.equal(authenticationOnlyUpdate(on, on), false);
for (const field of ['13.7.51', 'v13.7.51', 'a'.repeat(40)]) assert.equal(authenticationOnlyUpdate(off, on.replace(field, 'different')), false);
for (const invalid of ['', '1', on.slice(0, -2), on + '|extra', on.slice(0, -1) + 'yes']) assert.equal(authenticationOnlyUpdate(off, invalid), false);
for (const invalid of [html('yes'), html(''), html('0') + '__ARGUS_OWNER_AUTH_MODE__="0";', html('1').replace('__ARGUS_OWNER_AUTH_MODE__', 'old_mode'), html('1').replace('13.7.51', 'bad|value')]) assert.equal(deployedPwaIdentity(invalid), null);
// Execute the actual recovery branch, preserving its existing timeout/counter rules.
const main = fs.readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
assert.match(main, /selfHeal\(authenticationOnlyUpdate\(RUNNING_IDENTITY, deployed\)\)/);
assert.match(main, /if \(!preserveSnapshots\) await waitAtMost\(clearVerifiedSnapshotCache\(\), PWA_STEP_TIMEOUT_MS\)/);
assert.match(main, /if \(tries >= 5\) return/);
assert.match(main, /PWA_STEP_TIMEOUT_MS = 12_000/);
assert.match(main, /PWA_RECONCILE_TIMEOUT_MS = 36_000/);
console.log('pwa-identity: setting changes detected, same-code views preserved, malformed metadata refused');

const recovery = main.slice(main.indexOf('async function selfHeal('), main.indexOf('let registeredServiceWorker'));
const executable = ts.transpileModule(recovery.replace('import.meta.env.BASE_URL', "'/argus/'"), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
for (const [running, deployed, clears] of [[off, on, 0], [on, off, 0], [off, on.replace('13.7.51', '13.8.8'), 1]]) {
  const calls = [];
  const sandbox = { repairAppCaches: async base => calls.push(['shell', base]),
    clearVerifiedSnapshotCache: async () => calls.push(['views']),
    waitAtMost: async promise => promise, PWA_STEP_TIMEOUT_MS: 12000 };
  vm.runInNewContext(executable, sandbox);
  await sandbox.selfHeal(authenticationOnlyUpdate(running, deployed));
  assert.equal(calls.filter(call => call[0] === 'shell').length, 1);
  assert.equal(calls.filter(call => call[0] === 'views').length, clears);
}
const broken = { repairAppCaches: async () => { throw new Error('storage_unavailable'); } };
vm.runInNewContext(executable, broken);
await broken.selfHeal(true); // best-effort repair still reaches bounded reload.
console.log('pwa-identity: real repair branch preserves mode-only snapshots; code updates retain existing invalidation');
const startup = main.slice(main.indexOf('const RUNNING ='), main.indexOf('const TRIES_KEY'));
for (const required of [false, true]) {
  const writes = [];
  const sandbox = { __APP_VERSION__: '13.7.51', __PRODUCT_VERSION__: 'v13.7.51', __FRONTEND_BUILD_SHA__: 'a'.repeat(40),
    OWNER_AUTH_REQUIRED: required, __ARGUS_OWNER_AUTH_MODE__: required ? '0' : '1',
    localStorage: { setItem: (...args) => writes.push(args) } };
  vm.runInNewContext(ts.transpileModule(startup, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, sandbox);
  assert.deepEqual(writes, [['argus.bundle.identity', required ? on : off]]);
  sandbox.localStorage.setItem = () => { throw new Error('quota'); };
  vm.runInNewContext(ts.transpileModule(startup, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, { ...sandbox });
}
console.log('pwa-identity: compiled identity recorded before timers, HTML mismatch and unavailable storage cannot forge it');

// 2026-09-30: a served page that is the previous release (an edge not yet
// updated) or the same entry module is not an update; reloading into it only
// dropped the in-memory owner session, for minutes after every release.
const newer = on.replace('13.7.51', '13.8.8'), older = on.replace('13.7.51', '13.7.50'), otherSha = on.replace('a'.repeat(40), 'b'.repeat(40));
assert.equal(deployedIsBehind(on, older), true);
assert.equal(deployedIsBehind(on, newer), false);
assert.equal(deployedIsBehind(on, on.replace('13.7.51', '13.8.8')), false);
assert.equal(deployedIsBehind(on, on.replace('13.7.51', '12.9.99')), true);
assert.equal(deployedIsBehind(on, otherSha), false);
for (const invalid of ['', 'x|y|z|1', on.replace('13.7.51', '13.7'), on.replace('13.7.51', '13.7.5a')]) assert.equal(deployedIsBehind(on, invalid), false);
assert.equal(identityDiffersOnlyInBuildSha(on, otherSha), true);
assert.equal(identityDiffersOnlyInBuildSha(on, on), false);
assert.equal(identityDiffersOnlyInBuildSha(on, off), false); // mode change must reload
assert.equal(identityDiffersOnlyInBuildSha(on, newer), false);
const page = entry => `<!doctype html><script type="module" crossorigin src="/argus/assets/${entry}"></script><link rel="modulepreload" href="/argus/assets/vendor-abc.js">`;
assert.equal(deployedEntryScript(page('index-BNV-iSdr.js')), 'index-BNV-iSdr.js');
assert.equal(deployedEntryScript(page('index-BNV-iSdr.js') + page('index-other.js')), null);
assert.equal(deployedEntryScript('<script src="/argus/assets/vendor-abc.js"></script>'), null);
assert.match(main, /servedPageIsNotAnUpdate\(served, RUNNING_IDENTITY\)/);
assert.match(main, /deployedIsBehind\(running, served\.identity\)/);
assert.match(main, /identityDiffersOnlyInBuildSha\(running, served\.identity\)/);
console.log('pwa-identity: a previous-release edge or the running entry module is not an update');

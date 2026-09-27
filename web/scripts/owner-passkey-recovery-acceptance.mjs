// Real browser credentials.create/get and real server verification, synthetic only.
// Virtual device keys stay inside Chromium; no credential export/token injection.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import { createBrowserOwner, verifiedStoreFingerprint, assertNoSecrets } from './owner-browser-acceptance.mjs';
assert.equal(process.env.ARGUS_SYNTHETIC_OWNER_TODAY, '1');
assert.equal(process.env.ARGUS_BACKEND_URL, 'https://argus-fixture.test');
assert.ok(process.send);
const url = process.env.ARGUS_PUBLIC_URL;
const owner = createBrowserOwner({ baseUrl: process.env.ARGUS_BACKEND_URL, publicUrl: url });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await context.newPage();
const secondContext = await browser.newContext();
const secondPage = await secondContext.newPage();
const cdp = await context.newCDPSession(page);
const report = { status: 'FAIL', syntheticOnly: true, physicalDeviceAccepted: false, checks: [] };
const secrets = new Set([process.env.ARGUS_ACCEPTANCE_OWNER_PASSWORD]);
const collectors = new Set();
for (const observedPage of [page, secondPage]) observedPage.on('response', response => {
  if (!['/api/argus/owner-auth/password', '/api/argus/owner-auth/login-verify'].some(p => response.url().endsWith(p))) return;
  const task = response.json().then(body => { if (body.token) secrets.add(body.token); }).catch(() => {});
  collectors.add(task); task.finally(() => collectors.delete(task));
});
const check = name => report.checks.push(name);
const menu = async () => {
  const details = page.locator('details.owner-access-bar');
  if (!await details.evaluate(node => node.open)) await details.locator('summary').click();
};
const ceremony = async (action, button, status) => {
  const responsePromise = page.waitForResponse(r => r.url().endsWith('/api/argus/owner-auth/' + action)
    && r.request().method() === 'POST', { timeout: 20000 });
  const guarded = responsePromise.catch(() => null);
  await page.getByRole('button', { name: button, exact: true }).click();
  const response = await guarded;
  assert.ok(response, action + '_response'); assert.equal(response.status(), status, action);
  if (status !== 200) {
    await page.getByRole('status').filter({ hasText: '操作を完了できませんでした' }).waitFor();
    await owner.locked(page);
  }
  return response;
};
const register = async () => {
  await menu();
  const response = await ceremony('register-verify', 'パスキーを登録', 200);
  assert.equal((await response.json()).registered, true);
  await page.getByRole('status').filter({ hasText: 'この端末のパスキーを登録しました' }).waitFor();
};
const passkeyLogin = async () => {
  await ceremony('login-verify', 'パスキーで開く', 200);
  await page.locator('.owner-access-bar > summary').waitFor();
  assert.equal(await page.locator('input[type=password]').count(), 0);
};
const control = operation => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error('fixture_control_timeout')), 20000);
  process.once('message', message => { clearTimeout(timer); message.ok ? resolve(message.result) : reject(new Error('fixture_control')); });
  process.send({ operation });
});
let original, originalRows;
report.storageObservations = [];
const rows = () => page.evaluate(async () => {
  const db = await new Promise((resolve, reject) => { const r = indexedDB.open('argus-verified-snapshots'); r.onsuccess = () => resolve(r.result); r.onerror = reject; });
  try {
    const result = {};
    for (const name of db.objectStoreNames) result[name] = await new Promise((resolve, reject) => {
      const r = db.transaction(name).objectStore(name).getAll(); r.onsuccess = () => resolve(r.result); r.onerror = reject;
    });
    return result;
  } finally { db.close(); }
});
function differentPaths(left, right, prefix = '') {
  if (JSON.stringify(left) === JSON.stringify(right)) return [];
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return [prefix];
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  const paths = [...keys].flatMap(key => differentPaths(left[key], right[key], prefix + '/' + key));
  return paths.length ? paths : [prefix + '/key-order'];
}
const preserved = async label => {
  const selector = '[data-argus-contract="canonical-market-snapshot-v1"]';
  await page.waitForFunction(selector => document.querySelector(selector)?.getAttribute('data-canonical-snapshot-id')?.startsWith('vs-'), selector);
  const id = await page.locator(selector).getAttribute('data-canonical-snapshot-id');
  const fingerprint = await verifiedStoreFingerprint(page);
  assert.ok(fingerprint.records > 0);
  const currentRows = await rows();
  if (original) {
    assert.equal(id, original.id);
    const changed = differentPaths(originalRows, currentRows);
    const allowed = ['/drawing-state/0/value/document/generatedAt', '/drawing-state/0/value/storedAt'];
    assert.equal(currentRows['drawing-state'][0].key, 'argus.todayHeadline.cache.v1');
    assert.ok(changed.every(path => allowed.includes(path)), 'unexpected_saved_content_change');
    for (const path of changed) {
      const parts = path.split('/').slice(1);
      const read = object => parts.reduce((value, part) => value[part], object);
      assert.ok(Number.isFinite(Date.parse(read(currentRows))));
      assert.ok(Date.parse(read(currentRows)) >= Date.parse(read(originalRows)));
    }
    assert.equal(fingerprint.records, original.fingerprint.records);
    // Online revalidation legitimately refreshes these two headline timestamps.
    // Every other saved field, including the full verified snapshot, is exact.
    report.storageObservations.push({ label, raw: fingerprint, changedPaths: changed });
  } else { original = { id, fingerprint }; originalRows = currentRows; }
  check(label);
};
try {
  await cdp.send('WebAuthn.enable', { enableUI: false });
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', { options: {
    protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true,
    isUserVerified: true, automaticPresenceSimulation: true,
  } });
  await page.goto(url); await owner.login(page); await preserved('password_snapshot');
  await register(); check('real_attestation_registered');
  await secondPage.goto(url); await owner.login(secondPage); check('second_session_open');
  report.backup = await control('checkpoint');
  await owner.logout(page); await passkeyLogin(); await preserved('real_assertion_snapshot');
  await owner.logout(page);
  await cdp.send('WebAuthn.setResponseOverrideBits', { authenticatorId, isBadUV: true });
  await ceremony('login-verify', 'パスキーで開く', 401); check('missing_uv_rejected');
  await cdp.send('WebAuthn.setResponseOverrideBits', { authenticatorId, isBadUV: false });
  await passkeyLogin(); await preserved('after_invalid_uv');
  await menu(); await page.getByRole('button', { name: '端末紛失・復旧', exact: true }).click();
  await page.getByLabel('復旧用パスワード', { exact: true }).fill(process.env.ARGUS_ACCEPTANCE_OWNER_PASSWORD);
  await ceremony('revoke-all', 'すべての端末を解除', 200);
  await owner.locked(page); check('revoke_all_locked');
  await secondPage.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await owner.locked(secondPage); check('revoke_all_invalidates_second_session');
  await ceremony('login-options', 'パスキーで開く', 401); check('revoked_device_rejected');
  await owner.login(page); await preserved('password_after_revocation');
  await register(); check('replacement_device_registered');
  await owner.logout(page); await passkeyLogin(); await preserved('replacement_device_login');
  report.restore = await control('restore');
  // The open page still holds its old in-memory session; a real API read must reject it.
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await owner.locked(page); check('restored_db_rejects_active_session');
  await ceremony('login-options', 'パスキーで開く', 401); check('historical_keys_not_reactivated');
  await owner.login(page); await preserved('password_after_database_restore');
  await register(); check('restored_database_new_registration');
  await owner.logout(page); await passkeyLogin(); await preserved('restored_database_passkey_login');
  await owner.logout(page); await owner.locked(page); check('final_logout');
  report.saved = original; report.status = 'PASS';
} finally {
  await Promise.allSettled([...collectors]);
  await secondContext.close(); await context.close(); await browser.close();
  // Only fixed check labels, counts and synthetic snapshot hashes leave memory.
  const text = JSON.stringify(report, null, 2) + '\n';
  assert.ok(![...secrets].some(value => text.includes(value)));
  await fs.writeFile(process.env.ARGUS_PASSKEY_OUT, text, { flag: 'wx' });
  await assertNoSecrets(path.dirname(process.env.ARGUS_PASSKEY_OUT), secrets);
  process.disconnect();
}
console.log(`owner-passkey-recovery: ${report.status}; ${report.checks.length} checks`);

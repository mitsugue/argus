// Dedicated synthetic profile; real old production SW and current owner auth.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import { createBrowserOwner, verifiedStoreFingerprint, assertNoSecrets } from './owner-browser-acceptance.mjs';
assert.equal(process.env.ARGUS_SYNTHETIC_OWNER_TODAY, '1');
assert.equal(process.env.ARGUS_PUBLIC_URL, 'https://argus-fixture.test/argus/');
assert.ok(process.send);
const profile = process.env.ARGUS_MIGRATION_PROFILE;
assert.ok(path.basename(profile) === 'profile' && path.basename(path.dirname(profile)).startsWith('argus-owner-today-'));
const owner = createBrowserOwner({ baseUrl: process.env.ARGUS_BACKEND_URL, publicUrl: process.env.ARGUS_PUBLIC_URL });
let context = await chromium.launchPersistentContext(profile, { headless: true, viewport: { width: 390, height: 844 } });
let page = context.pages()[0] || await context.newPage();
const report = { status: 'FAIL', syntheticOnly: true, physicalDeviceAccepted: false, checks: [] };
const secrets = new Set([process.env.ARGUS_ACCEPTANCE_OWNER_PASSWORD]);
const observe = p => p.on('response', async response => {
  if (response.url().endsWith('/api/argus/owner-auth/password')) {
    try { const body = await response.json(); if (body.token) secrets.add(body.token); } catch {}
  }
}); observe(page);
const check = value => report.checks.push(value);
const control = () => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error('fixture_activation_timeout')), 20000);
  process.once('message', message => { clearTimeout(timer); message.ok ? resolve(message.result) : reject(new Error('fixture_activation')); });
  process.send({ operation: 'activate' });
});
const canonical = async () => {
  const selector = '[data-argus-contract="canonical-market-snapshot-v1"]';
  await page.waitForFunction(selector => document.querySelector(selector)?.getAttribute('data-canonical-snapshot-id')?.startsWith('vs-'), selector, { timeout: 30000 });
  return page.locator(selector).getAttribute('data-canonical-snapshot-id');
};
const marker = { key: 'argus.synthetic.migration.drawing', value: { points: [[1, 2], [3, 4]], label: 'saved-drawing' } };
const preservedMarker = async () => {
  const actual = await page.evaluate(async () => {
    const db = await new Promise((resolve, reject) => { const r = indexedDB.open('argus-verified-snapshots'); r.onsuccess = () => resolve(r.result); r.onerror = reject; });
    try {
      const drawing = await new Promise((resolve, reject) => { const r = db.transaction('drawing-state').objectStore('drawing-state').get('argus.synthetic.migration.drawing'); r.onsuccess = () => resolve(r.result); r.onerror = reject; });
      return { drawing, setting: localStorage.getItem('argus.synthetic.migration.settings') };
    } finally { db.close(); }
  });
  assert.deepEqual(actual, { drawing: marker, setting: '{"horizon":"20D","theme":"dark"}' });
};
try {
  await page.goto(process.env.ARGUS_PUBLIC_URL);
  report.snapshotId = await canonical();
  await page.waitForFunction(() => navigator.serviceWorker.controller);
  await page.evaluate(async marker => {
    const db = await new Promise((resolve, reject) => { const r = indexedDB.open('argus-verified-snapshots'); r.onsuccess = () => resolve(r.result); r.onerror = reject; });
    try { await new Promise((resolve, reject) => { const t = db.transaction('drawing-state', 'readwrite'); t.objectStore('drawing-state').put(marker); t.oncomplete = resolve; t.onerror = reject; }); }
    finally { db.close(); }
    localStorage.setItem('argus.synthetic.migration.settings', '{"horizon":"20D","theme":"dark"}');
  }, marker);
  report.before = await verifiedStoreFingerprint(page); assert.ok(report.before.records > 1);
  check('legacy_sw_and_saved_data');
  await context.setOffline(true); await page.reload();
  assert.equal(await canonical(), report.snapshotId); await preservedMarker();
  check('legacy_offline_original_available');
  await context.setOffline(false);
  await control();
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await page.waitForFunction(() => document.documentElement.dataset.argusOwnerAuthMode === '1', null, { timeout: 60000 });
  await owner.locked(page); check('legacy_update_reaches_owner_lock');
  await preservedMarker();
  report.locked = await verifiedStoreFingerprint(page);
  assert.deepEqual(report.locked, report.before); check('all_saved_rows_exact_before_login');
  await owner.login(page); assert.equal(await canonical(), report.snapshotId); await preservedMarker();
  check('normal_login_restores_same_snapshot_and_owner_data');
  await owner.logout(page); await context.close();
  context = await chromium.launchPersistentContext(profile, { headless: true, viewport: { width: 390, height: 844 } });
  page = context.pages()[0] || await context.newPage(); observe(page);
  await context.setOffline(true); await page.goto(process.env.ARGUS_PUBLIC_URL);
  await owner.locked(page); await preservedMarker(); check('reopened_profile_offline_stays_locked_and_preserves_data');
  await context.setOffline(false); await owner.login(page); assert.equal(await canonical(), report.snapshotId);
  await preservedMarker(); check('reopened_profile_online_normal_reauthentication');
  await owner.logout(page); await context.close(); context = null;
  await assertNoSecrets(profile, [...secrets]); check('no_password_or_session_in_profile');
  report.status = 'PASS';
} catch (error) {
  report.failureState = await page.evaluate(() => ({ mode: document.documentElement.dataset.argusOwnerAuthMode,
    visibility: document.documentElement.style.visibility, identity: localStorage.getItem('argus.bundle.identity'),
    controller: Boolean(navigator.serviceWorker.controller), lockButtons: [...document.querySelectorAll('button')].filter(b => b.textContent === 'パスワードで開く').length,
    canonicalVisible: Boolean(document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]')) })).catch(() => ({ pageUnavailable: true }));
  throw error;
} finally {
  if (context) await context.close();
  await fs.writeFile(process.env.ARGUS_MIGRATION_OUT, JSON.stringify(report, null, 2) + '\n');
}
console.log('owner-pwa-migration: PASS');

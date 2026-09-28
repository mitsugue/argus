// Normal UI ceremonies only. Never inject a token/admin header into a page or
// persistence. Credentials and captured session identifiers stay in memory.
import fs from 'node:fs/promises';
import path from 'node:path';
import { readerConfiguration } from './owner-auth-reader.mjs';

export class OwnerBrowserError extends Error {
  constructor(code) { super(`owner_browser:${code}`); this.name = 'OwnerBrowserError'; }
}
const fail = (code) => { throw new OwnerBrowserError(code); };
export const isOwnerCeremony = (url, backend, method) => {
  try {
    const u = new URL(url);
    return u.origin === backend && (method === 'POST'
      && ['/api/argus/owner-auth/password', '/api/argus/owner-auth/logout'].includes(u.pathname)
      || method === 'GET' && u.pathname === '/api/argus/owner-auth/session');
  } catch { return false; }
};
export async function assertNoSecrets(root, secrets) {
  const needles = [...secrets].filter(Boolean).flatMap(value =>
    [...new Set([value, encodeURIComponent(value), JSON.stringify(value).slice(1, -1)])]
      .flatMap(text => [Buffer.from(text), Buffer.from(text, 'utf16le')]));
  const overlap = Math.max(1, ...needles.map(b => b.length)) - 1;
  async function visit(file) {
    const stat = await fs.lstat(file);
    if (stat.isSymbolicLink()) fail('artifact_link');
    if (stat.isDirectory()) {
      for (const name of await fs.readdir(file)) await visit(path.join(file, name));
      return;
    }
    if (!stat.isFile()) fail('artifact_type');
    const handle = await fs.open(file, 'r');
    try {
      const buffer = Buffer.alloc(65536); let previous = Buffer.alloc(0);
      for (;;) {
        const { bytesRead } = await handle.read(buffer, 0, buffer.length, null);
        if (!bytesRead) break;
        const bytes = Buffer.concat([previous, buffer.subarray(0, bytesRead)]);
        if (needles.some(needle => bytes.includes(needle))) fail('artifact_secret');
        previous = Buffer.from(bytes.subarray(Math.max(0, bytes.length - overlap)));
      }
    } finally { await handle.close(); }
  }
  try { await visit(root); } catch (error) {
    if (error instanceof OwnerBrowserError) throw error;
    fail('artifact_read');
  }
}
export function createBrowserOwner({ baseUrl, publicUrl, env = process.env }) {
  const config = readerConfiguration(baseUrl, env);
  if (config.enabled) {
    const publicOrigin = new URL(publicUrl);
    if (publicOrigin.origin !== config.browserOrigin || publicOrigin.username
        || publicOrigin.password) fail('configuration');
  }
  const secrets = new Set(config.enabled ? [config.password] : []);
  let lastAttempt = 0;
  const boundary = page => {
    if (new URL(page.url()).origin !== config.browserOrigin) fail('page_origin');
  };
  async function locked(page) {
    if (!config.enabled) return;
    try {
      boundary(page);
      await page.getByRole('button', { name: 'パスワードで開く', exact: true })
        .waitFor({ state: 'visible', timeout: 15000 });
      if (await page.locator('.nav__mobile, [data-argus-contract="canonical-market-snapshot-v1"]').count()) fail('unlocked_content');
    } catch { fail('lock_required'); }
  }
  async function login(page) {
    if (config.enabled) await locked(page);
    try {
      await page.waitForFunction(() => ['0', '1'].includes(document.documentElement.dataset.argusOwnerAuthMode), { }, { timeout: 15000 });
      const actual = await page.evaluate(() => document.documentElement.dataset.argusOwnerAuthMode);
      if (actual !== (config.enabled ? '1' : '0')) fail('mode_mismatch');
    } catch (error) { if (error instanceof OwnerBrowserError) throw error; fail('mode_unavailable'); }
    if (!config.enabled) return;
    // Respect the existing ten/minute owner-wide limiter. No 429 retries.
    await new Promise(resolve => setTimeout(resolve, Math.max(0, 7000 - (Date.now() - lastAttempt))));
    lastAttempt = Date.now();
    const input = page.getByLabel('復旧用パスワード', { exact: true });
    let responsePromise;
    try {
      boundary(page);
      const controller = page.waitForResponse(response => response.url() === config.backend + '/api/argus/owner-auth/password'
        && response.request().method() === 'POST', { timeout: 15000 });
      responsePromise = controller.catch(() => null);
      await input.fill(config.password);
      await page.getByRole('button', { name: 'パスワードで開く', exact: true }).click();
      const response = await responsePromise;
      // Name the stage and HTTP status (never the body) so a production
      // owner-mode failure is diagnosable from the run log: a 429 means the
      // owner-wide ten-per-minute limiter, not a wrong password.
      if (!response) fail('login_no_response');
      if (response.status() !== 200) fail('login_status_' + response.status());
      const body = await response.json();
      if (typeof body?.token !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(body.token)) fail('login_shape');
      secrets.add(body.token);
      // The product opens this control only after its fresh nonce proof.
      try {
        await page.locator('.owner-access-bar > summary').waitFor({ state: 'visible', timeout: 30000 });
      } catch {
        // Name the page state (fixed codes only, never text the owner typed):
        // the product's own error code, whether the shell header exists,
        // whether the lock screen is still up, and the owner-mode marker.
        const state = await page.evaluate(() => ({
          code: document.querySelector('[role="status"][data-owner-code]')?.getAttribute('data-owner-code') || 'none',
          header: document.querySelector('.shell__header') ? 'header' : 'noheader',
          locked: document.querySelector('.owner-access-screen') ? 'locked' : 'unlocked',
          mode: document.documentElement.dataset.argusOwnerAuthMode || '?',
        })).catch(() => ({ code: 'unreadable', header: '?', locked: '?', mode: '?' }));
        fail(`login_marker:${state.code}:${state.header}:${state.locked}:mode${state.mode}`);
      }
      boundary(page);
    } catch (error) { if (error instanceof OwnerBrowserError) throw error; fail('login'); }
    finally { if (await input.count().catch(() => 0)) await input.fill('', { timeout: 1000 }).catch(() => {}); }
  }
  async function logout(page) {
    if (!config.enabled || page.isClosed()) return;
    let stage = 'boundary';
    try {
      boundary(page);
      const menu = page.locator('details.owner-access-bar');
      if (await menu.count() && !await menu.evaluate(element => element.open)) await menu.locator('summary').click();
      const control = page.getByRole('button', { name: 'ログアウト', exact: true });
      if (!await control.count()) { await locked(page); return; }
      const pending = page.waitForResponse(response => response.url() === config.backend + '/api/argus/owner-auth/logout'
        && response.request().method() === 'POST', { timeout: 15000 }).catch(() => null);
      stage = 'click';
      await control.click();
      stage = 'response';
      const response = await pending;
      if (!response || response.status() !== 200 || (await response.json())?.loggedOut !== true) fail('logout');
      stage = 'nonce';
      const nonce = response.request().headers()['x-argus-owner-nonce'];
      if (!nonce || response.headers()['x-argus-owner-nonce'] !== nonce) fail('logout');
      stage = 'locked';
      await locked(page);
    } catch { fail('logout_' + stage); }
  }
  async function active(page) {
    if (!config.enabled) return;
    try {
      boundary(page);
      if (!await page.locator('.owner-access-bar > summary').count()) fail('session_lost');
    } catch { fail('session_lost'); }
  }
  return { enabled: config.enabled, login, logout, locked, active,
    redact: value => [...secrets].reduce((text, secret) => text.split(secret).join('[redacted]'), String(value ?? '')),
    scan: root => config.enabled ? assertNoSecrets(root, secrets) : Promise.resolve() };
}
// Snapshot only the existing verified store, not browser credentials or payload.
export async function verifiedStoreFingerprint(page) {
  return page.evaluate(async () => {
    const name = 'argus-verified-snapshots';
    if (!(await indexedDB.databases()).some(row => row.name === name)) throw new Error('verified_store_missing');
    const db = await new Promise((resolve, reject) => {
      const req = indexedDB.open(name); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(new Error('store_open'));
    });
    try {
      const rows = [];
      for (const store of [...db.objectStoreNames].sort()) {
        const entries = await new Promise((resolve, reject) => {
          const tx = db.transaction(store, 'readonly'); const req = tx.objectStore(store).getAll();
          tx.oncomplete = () => resolve(req.result); tx.onerror = () => reject(new Error('store_read'));
        });
        rows.push([store, entries]);
      }
      const bytes = new TextEncoder().encode(JSON.stringify(rows));
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(x => x.toString(16).padStart(2, '0')).join('');
      return { hash, records: rows.reduce((n, [, values]) => n + values.length, 0) };
    } finally { db.close(); }
  });
}

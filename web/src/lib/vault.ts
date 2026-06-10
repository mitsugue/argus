// Cloud backup vault (v10.3.4) — fully automatic, zero new accounts.
//
// Flow: the device ENCRYPTS the backup (AES-GCM, key derived from the user's
// passphrase via PBKDF2) → POSTs the ciphertext envelope to the backend relay
// → the daily prediction-ledger workflow commits it to the public `ledger`
// branch (vault/<id>/latest.json). Restore on ANY device = passphrase only:
// the vault id is itself derived from the passphrase, the ciphertext is
// fetched from GitHub and decrypted locally. Plaintext never leaves the
// device; the server and the public repo only ever see ciphertext.
//
// Honest limits: a WEAK passphrase can be brute-forced offline because the
// ciphertext is public — use a long one. Losing the passphrase = no restore.

import { buildBackupPayload, restoreBackup, type BackupFile } from './backup';

const PASS_KEY = 'argus.vaultPass.v1';
const LAST_KEY = 'argus.lastCloudBackup.v1';
const INTERVAL_MS = 20 * 3600 * 1000; // ~daily on first open
const PBKDF2_ITERS = 200_000;
const RAW_BASE = 'https://raw.githubusercontent.com/mitsugue/argus/ledger/ledger/vault';

interface Envelope { v: 1; salt: string; iv: string; ct: string; exportedAt: string; }

const te = new TextEncoder();
const td = new TextDecoder();
const b64 = (buf: ArrayBuffer | Uint8Array) =>
  btoa(String.fromCharCode(...new Uint8Array(buf instanceof Uint8Array ? buf : new Uint8Array(buf))));
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function sha256hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', te.encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Deterministic vault id from the passphrase — the only thing to remember. */
export function vaultIdFrom(pass: string): Promise<string> {
  return sha256hex(`argus-vault-id:${pass}`);
}

async function deriveKey(pass: string, salt: Uint8Array): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey('raw', te.encode(pass), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: salt as BufferSource, iterations: PBKDF2_ITERS, hash: 'SHA-256' },
    base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}

export async function encryptBackup(pass: string, payload: BackupFile): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(pass, salt);
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv as BufferSource }, key, te.encode(JSON.stringify(payload)));
  const env: Envelope = { v: 1, salt: b64(salt), iv: b64(iv), ct: b64(ct), exportedAt: payload.exportedAt };
  return JSON.stringify(env);
}

export async function decryptBackup(pass: string, envelopeStr: string): Promise<BackupFile> {
  const env = JSON.parse(envelopeStr) as Envelope;
  const key = await deriveKey(pass, unb64(env.salt));
  const pt = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: unb64(env.iv) as BufferSource }, key, unb64(env.ct) as BufferSource);
  return JSON.parse(td.decode(pt)) as BackupFile;
}

export function getVaultPass(): string | null {
  try { return localStorage.getItem(PASS_KEY); } catch { return null; }
}
export function setVaultPass(pass: string | null): void {
  try {
    if (pass) localStorage.setItem(PASS_KEY, pass);
    else { localStorage.removeItem(PASS_KEY); localStorage.removeItem(LAST_KEY); }
  } catch { /* ignore */ }
}
export function lastCloudBackupAt(): number {
  try { return Number(localStorage.getItem(LAST_KEY) || 0); } catch { return 0; }
}

/** Push one encrypted envelope to the relay. Returns the backend note. */
export async function cloudBackupNow(pass: string): Promise<string> {
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
  if (!backend) throw new Error('backend not configured');
  const payload = buildBackupPayload(true);
  if (Object.keys(payload.data).length === 0) return '保存するデータがまだありません。';
  const blob = await encryptBackup(pass, payload);
  const vaultId = await vaultIdFrom(pass);
  const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/vault-push', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ vaultId, blob }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  try { localStorage.setItem(LAST_KEY, String(Date.now())); } catch { /* ignore */ }
  const d = await r.json();
  return d.noteJa || 'OK';
}

/** Daily-ish automatic cloud backup on app open (no-op until enabled). */
export async function maybeCloudBackup(): Promise<void> {
  const pass = getVaultPass();
  if (!pass) return;
  if (Date.now() - lastCloudBackupAt() < INTERVAL_MS) return;
  try { await cloudBackupNow(pass); } catch { /* retried next open */ }
}

/** Restore from the cloud vault using only the passphrase. */
export async function cloudRestore(pass: string): Promise<number> {
  const vaultId = await vaultIdFrom(pass);
  const r = await fetch(`${RAW_BASE}/${vaultId}/latest.json?cb=${Date.now()}`);
  if (!r.ok) throw new Error(r.status === 404
    ? 'クラウド上にバックアップが見つかりません(パスフレーズ違い、または初回保存が16:05の台帳ランを未通過)。'
    : `HTTP ${r.status}`);
  const envelopeStr = await r.text();
  const payload = await decryptBackup(pass, envelopeStr);
  return restoreBackup(payload);
}

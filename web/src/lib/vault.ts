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

import { buildBackupPayload, restoreBackup, BACKUP_KEYS, type BackupFile } from './backup';
import { mergeAssets, loadTombstones, saveTombstones, type Tombstones } from './assetMerge';
import type { AssetItem } from '../types/assetItem';

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
  // Own push = already applied locally — the sync loop must not re-apply it.
  setSyncState({ appliedExportedAt: payload.exportedAt });
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

// ── Cross-device sync (sync-v1, v10.10) ─────────────────────────────────────
// Both devices encrypt with the same passphrase → same vault id. Edits are
// debounce-pushed to the backend relay; other devices poll the relay (with a
// one-time GitHub-raw fallback per session) and apply when the remote payload
// is NEWER than their own last local edit. Whole-payload last-writer-wins —
// simultaneous edits on two devices keep the most recent push (v1 limitation,
// per-item merge is a later refinement). Ciphertext-only on the wire, as ever.
const SYNC_KEY = 'argus.vaultSync.v1';        // {appliedExportedAt, pushedEditAt}
const EDIT_KEY = 'argus.lastLocalEditAt.v1';
// v11.3.3 (sync-v2): an edit pushes ~3s after the last change; the other device
// polls every 15s and ALSO pulls immediately on visibilitychange, so switching
// from the app to the web tab surfaces the change right away (~5-20s worst case).
const PUSH_DEBOUNCE_MS = 3_000;
const SYNC_POLL_MS = 15_000;
let pushTimer: number | null = null;
let suppressEditsUntil = 0;
let syncLoopStarted = false;

interface SyncState { appliedExportedAt: string; pushedEditAt: number; }
function syncState(): SyncState {
  try {
    return { appliedExportedAt: '', pushedEditAt: 0,
             ...JSON.parse(localStorage.getItem(SYNC_KEY) || '{}') };
  } catch { return { appliedExportedAt: '', pushedEditAt: 0 }; }
}
function setSyncState(patch: Partial<SyncState>): void {
  try { localStorage.setItem(SYNC_KEY, JSON.stringify({ ...syncState(), ...patch })); }
  catch { /* ignore */ }
}
export function lastLocalEditAt(): number {
  try { return Number(localStorage.getItem(EDIT_KEY) || 0); } catch { return 0; }
}

/** Called by data hooks whenever device data actually changes: stamps the
    edit time and debounce-pushes the encrypted backup so other devices can
    pick it up within ~1 minute. No-op until cloud backup is enabled. */
export function markLocalEdit(): void {
  if (Date.now() < suppressEditsUntil) return;  // change came FROM a sync apply
  try { localStorage.setItem(EDIT_KEY, String(Date.now())); } catch { /* ignore */ }
  const pass = getVaultPass();
  if (!pass) return;
  if (pushTimer != null) window.clearTimeout(pushTimer);
  pushTimer = window.setTimeout(() => {
    pushTimer = null;
    void cloudBackupNow(pass)
      .then(() => setSyncState({ pushedEditAt: lastLocalEditAt() }))
      .catch(() => { /* re-pushed by the next sync tick */ });
  }, PUSH_DEBOUNCE_MS);
}

async function fetchRemoteEnvelope(vaultId: string, rawFallback: boolean): Promise<string | null> {
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
  if (backend) {
    try {
      const r = await fetch(`${backend.replace(/\/$/, '')}/api/argus/vault-relay?vaultId=${vaultId}`);
      if (r.ok) return ((await r.json()) as { blob: string }).blob;
    } catch { /* relay unreachable — maybe raw below */ }
  }
  if (!rawFallback) return null;
  try {
    const r = await fetch(`${RAW_BASE}/${vaultId}/latest.json?cb=${Date.now()}`);
    if (r.ok) return await r.text();
  } catch { /* offline */ }
  return null;
}

// Sync status surfaced to the Guide backup card (診断: なぜ同期しないのか).
const SYNC_INFO_KEY = 'argus.lastSyncInfo.v1';
export interface SyncInfo { at: number; outcome: 'applied' | 'pushed' | 'noop'; merged?: boolean }
function recordSyncTick(outcome: SyncInfo['outcome'], merged: boolean): void {
  try { localStorage.setItem(SYNC_INFO_KEY, JSON.stringify({ at: Date.now(), outcome, merged })); }
  catch { /* ignore */ }
}
export function lastSyncInfo(): SyncInfo | null {
  try { return JSON.parse(localStorage.getItem(SYNC_INFO_KEY) || 'null') as SyncInfo | null; }
  catch { return null; }
}

/** One sync cycle (sync-v2, v11.3.3).
    WATCHLIST (`argus.assets.v1`) is merged PER-ITEM: union by id, newer
    updatedAt wins, deletions propagate via tombstones. Both devices converge
    to the same list — an add on either side survives, no join gate needed,
    nothing is clobbered. Other keys (journal/trades/research) keep the v1
    whole-key LWW with the never-synced-device safety gate. */
export async function cloudSyncNow(opts: { rawFallback?: boolean } = {}): Promise<'applied' | 'pushed' | 'noop'> {
  const pass = getVaultPass();
  if (!pass) return 'noop';
  const vaultId = await vaultIdFrom(pass);
  const env = await fetchRemoteEnvelope(vaultId, opts.rawFallback ?? false);
  const st = syncState();
  const localEdit = lastLocalEditAt();
  let outcome: 'applied' | 'pushed' | 'noop' = 'noop';
  let needPush = false;
  let mergedTick = false;
  if (env) {
    let payload: BackupFile | null = null;
    try { payload = await decryptBackup(pass, env); } catch { payload = null; }
    if (payload?.data) {
      // 1) watchlist: per-item merge — always safe, runs on every cycle.
      const rawRemote = payload.data['argus.assets.v1'];
      const remoteAssets = Array.isArray(rawRemote) ? (rawRemote as AssetItem[]) : [];
      const rawTombs = payload.data['argus.assetTombstones.v1'];
      const remoteTombs = (rawTombs && typeof rawTombs === 'object' ? rawTombs : {}) as Tombstones;
      if (remoteAssets.length > 0 || Object.keys(remoteTombs).length > 0) {
        let localAssets: AssetItem[] = [];
        try { localAssets = JSON.parse(localStorage.getItem('argus.assets.v1') || '[]') as AssetItem[]; }
        catch { localAssets = []; }
        if (!Array.isArray(localAssets)) localAssets = [];
        const m = mergeAssets(localAssets, remoteAssets, loadTombstones(), remoteTombs);
        saveTombstones(m.tombstones);
        mergedTick = true;
        if (m.localChanged) {
          suppressEditsUntil = Date.now() + 3_000;
          try { localStorage.setItem('argus.assets.v1', JSON.stringify(m.items)); } catch { /* ignore */ }
          window.dispatchEvent(new CustomEvent('argus:data-synced'));
          outcome = 'applied';
        }
        if (m.remoteChanged) needPush = true;  // we hold items/deletions the cloud lacks
      }
      // 2) other keys: v1 whole-key LWW + safety gate (assets excluded — merged above).
      if (payload.exportedAt && payload.exportedAt !== st.appliedExportedAt) {
        const remoteTs = Date.parse(payload.exportedAt) || 0;
        let hasLocalData = false;
        try { hasLocalData = !!localStorage.getItem('argus.assets.v1'); } catch { /* ignore */ }
        const everSynced = st.appliedExportedAt !== '' || localEdit > 0;
        if (remoteTs > localEdit && (everSynced || !hasLocalData)) {
          let applied = 0;
          for (const k of BACKUP_KEYS) {
            if (k === 'argus.assets.v1' || k === 'argus.assetTombstones.v1') continue;
            if (payload.data[k] != null) {
              try { localStorage.setItem(k, JSON.stringify(payload.data[k])); applied++; }
              catch { /* ignore */ }
            }
          }
          setSyncState({ appliedExportedAt: payload.exportedAt });
          if (applied > 0) {
            suppressEditsUntil = Date.now() + 3_000;
            window.dispatchEvent(new CustomEvent('argus:data-synced'));
            outcome = 'applied';
          }
        }
      }
    }
  }
  if (needPush || localEdit > st.pushedEditAt) {
    try {
      await cloudBackupNow(pass);
      setSyncState({ pushedEditAt: lastLocalEditAt() });
      if (outcome === 'noop') outcome = 'pushed';
    } catch { /* next tick */ }
  }
  recordSyncTick(outcome, mergedTick);
  return outcome;
}

/** App-start hook: initial sync (with one GitHub-raw fallback), then a gentle
    poll while the tab is visible + an immediate check on tab return. */
export function startCloudSync(): void {
  if (syncLoopStarted) return;
  syncLoopStarted = true;
  void maybeCloudBackup();   // legacy ~20h heartbeat (also covers judgment log)
  void cloudSyncNow({ rawFallback: true });
  window.setInterval(() => { if (!document.hidden) void cloudSyncNow(); }, SYNC_POLL_MS);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void cloudSyncNow();
  });
}

/** Restore from the cloud vault using only the passphrase. Tries the live
    relay first (sync-v1: works minutes after the other device pushed, no
    need to wait for the 16:05 ledger commit), then the durable GitHub copy. */
export async function cloudRestore(pass: string): Promise<number> {
  const vaultId = await vaultIdFrom(pass);
  const envelopeStr = await fetchRemoteEnvelope(vaultId, true);
  if (!envelopeStr) {
    throw new Error('クラウド上にバックアップが見つかりません(パスフレーズ違い、または他端末がまだ一度も送信していません)。');
  }
  const payload = await decryptBackup(pass, envelopeStr);
  const n = restoreBackup(payload);
  // Joining the sync group: record what we applied so the loop doesn't
  // re-apply it, and let mounted hooks reload without a manual refresh.
  setSyncState({ appliedExportedAt: payload.exportedAt });
  suppressEditsUntil = Date.now() + 3_000;
  window.dispatchEvent(new CustomEvent('argus:data-synced'));
  return n;
}

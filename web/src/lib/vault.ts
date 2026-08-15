// Read-only encrypted recovery for envelopes produced by the former cloud
// backup path. The public browser can fetch an existing ciphertext envelope
// from the relay or durable ledger copy and decrypt it locally. It cannot
// upload a new envelope, retry a failed upload, or provide live device sync.
// New recovery points are created with the local JSON export instead.
//
// Honest limits: a WEAK passphrase can be brute-forced offline because the
// ciphertext is public — use a long one. Losing the passphrase = no restore.

import { restoreBackup, BACKUP_KEYS, type BackupFile } from './backup';
import { mergeAssets, loadTombstones, saveTombstones, type Tombstones } from './assetMerge';
import type { AssetItem } from '../types/assetItem';
import { buildRecoveryDurability, type RecoveryDurability } from '../domain/recoveryDurability';

const PASS_KEY = 'argus.vaultPass.v1';
const LAST_KEY = 'argus.lastCloudBackup.v1';
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

function recordExistingEnvelope(exportedAt: string): void {
  const timestamp = Date.parse(exportedAt || '') || 0;
  if (!timestamp) return;
  try { localStorage.setItem(LAST_KEY, String(timestamp)); } catch { /* ignore */ }
}

// ── Read-only encrypted recovery ─────────────────────────────────────────────
// The static browser has no authenticated cloud-push channel. It can read an
// existing encrypted envelope on startup/tab return and can restore it, but it
// never uploads, retries an upload, or advertises live cross-device sync.
const SYNC_KEY = 'argus.vaultSync.v1';        // {appliedExportedAt, pushedEditAt}
const EDIT_KEY = 'argus.lastLocalEditAt.v1';
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

export function recoveryDurability(hasLocalData: boolean, lastLocalExportAt?: number | null): RecoveryDurability {
  return buildRecoveryDurability({
    hasLocalData,
    existingEnvelopeAt: lastCloudBackupAt() || null,
    lastLocalEditAt: lastLocalEditAt() || null,
    lastLocalExportAt,
  });
}

/** Called by data hooks whenever device data changes. This only records the
    local LWW timestamp; unavailable browser-side cloud push is never retried. */
export function markLocalEdit(): void {
  if (Date.now() < suppressEditsUntil) return;  // change came FROM a sync apply
  try { localStorage.setItem(EDIT_KEY, String(Date.now())); } catch { /* ignore */ }
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
export interface SyncInfo {
  at: number; outcome: 'applied' | 'pushed' | 'noop'; merged?: boolean;
  /** v11.3.4 diagnostics */
  lastPullAppliedAt?: number; lastPushAt?: number;
  remoteProtocol?: number; legacyClientDetected?: boolean;
}
function recordSyncTick(patch: Partial<SyncInfo> & { outcome: SyncInfo['outcome'] }): void {
  try {
    const prev = lastSyncInfo() || ({} as SyncInfo);
    localStorage.setItem(SYNC_INFO_KEY, JSON.stringify({ ...prev, ...patch, at: Date.now() }));
  } catch { /* ignore */ }
}
export function lastSyncInfo(): SyncInfo | null {
  try { return JSON.parse(localStorage.getItem(SYNC_INFO_KEY) || 'null') as SyncInfo | null; }
  catch { return null; }
}

/** One read/apply cycle for an existing sync-v2 envelope.
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
  let mergedTick = false;
  let remoteProto: number | undefined;
  let legacy = false;
  if (env) {
    let payload: BackupFile | null = null;
    try { payload = await decryptBackup(pass, env); } catch { payload = null; }
    if (payload?.data) {
      recordExistingEnvelope(payload.exportedAt);
      // v11.3.4 migration guard: a RECENT envelope without syncProtocolVersion
      // means another device still runs pre-sync-v2 code (whole-payload LWW,
      // no tombstones). The merge below stays safe on THIS device; the UI
      // warns the owner to reload the old app/tab.
      remoteProto = payload.syncProtocolVersion ?? 1;
      const remoteTsRaw = Date.parse(payload.exportedAt || '') || 0;
      legacy = remoteProto < 2 && remoteTsRaw > Date.now() - 48 * 3600_000;
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
        // m.remoteChanged is intentionally not uploaded: public browser push is unavailable.
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
  recordSyncTick({
    outcome, merged: mergedTick,
    ...(outcome === 'applied' ? { lastPullAppliedAt: Date.now() } : {}),
    ...(remoteProto !== undefined ? { remoteProtocol: remoteProto, legacyClientDetected: legacy } : {}),
  });
  return outcome;
}

/** App-start hook: one raw-fallback pull and a pull when the tab returns.
    Deliberately no 15-second polling loop and no cloud-push retry. */
export function startCloudSync(): void {
  if (syncLoopStarted) return;
  syncLoopStarted = true;
  void cloudSyncNow({ rawFallback: true });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void cloudSyncNow();
  });
}

/** Restore from an existing encrypted envelope using only the passphrase.
    Tries the read-only relay first, then the durable GitHub copy. */
export async function cloudRestore(pass: string): Promise<number> {
  const vaultId = await vaultIdFrom(pass);
  const envelopeStr = await fetchRemoteEnvelope(vaultId, true);
  if (!envelopeStr) {
    throw new Error('クラウド上にバックアップが見つかりません(パスフレーズ違い、または他端末がまだ一度も送信していません)。');
  }
  const payload = await decryptBackup(pass, envelopeStr);
  recordExistingEnvelope(payload.exportedAt);
  const n = restoreBackup(payload);
  // Record what was applied so a later visibility pull does not re-apply it,
  // and let mounted hooks reload without a manual refresh.
  setSyncState({ appliedExportedAt: payload.exportedAt });
  suppressEditsUntil = Date.now() + 3_000;
  window.dispatchEvent(new CustomEvent('argus:data-synced'));
  return n;
}

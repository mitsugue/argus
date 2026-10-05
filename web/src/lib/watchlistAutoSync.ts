import type { AssetItem } from '../types/assetItem';

export const OWNER_SYNC_TOKEN_KEY = 'argus.ownerSyncToken.v1';
const ASSETS_KEY = 'argus.assets.v1';
const PREFIX = 'argus.watchlist-pending.v1.';
const SCHEMA = 'watchlist-changes-v1';
const MARKETS = new Set(['JP', 'US', 'CRYPTO']);
const EVENT = 'argus:watchlist-sync-state';
const WAKE_EVENT = 'argus:watchlist-sync-wake';
type Item = { symbol: string; market: string; name?: string };
type Change = { action: 'add' | 'remove'; item: Item };
type Batch = { id: string; createdAt: number; committed: boolean; changes: Change[] };
type QueueEntry = { key: string; raw: string; batch: Batch };
export type SyncState = { kind: 'idle' | 'pending' | 'saving' | 'saved' | 'error' | 'auth_required' | 'unavailable'; message: string };
let state: SyncState = { kind: 'idle', message: '' };
let running = false;
export function watchlistSyncState(): SyncState { return state; }
export function setWatchlistSyncState(next: SyncState): void {
  state = next;
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event(EVENT));
  }
}
export function subscribeWatchlistSync(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
const keyOf = (item: Item) => `${item.market}:${item.symbol.trim().toUpperCase()}`;
function membership(assets: AssetItem[]): Map<string, Item> {
  if (!Array.isArray(assets)) throw Error('端末の登録銘柄を確認できません');
  const result = new Map<string, Item>();
  for (const a of assets) {
    if (!MARKETS.has(a.market) || !a.enabled) continue;
    if (typeof a.symbol !== 'string' || !a.symbol.trim()) throw Error('端末の登録銘柄を確認できません');
    const item: Item = { symbol: a.symbol.trim(), market: a.market };
    const name = a.displayNameJa || a.displayName;
    if (name) item.name = name.slice(0, 48);
    result.set(keyOf(item), item);
  }
  return result;
}
export function registrationChanges(before: AssetItem[], after: AssetItem[]): Change[] {
  const old = membership(before), next = membership(after);
  return [
    ...[...old].filter(([key]) => !next.has(key)).map(([, item]) => ({ action: 'remove' as const, item })),
    ...[...next].filter(([key]) => !old.has(key)).map(([, item]) => ({ action: 'add' as const, item })),
  ];
}
// One immutable key per operation batch: acknowledgements never replace a
// shared array and cannot erase a new edit or another tab's pending batch.
function nextBatchTime(): number {
  let latest = Date.now() - 1;
  for (const entry of queue(localStorage)) latest = Math.max(latest, entry.batch.createdAt);
  return Math.max(Date.now(), latest + 1);
}
export function stageRegistrationChanges(before: AssetItem[], after: AssetItem[], restoredKeys: ReadonlySet<string> = new Set()): string | null {
  const changes = registrationChanges(before, after).filter(change => !restoredKeys.has(keyOf(change.item)));
  if (!changes.length) return null;
  const id = crypto.randomUUID();
  const key = PREFIX + id;
  const batch: Batch = { id, createdAt: nextBatchTime(), committed: false, changes };
  localStorage.setItem(key, JSON.stringify(batch)); // must succeed BEFORE assets persist
  setWatchlistSyncState({ kind: 'pending', message: '登録銘柄の変更を保存待ちです' });
  return key;
}
export function commitRegistrationChanges(key: string | null): void {
  if (!key) return;
  const batch = JSON.parse(localStorage.getItem(key) || 'null') as Batch | null;
  if (!batch) throw Error('登録変更の記録を確認できません');
  localStorage.setItem(key, JSON.stringify({ ...batch, committed: true }));
  setWatchlistSyncState({ kind: 'pending', message: '登録銘柄の変更を保存待ちです' });
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event(WAKE_EVENT));
  }
}
export function cancelStagedRegistration(key: string | null): void {
  if (key) localStorage.removeItem(key);
}
function queue(storage: Storage): QueueEntry[] {
  const entries: QueueEntry[] = [];
  for (let n = 0; n < storage.length; n++) {
    const key = storage.key(n);
    if (!key?.startsWith(PREFIX)) continue;
    const raw = storage.getItem(key);
    if (!raw) continue;
    const batch = JSON.parse(raw) as Batch;
    if (!batch || PREFIX + batch.id !== key || !/^[0-9a-f-]{36}$/.test(batch.id)
      || !Number.isFinite(batch.createdAt) || typeof batch.committed !== 'boolean'
      || !Array.isArray(batch.changes) || !batch.changes.length || batch.changes.length > 200
      || batch.changes.some(c => !c || !['add', 'remove'].includes(c.action)
        || !c.item || !MARKETS.has(c.item.market) || typeof c.item.symbol !== 'string'
        || !c.item.symbol.trim() || c.item.symbol.length > 24
        || Object.keys(c).some(k => !['action', 'item'].includes(k))
        || Object.keys(c.item).some(k => !['symbol', 'market', 'name'].includes(k)))) {
      throw Error('未送信の登録変更を確認できません');
    }
    entries.push({ key, raw, batch });
  }
  return entries.sort((a, b) => a.batch.createdAt - b.batch.createdAt || a.key.localeCompare(b.key));
}
export function queueManualRegistrations(): void {
  const assets = JSON.parse(localStorage.getItem(ASSETS_KEY) || 'null') as AssetItem[];
  const changes = [...membership(assets).values()].map(item => ({ action: 'add' as const, item }));
  if (!changes.length) return;
  const id = crypto.randomUUID();
  localStorage.setItem(PREFIX + id, JSON.stringify({ id, createdAt: nextBatchTime(), committed: true, changes }));
}
function assertLocalCommit(entries: QueueEntry[], storage: Storage): void {
  const assets = JSON.parse(storage.getItem(ASSETS_KEY) || 'null') as AssetItem[];
  const local = membership(assets);
  const expected = new Map<string, boolean>();
  for (const entry of entries) {
    // If a crash interrupted the local two-step save, only a matching local
    // state proves the change persisted. Otherwise hold, never infer deletion.
    if (!entry.batch.committed && entry.batch.changes.some(c =>
      local.has(keyOf(c.item)) !== (c.action === 'add'))) {
      throw Error('端末の保存が完了していません。登録銘柄を確認してください');
    }
    for (const c of entry.batch.changes) expected.set(keyOf(c.item), c.action === 'add');
  }
  for (const [key, present] of expected) {
    if (local.has(key) !== present) throw Error('復元後の登録銘柄と未送信の変更が異なります。確認が必要です');
  }
}
interface SyncOptions { storage?: Storage; fetcher?: typeof fetch; locks?: LockManager; }
export async function flushWatchlistChanges(backend: string, token: string, options: SyncOptions = {}): Promise<SyncState> {
  if (running) return { kind: 'pending', message: '保存中です。追加の変更は保存待ちです' };
  const storage = options.storage || localStorage;
  let entries: QueueEntry[];
  try { entries = queue(storage); } catch {
    const next: SyncState = { kind: 'error', message: '未送信の登録変更を確認できません。元の記録を保持しています' };
    setWatchlistSyncState(next); return next;
  }
  if (!entries.length) return { kind: 'idle', message: '' };
  if (!backend || !token.trim()) {
    const next: SyncState = { kind: 'auth_required', message: '登録銘柄は端末に保存済みです。自動同期には合言葉の設定が必要です' };
    setWatchlistSyncState(next); return next;
  }
  const locks = options.locks || (typeof navigator !== 'undefined' ? navigator.locks : undefined);
  if (!locks) {
    const next: SyncState = { kind: 'unavailable', message: 'このブラウザでは自動同期を保留しています。端末の登録銘柄は保持しています' };
    setWatchlistSyncState(next); return next;
  }
  const fetcher = options.fetcher || fetch;
  running = true;
  try {
    await locks.request('argus-membership-send-v1', { ifAvailable: true }, async lock => {
      if (!lock) { setWatchlistSyncState({ kind: 'pending', message: '別の画面で保存中です。変更は保存待ちです' }); return; }
      // Bounded drain. The lifecycle will resume the rest, without losing edits.
      for (let sent = 0; sent < 3; sent++) {
        entries = queue(storage);
        if (!entries.length) break;
        assertLocalCommit(entries, storage);
        const entry = entries[0];
        setWatchlistSyncState({ kind: 'saving', message: '登録銘柄の変更を保存しています' });
        let accepted = false;
        for (let retry = 0; retry < 3 && !accepted; retry++) {
          const base = backend.replace(/\/$/, '');
          const read = await fetcher(base + '/api/argus/calibration/watchlist-membership', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ownerToken: token.trim() }), signal: AbortSignal.timeout(30000),
          });
          const current = await read.json();
          if (!read.ok || !['ok', 'empty'].includes(current?.status)
            || typeof current.version !== 'string' || !/^(absent|[0-9a-f]{40})$/.test(current.version)) {
            throw Error(read.status === 401 ? '合言葉を確認してください。変更は保存待ちのまま残しています'
              : '保存先を読み込めません。変更は保存待ちのまま残しています');
          }
          const response = await fetcher(base + '/api/argus/calibration/watchlist-sync', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ownerToken: token.trim(), syncMode: SCHEMA,
              baseVersion: current.version, batchId: entry.batch.id, changes: entry.batch.changes }),
            signal: AbortSignal.timeout(60000),
          });
          if (response.status === 409) continue; // refresh the version, retain SAME batch id
          const saved = await response.json();
          if (!response.ok || saved?.ok !== true || saved.status !== 'synced'
            || saved.batchId !== entry.batch.id || !/^[0-9a-f]{40}$/.test(saved.version || '')) {
            throw Error('保存を確認できません。変更は保存待ちのまま残しています');
          }
          // The server returns success only after reading back the exact saved
          // private commit, including its receipt. A lost reply is safe to retry.
          if (storage.getItem(entry.key) !== entry.raw) throw Error('保存中の登録変更を確認できません');
          storage.removeItem(entry.key);
          accepted = true;
        }
        if (!accepted) throw Error('別の端末の変更を確認中です。保存待ちの変更は保持しています');
      }
      setWatchlistSyncState(queue(storage).length
        ? { kind: 'pending', message: '残りの登録変更を保存待ちです' }
        : { kind: 'saved', message: '登録銘柄の変更を保存しました' });
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : '';
    setWatchlistSyncState(message.startsWith('合言葉')
      ? { kind: 'auth_required', message }
      : { kind: 'error', message: message.startsWith('端末') || message.startsWith('復元後') ? message
        : '保存を確認できません。変更は端末に残し、再接続時に確認します' });
  } finally { running = false; }
  return state;
}
export function startWatchlistAutoSync(backend: string): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let retryAt = 0;
  let failures = 0;
  const wake = () => {
    if (stopped) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (stopped || Date.now() < retryAt || document.visibilityState === 'hidden' || !navigator.onLine) return;
      let token = '';
      try { token = localStorage.getItem(OWNER_SYNC_TOKEN_KEY) || ''; } catch { return; }
      void flushWatchlistChanges(backend, token).then(next => {
        failures = next.kind === 'error' ? failures + 1 : 0;
        retryAt = failures ? Date.now() + Math.min(300000, 30000 * 2 ** Math.min(failures - 1, 4)) : 0;
      });
    }, 1500);
  };
  window.addEventListener(WAKE_EVENT, wake);
  window.addEventListener('online', wake);
  document.addEventListener('visibilitychange', wake);
  const interval = setInterval(wake, 30000);
  wake();
  return () => { stopped = true; clearTimeout(timer); clearInterval(interval);
    window.removeEventListener(WAKE_EVENT, wake); window.removeEventListener('online', wake);
    document.removeEventListener('visibilitychange', wake); };
}

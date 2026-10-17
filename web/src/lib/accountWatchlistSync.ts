// Registration sync uses the existing owner session and durable server store.
import type { AssetItem } from '../types/assetItem';
import { hasOwnerSession, OWNER_AUTH_REQUIRED } from './ownerSession';
import { setWatchlistSyncState } from './watchlistAutoSync';
export const ACCOUNT_ASSETS_KEY = 'argus.assets.v1';
const PREFIX = 'argus.account-watchlist-pending.v1.';
const APPLY = 'argus.account-watchlist-apply.v1';
const BASELINE = 'argus.account-watchlist-baseline.v1';
const JOINED = 'argus.account-watchlist-joined.v1';
const WAKE = 'argus:account-watchlist-wake';
type Operation = { kind: 'add' | 'import'; asset: AssetItem }
  | { kind: 'remove'; id: string }
  | { kind: 'update'; id: string; set: Partial<AssetItem>; unset: string[] };
type Batch = { batchId: string; operations: Operation[]; committed: boolean;
  before: AssetItem[]; after: AssetItem[]; createdAt: number };
type State = { revision: number; initialized: boolean; assets: AssetItem[]; deleted: string[]; batchId?: string };
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const immutable = new Set(['id', 'createdAt', 'market', 'symbol']);
export function registrationOperations(before: AssetItem[], after: AssetItem[]): Operation[] {
  const old = new Map(before.map(a => [a.id, a]));
  const ids = new Set(after.map(a => a.id));
  const operations: Operation[] = before.filter(a => !ids.has(a.id)).map(a => ({ kind: 'remove', id: a.id }));
  for (const asset of after) {
    const previous = old.get(asset.id);
    if (!previous) { operations.push({ kind: 'add', asset }); continue; }
    const changed: Partial<AssetItem> = {};
    const unset: string[] = [];
    for (const key of new Set([...Object.keys(previous), ...Object.keys(asset)])) {
      if (immutable.has(key)) continue;
      const field = key as keyof AssetItem;
      if (equal(previous[field], asset[field])) continue;
      if (asset[field] === undefined) unset.push(key);
      else Object.assign(changed, { [key]: asset[field] });
    }
    if (Object.keys(changed).length || unset.length) operations.push({ kind: 'update', id: asset.id, set: changed, unset });
  }
  return operations;
}
function wake() { window.dispatchEvent(new Event(WAKE)); }
let lastQueuedAt = 0;
function enqueue(operations: Operation[], before: AssetItem[], after: AssetItem[], committed: boolean, initialize = false): string | null {
  if (!operations.length && !initialize) return null;
  for (let i = 0; i < localStorage.length; i++) {
    const existing = localStorage.key(i);
    if (existing?.startsWith(PREFIX)) lastQueuedAt = Math.max(lastQueuedAt,
      Number((JSON.parse(localStorage.getItem(existing)!) as Batch).createdAt) || 0);
  }
  lastQueuedAt = Math.max(Date.now(), lastQueuedAt + 1);
  const batchId = crypto.randomUUID();
  const key = PREFIX + batchId;
  localStorage.setItem(key, JSON.stringify({ batchId, operations, before, after, committed, createdAt: lastQueuedAt }));
  return key;
}
export function stageAccountRegistrations(before: AssetItem[], after: AssetItem[]): string | null {
  if (!OWNER_AUTH_REQUIRED) return null;
  const key = enqueue(registrationOperations(before, after), before, after, false);
  if (key) setWatchlistSyncState({ kind: 'pending', message: '登録銘柄の変更を端末に保持・サーバーへの保存待ち' });
  return key;
}
export function commitAccountRegistrations(key: string | null) {
  if (!key) return;
  const raw = localStorage.getItem(key);
  if (!raw) throw Error('pending_missing');
  const batch = JSON.parse(raw) as Batch;
  batch.committed = true;
  localStorage.setItem(key, JSON.stringify(batch));
  wake();
}
export function cancelAccountRegistrations(key: string | null) { if (key) localStorage.removeItem(key); }
function localAssets(): AssetItem[] {
  const parsed: unknown = JSON.parse(localStorage.getItem(ACCOUNT_ASSETS_KEY) || '[]');
  if (!Array.isArray(parsed) || parsed.some(a => !a || typeof a.id !== 'string')) throw Error('local_invalid');
  return parsed;
}
function pending(): { key: string; raw: string; batch: Batch }[] {
  const result: { key: string; raw: string; batch: Batch }[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key?.startsWith(PREFIX)) continue;
    const raw = localStorage.getItem(key)!;
    const batch = JSON.parse(raw) as Batch;
    if (!batch || !Array.isArray(batch.operations) || key !== PREFIX + batch.batchId) throw Error('pending_invalid');
    if (!batch.committed) {
      // Journal precedes local write; only exact before/after proves the crash window.
      const local = localAssets();
      if (equal(local, batch.after)) commitAccountRegistrations(key);
      else if (equal(local, batch.before)) { cancelAccountRegistrations(key); i--; continue; }
      else throw Error('local_commit_uncertain');
    }
    result.push({ key, raw: localStorage.getItem(key)!, batch: { ...batch, committed: true } });
  }
  return result.sort((a, b) => a.batch.createdAt - b.batch.createdAt || a.key.localeCompare(b.key));
}
function state(value: unknown): State {
  const s = value as State;
  if (!s || !Number.isSafeInteger(s.revision) || s.revision < 0 || typeof s.initialized !== 'boolean'
    || !Array.isArray(s.assets) || s.assets.length > 50 || !Array.isArray(s.deleted)
    || s.assets.some(a => !a || typeof a.id !== 'string' || typeof a.symbol !== 'string'
      || typeof a.enabled !== 'boolean' || typeof a.sortOrder !== 'number')
    || s.deleted.some(id => typeof id !== 'string')) throw Error('server_invalid');
  return s;
}
function migrate(remote: State) {
  if (localStorage.getItem(JOINED)) return;
  const local = localAssets();
  const operations: Operation[] = local.filter(a => !remote.initialized || a.updatedAt > 0)
    .map(asset => ({ kind: 'import', asset }));
  enqueue(operations, local, local, true, !remote.initialized);
  localStorage.setItem(JOINED, '1');
}
function recoverRemoteApply() {
  const raw = localStorage.getItem(APPLY);
  if (!raw) return;
  const saved = JSON.parse(raw) as { before: string | null; after: string };
  const current = localStorage.getItem(ACCOUNT_ASSETS_KEY);
  if (current === saved.after) localStorage.setItem(BASELINE, saved.after);
  else if (current !== saved.before) throw Error('remote_apply_uncertain');
  localStorage.removeItem(APPLY);
}
async function requestState(url: string, body?: object, fetcher: typeof fetch = fetch): Promise<State> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetcher(url, { method: body ? 'POST' : 'GET', cache: 'no-store',
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
      signal: controller.signal });
    if (response.status === 409) throw Error('revision_conflict');
    if (!response.ok) throw Error('server_unavailable');
    const received = state(await response.json());
    // A previously shared account disappearing is a storage failure, not an intentional empty list.
    if (localStorage.getItem(BASELINE) && !received.initialized) throw Error('server_state_reset');
    if (!hasOwnerSession()) throw Error('owner_session_changed');
    return received;
  } finally { clearTimeout(timeout); }
}
let running: Promise<void> | null = null;
export function syncAccountRegistrations(backend: string, fetcher: typeof fetch = fetch): Promise<void> {
  if (running) return running;
  const current = (async () => {
    if (!hasOwnerSession()) throw Error('owner_auth_required');
    recoverRemoteApply();
    const baseline = localStorage.getItem(BASELINE);
    if (baseline && !pending().length) {
      const previous = JSON.parse(baseline) as AssetItem[];
      const local = localAssets();
      enqueue(registrationOperations(previous, local), previous, local, true);
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/owner-auth/watchlist';
    let remote = await requestState(url, undefined, fetcher);
    migrate(remote);
    for (let count = 0; count < 10; count++) {
      const entry = pending()[0];
      if (!entry) break;
      setWatchlistSyncState({ kind: 'saving', message: '登録銘柄をサーバーに保存中' });
      let saved = false;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const received = await requestState(url, { revision: remote.revision,
            batchId: entry.batch.batchId, operations: entry.batch.operations }, fetcher);
          if (received.batchId !== entry.batch.batchId) throw Error('receipt_invalid');
          remote = received;
          if (localStorage.getItem(entry.key) !== entry.raw) throw Error('pending_changed');
          localStorage.removeItem(entry.key); saved = true; break;
        } catch (error) {
          if (!(error instanceof Error) || error.message !== 'revision_conflict') throw error;
          remote = await requestState(url, undefined, fetcher);
        }
      }
      if (!saved) throw Error('concurrent_changes');
    }
    if (pending().length) { wake(); return; }
    const before = localStorage.getItem(ACCOUNT_ASSETS_KEY);
    const after = JSON.stringify(remote.assets);
    if (before !== after) {
      if (pending().length || localStorage.getItem(ACCOUNT_ASSETS_KEY) !== before) return;
      localStorage.setItem(APPLY, JSON.stringify({ before, after }));
      localStorage.setItem(ACCOUNT_ASSETS_KEY, after);
      localStorage.setItem(BASELINE, after);
      localStorage.removeItem(APPLY);
      window.dispatchEvent(new Event('argus:data-synced'));
    }
    localStorage.setItem(BASELINE, after);
    setWatchlistSyncState({ kind: 'saved', message: '登録銘柄・並び順はサーバーに保存済み' });
  })().finally(() => { if (running === current) running = null; });
  running = current;
  return current;
}
export function startAccountWatchlistSync(backend: string) {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout>;
  let failures = 0;
  const ready = () => !stopped && hasOwnerSession() && document.visibilityState === 'visible' && navigator.onLine;
  const schedule = (delay = 1200) => { clearTimeout(timer); if (!stopped) timer = setTimeout(run, delay); };
  const run = async () => {
    if (!ready()) return;
    try { await syncAccountRegistrations(backend); failures = 0; }
    catch {
      failures++;
      if (!stopped) setWatchlistSyncState({ kind: 'error',
        message: 'サーバーへの保存・反映を確認できません。端末の記録を保持して再試行します' });
    }
    if (ready()) schedule(Math.min(300_000, 30_000 * 2 ** failures));
  };
  const onWake = () => schedule();
  window.addEventListener(WAKE, onWake);
  window.addEventListener('argus:data-synced', onWake);
  window.addEventListener('online', onWake);
  window.addEventListener('argus:reload', onWake);
  window.addEventListener('storage', onWake);
  const onVisibility = () => {
    clearTimeout(timer);
    if (ready()) schedule(30_000); // 復帰は全取得の再開ではなく通常間隔を待つ。
  };
  document.addEventListener('visibilitychange', onVisibility);
  schedule(0);
  return () => { stopped = true; clearTimeout(timer);
    window.removeEventListener(WAKE, onWake); window.removeEventListener('argus:data-synced', onWake);
    window.removeEventListener('online', onWake); window.removeEventListener('argus:reload', onWake); window.removeEventListener('storage', onWake);
    document.removeEventListener('visibilitychange', onVisibility); };
}

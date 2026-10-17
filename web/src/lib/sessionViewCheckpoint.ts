import { readDrawingState, writeDrawingState } from './verifiedSnapshot';

// One bounded encrypted view record in the existing device database. This is
// not an authentication source, owner vault, provider store or market history.
// The caller may prepare it only after the fresh server session verification.
const KEY = 'argus-session-view-v1';
const SCHEMA = 'argus-session-view-v1';
const MAX_BYTES = 4 * 1024 * 1024;
const MAX_ENTRIES = 64;
const MAX_SESSION_MS = 86_401_000;
const READ_DEADLINE_MS = 1500;
export type ViewSessionBinding = {
  token: string; expiresAt: number; build: string; backendOrigin: string;
};
type Envelope = {
  schema: typeof SCHEMA; build: string; backendOrigin: string;
  expiresAt: number; savedAt: number; iv: string; ciphertext: string;
};
type Storage = {
  read: (key: string) => Promise<unknown>;
  write: (key: string, value: unknown) => Promise<boolean>;
};
const encode = (bytes: Uint8Array) => {
  let text = '';
  for (let offset = 0; offset < bytes.length; offset += 8192)
    text += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(text);
};
const decode = (text: string) => Uint8Array.from(atob(text), char => char.charCodeAt(0));
const keyValid = (key: unknown): key is string =>
  typeof key === 'string' && key.length > 0 && key.length <= 4096 && !/[\u0000-\u001f]/.test(key);
function serialize(value: unknown) {
  return JSON.stringify(value, (_key, item) => {
    if (typeof item === 'number' && !Number.isFinite(item)
      || ['function', 'symbol', 'bigint'].includes(typeof item)) throw Error('view_not_json');
    return item;
  });
}
function context(binding: ViewSessionBinding) {
  return JSON.stringify([SCHEMA, binding.build, binding.backendOrigin, binding.expiresAt]);
}
function associatedData(binding: ViewSessionBinding, savedAt: number) {
  return new TextEncoder().encode(JSON.stringify([context(binding), savedAt]));
}
async function derive(binding: ViewSessionBinding) {
  const input = await crypto.subtle.importKey('raw', new TextEncoder().encode(binding.token), 'HKDF', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'HKDF', hash: 'SHA-256',
    salt: new TextEncoder().encode(SCHEMA), info: new TextEncoder().encode(context(binding)) },
  input, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}
function validBinding(binding: ViewSessionBinding) {
  try {
    const origin = new URL(binding.backendOrigin);
    return /^[A-Za-z0-9_-]{32,128}$/.test(binding.token)
      && typeof binding.build === 'string' && binding.build.length > 0 && binding.build.length <= 160
      && binding.backendOrigin === origin.origin && origin.protocol === 'https:'
      && Number.isFinite(binding.expiresAt) && binding.expiresAt > Date.now()
      && binding.expiresAt <= Date.now() + MAX_SESSION_MS;
  } catch { return false; }
}

/** Storage can be substituted in isolated tests; production uses the existing
 * drawing-state database accessor without adding a database or object store.
 */
export function createSessionViewCheckpoint(storage: Storage = {
  read: key => readDrawingState<unknown>(key, null), write: writeDrawingState,
}) {
  let binding: ViewSessionBinding | null = null;
  let entries = new Map<string, unknown>();
  let restored = new Set<string>();
  let generation = 0;
  let writeFlight: Promise<boolean> | null = null;
  let dirty = false;
  let status = 'idle'; // fixed diagnostics; no key, token, view or exception
  const listeners = new Map<string, Set<(value: unknown) => void>>();
  function clearMemory() {
    generation += 1; binding = null; entries = new Map(); restored = new Set(); dirty = false;
    status = 'cleared';
  }
  async function prepare(verified: ViewSessionBinding, recover: boolean) {
    clearMemory();
    if (!validBinding(verified)) { status = 'binding_rejected'; return false; }
    const epoch = generation;
    binding = { ...verified };
    if (!recover) { status = 'new_view'; return false; }
    try {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const timeout = Symbol('storage_timeout');
      const result = await Promise.race([storage.read(KEY), new Promise<symbol>(resolve => {
        timer = setTimeout(() => resolve(timeout), READ_DEADLINE_MS);
      })]).finally(() => clearTimeout(timer));
      if (result === timeout) { status = 'storage_timeout'; return false; }
      const value = result as Envelope | null;
      if (!value) { status = 'absent'; return false; }
      if (value.savedAt > Date.now()) { status = 'saved_time_ahead'; return false; }
      status = 'envelope_rejected';
      if (!value || value.schema !== SCHEMA || value.build !== verified.build
        || value.backendOrigin !== verified.backendOrigin || value.expiresAt !== verified.expiresAt
        || !Number.isFinite(value.savedAt) || value.savedAt > Date.now() || value.savedAt < verified.expiresAt - MAX_SESSION_MS
        || typeof value.iv !== 'string' || value.iv.length > 32
        || typeof value.ciphertext !== 'string' || value.ciphertext.length > Math.ceil((MAX_BYTES + 16) / 3) * 4)
        return false;
      const iv = decode(value.iv); if (iv.byteLength !== 12) return false;
      status = 'decrypt_rejected';
      const raw = await crypto.subtle.decrypt({ name: 'AES-GCM', iv,
        additionalData: associatedData(verified, value.savedAt) }, await derive(verified), decode(value.ciphertext));
      if (raw.byteLength > MAX_BYTES) return false;
      const decoded: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw));
      status = 'content_rejected';
      if (!Array.isArray(decoded) || decoded.length > MAX_ENTRIES
        || !decoded.every(row => Array.isArray(row) && row.length === 2 && keyValid(row[0]))
        || new Set(decoded.map(row => row[0])).size !== decoded.length) return false;
      if (epoch !== generation || !binding || binding.expiresAt <= Date.now()) return false;
      entries = new Map(decoded); restored = new Set(entries.keys());
      status = entries.size ? 'restored' : 'empty';
      for (const [key, value] of entries) for (const apply of listeners.get(key) ?? []) apply(value);
      return entries.size > 0;
    } catch { return false; }
  }
  function keep(key: string, value: unknown) {
    if (!binding || binding.expiresAt <= Date.now() || !keyValid(key)) return false;
    try {
      const text = serialize(value);
      if (typeof text !== 'string' || new TextEncoder().encode(text).byteLength > MAX_BYTES) return false;
      const next = new Map(entries); next.set(key, JSON.parse(text));
      if (next.size > MAX_ENTRIES || new TextEncoder().encode(serialize([...next])).byteLength > MAX_BYTES) return false;
      entries = next; dirty = true; return true;
    } catch { return false; }
  }
  async function writeCurrent() {
    if (!dirty || !binding || binding.expiresAt <= Date.now()) return false;
    const verified = { ...binding }, epoch = generation;
    const bytes = new TextEncoder().encode(serialize([...entries]));
    if (bytes.byteLength > MAX_BYTES) return false;
    dirty = false;
    const iv = crypto.getRandomValues(new Uint8Array(12));
    try {
      const savedAt = Date.now();
      const raw = await crypto.subtle.encrypt({ name: 'AES-GCM', iv,
        additionalData: associatedData(verified, savedAt) }, await derive(verified), bytes);
      if (epoch !== generation || !binding || binding.expiresAt <= Date.now()) return false;
      const envelope: Envelope = { schema: SCHEMA, build: verified.build, backendOrigin: verified.backendOrigin,
        expiresAt: verified.expiresAt, savedAt, iv: encode(iv), ciphertext: encode(new Uint8Array(raw)) };
      const saved = await storage.write(KEY, envelope);
      if (!saved && epoch === generation) dirty = true;
      return saved;
    } catch { if (epoch === generation) dirty = true; return false; }
  }
  function flush(): Promise<boolean> {
    if (writeFlight) return writeFlight;
    writeFlight = (async () => {
      let saved = false;
      // One in-flight write; a concurrent update is written next, not dropped
      // or allowed to overwrite a later state with an earlier ciphertext.
      while (dirty && binding && binding.expiresAt > Date.now()) {
        if (!await writeCurrent()) return false;
        saved = true;
      }
      return saved;
    })().finally(() => { writeFlight = null; });
    return writeFlight;
  }
  function bind(key: string, apply: (value: unknown) => void) {
    if (!keyValid(key)) throw Error('view_key_invalid');
    const group = listeners.get(key) ?? new Set(); group.add(apply); listeners.set(key, group);
    if (restored.has(key)) apply(entries.get(key));
    return () => { group.delete(apply); if (!group.size) listeners.delete(key); };
  }
  return { prepare, keep, flush, bind, clearMemory,
    diagnostic: () => ({ status, restoredEntries: restored.size }),
    hasRestored: (key: string) => restored.has(key),
    restoredValue: (key: string) => restored.has(key) ? entries.get(key) : undefined };
}
export const sessionViewCheckpoint = createSessionViewCheckpoint();

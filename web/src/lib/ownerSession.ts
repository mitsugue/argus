// The bearer lives in memory and, in the home-screen app only, so a
// pull-to-refresh or relaunch inside the same app session does not lock the
// owner out (owner request 2026-10-02), in sessionStorage: a full quit ends
// it, an app update does not. An ordinary browser tab keeps
// it in memory only, so a browser profile on disk never holds a credential
// (the release acceptance scans its profile for it and stopped every Pages
// acceptance from 13.8.2 on). Never attach it to another origin, redirects,
// logs, URLs, localStorage, IndexedDB or the legacy owner vault.
export const OWNER_AUTH_REQUIRED = import.meta.env.VITE_ARGUS_OWNER_AUTH_REQUIRED === '1';
const base = String(import.meta.env.VITE_ARGUS_BACKEND_URL ?? '').replace(/\/$/, '');
const prefix = '/api/argus/owner-auth/';
let token = '';
let expiresAt = 0;
let ceremonyEpoch = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
// Owner reads still on the wire. Logout cancels them first so none reaches the
// server after its session is gone (a stray 401 after logout, 2026-10-02).
const inflight = new Set<AbortController>();
// Server sessions last 24 hours (argus_owner_auth.TTL); anything longer is rejected.
const MAX_SESSION_MS = 86_401_000;
const STORE_KEY = 'argus.owner.session.v1';
const buildId = () => {
  try { return typeof __FRONTEND_BUILD_SHA__ === 'string' && __FRONTEND_BUILD_SHA__ ? __FRONTEND_BUILD_SHA__
    : typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : 'unknown'; } catch { return 'unknown'; }
};
const anyStore = () => { try { return typeof sessionStorage === 'undefined' ? null : sessionStorage; } catch { return null; } };
const installedApp = () => {
  try {
    // The manifest asks for fullscreen first and standalone as the fallback;
    // iOS home-screen apps also report navigator.standalone.
    return ['standalone', 'fullscreen'].some((mode) => window.matchMedia?.(`(display-mode: ${mode})`).matches === true)
      || (navigator as Navigator & { standalone?: boolean }).standalone === true;
  } catch { return false; }
};
/** Where a login may be kept across a reload: the home-screen app's session storage, nowhere else. */
const store = () => installedApp() ? anyStore() : null;
const listeners = new Set<() => void>();
export const subscribeOwner = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
export const hasOwnerSession = () => !!token && expiresAt > Date.now();
// Why an active session ended, as a fixed code plus at most an API path, so a
// release acceptance that finds the lock screen can say what caused it. Never
// a credential, a query string or a response body.
const lockPath = (url: URL) => url.pathname.replace(/[^A-Za-z0-9/_-]/g, '').slice(0, 80);
function recordLock(reason: string) {
  try { document.documentElement.dataset.argusOwnerLock = reason; } catch { /* no document */ }
}
export function clearOwnerSession(reason: unknown = 'cleared') {
  if (token) recordLock(typeof reason === 'string' ? reason : 'cleared');
  ceremonyEpoch += 1;
  token = ''; expiresAt = 0; clearTimeout(timer);
  try { anyStore()?.removeItem(STORE_KEY); } catch { /* storage unavailable */ }
  listeners.forEach((fn) => fn());
}
function setSession(value: { token?: unknown; expiresAt?: unknown }) {
  if (typeof value.token !== 'string' || value.token.length < 32
      || typeof value.expiresAt !== 'number' || value.expiresAt <= Date.now()
      || value.expiresAt > Date.now() + MAX_SESSION_MS) throw new Error('authentication_failed');
  token = value.token; expiresAt = value.expiresAt;
  try {
    const kept = store();
    if (kept) kept.setItem(STORE_KEY, JSON.stringify({ token, expiresAt, build: buildId() }));
    else anyStore()?.removeItem(STORE_KEY);
  } catch { /* memory only */ }
  clearTimeout(timer); timer = setTimeout(() => clearOwnerSession('expired'), expiresAt - Date.now());
  listeners.forEach((fn) => fn());
}

export function installOwnerTransport() {
  if (!OWNER_AUTH_REQUIRED) return;
  const backend = new URL(base || window.location.origin);
  if (backend.protocol !== 'https:' || backend.pathname !== '/' || backend.search || backend.hash) {
    throw new Error('owner_backend_configuration_invalid');
  }
  const original = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const req = new Request(input, init);
    const url = new URL(req.url);
    if (url.origin !== backend.origin || !url.pathname.startsWith('/api/')) return original(req);
    const authRoute = url.pathname.startsWith(prefix);
    const capturedToken = token;
    if (!authRoute && !hasOwnerSession()) {
      clearOwnerSession('expired');
      throw new Error('owner_auth_required');
    }
    const headers = new Headers(req.headers);
    const loginRoute = ['password', 'login-options', 'login-verify'].some((name) => url.pathname === prefix + name);
    // A verification request that already names its own session (a new login
    // while one is still active) keeps its credential and nonce.
    const explicit = authRoute && req.headers.has('X-ARGUS-OWNER-SESSION');
    const nonce = hasOwnerSession() && !loginRoute && !explicit ? crypto.randomUUID() : '';
    if (nonce) {
      headers.set('X-ARGUS-OWNER-SESSION', token);
      headers.set('X-ARGUS-OWNER-NONCE', nonce);
    }
    // Errors on redirects prevent disclosure of the custom credential header.
    const cancel = new AbortController();
    const onAbort = () => cancel.abort();
    if (req.signal.aborted) cancel.abort(); else req.signal.addEventListener('abort', onAbort, { once: true });
    if (!authRoute) inflight.add(cancel);
    let response: Response;
    try {
      response = await original(new Request(req, { headers, cache: 'no-store', redirect: 'error', signal: cancel.signal }));
    } finally {
      inflight.delete(cancel);
      req.signal.removeEventListener('abort', onAbort);
    }
    if (!authRoute && (capturedToken !== token || !hasOwnerSession())) {
      throw new Error('owner_session_changed');
    }
    // A prior Service Worker can ignore request cache policy. A unique server
    // echo proves that this response passed the session boundary for this read.
    // Only a successful body needs that proof: an error without the echo (a
    // proxy 502/503 during a restart, a busy auth store) says nothing about
    // the session, so it fails this request without locking the owner out
    // (2026-10-02: such errors kept returning the owner to the lock screen).
    if (nonce && response.headers.get('X-ARGUS-OWNER-NONCE') !== nonce) {
      if (response.ok && token === capturedToken) clearOwnerSession('response_unverified:' + lockPath(url));
      throw new Error(response.ok ? 'owner_response_unverified' : 'owner_backend_unavailable');
    }
    if (!authRoute && response.status === 401) clearOwnerSession('response_401:' + lockPath(url));
    return response;
  };
  let validating = false;
  const validate = async () => {
    if (document.hidden || !token || validating) return;
    if (!hasOwnerSession()) { clearOwnerSession('expired'); return; }
    validating = true;
    const captured = token;
    try {
      const response = await window.fetch(base + prefix + 'session', {
        cache: 'no-store', signal: AbortSignal.timeout(10_000),
      });
      // Only a definite loss of the session locks the app. A throttled or
      // unavailable backend (429, 5xx) or a network error is retried at the
      // next tick; server-side expiry still applies and the offline listener
      // covers loss of network. 2026-09-30: the shared per-address request
      // budget answered this ping with 429 during the release acceptance and
      // every page locked itself mid-flow; an owner behind a congested
      // connection saw the same lock screen.
      if (response.status === 401 && token === captured) clearOwnerSession('session_check_401');
    } catch { /* transient: keep the session until a definite answer */ }
    finally { validating = false; }
  };
  window.setInterval(() => { void validate(); }, 30_000);
  document.addEventListener('visibilitychange', () => { void validate(); });
  // A reload or an app switch keeps the session (sessionStorage ends with the
  // app); a definite 401, logout, revoke or expiry still locks immediately.
}

function savedSession(): { token?: unknown; expiresAt?: unknown; build?: unknown } | null {
  try { return JSON.parse(store()?.getItem(STORE_KEY) ?? 'null'); } catch { return null; }
}
/** A login kept by this app session that a reload can try to resume (no network). */
export const hasSavedOwnerSession = () => {
  if (!OWNER_AUTH_REQUIRED) return false;
  const saved = savedSession();
  return !!saved && typeof saved.expiresAt === 'number' && saved.expiresAt > Date.now();
};
// 2026-10-04 (owner: a pull-to-refresh still sometimes opened the lock
// screen): any failed check used to delete the saved login, so a timeout or a
// 503 while the server restarted after a release or was busy recalculating
// ended the session. Only a definite rejection ends it now; an unreachable or
// busy server is retried for up to a minute.
const RESTORE_RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 8000, 10000, 10000, 10000];
const RESTORE_DEADLINE_MS = 60_000;

/** Resume this app session's login after a reload or an app update, only after a fresh server echo. */
export async function restoreOwnerSession(): Promise<boolean> {
  if (!OWNER_AUTH_REQUIRED || hasOwnerSession()) return hasOwnerSession();
  const saved = savedSession();
  // 2026-10-02: an app update no longer ends the login; frequent releases
  // returned the owner to the lock screen every time. The server still
  // verifies the session (nonce echo) and its 24-hour expiry applies.
  if (!saved || typeof saved.expiresAt !== 'number' || saved.expiresAt <= Date.now()) {
    try { anyStore()?.removeItem(STORE_KEY); } catch { /* storage unavailable */ }
    return false;
  }
  // One epoch for every attempt: a sign-in the owner starts meanwhile cancels
  // the resume instead of the resume cancelling the sign-in.
  const epoch = ++ceremonyEpoch;
  const deadline = Date.now() + RESTORE_DEADLINE_MS;
  for (let attempt = 0; ; attempt += 1) {
    try { await verifyAndSetSession(saved, epoch); return true; }
    catch (error) {
      const reason = error instanceof Error ? error.message : 'unknown';
      if (reason === 'authentication_failed') {
        try { anyStore()?.removeItem(STORE_KEY); } catch { /* storage unavailable */ }
        return false;
      }
      if (reason !== 'session_check_unavailable') return hasOwnerSession();
      const delay = RESTORE_RETRY_DELAYS_MS[Math.min(attempt, RESTORE_RETRY_DELAYS_MS.length - 1)];
      if (Date.now() + delay > deadline || (saved.expiresAt as number) <= Date.now() + delay) return false;
      await new Promise((resolve) => setTimeout(resolve, delay));
      if (epoch !== ceremonyEpoch) return hasOwnerSession();
    }
  }
}

async function action(name: string, body: unknown = {}) {
  const response = await fetch(base + prefix + name, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), cache: 'no-store', redirect: 'error',
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(response.status === 429 ? 'try_later' : 'authentication_failed');
  return response.json();
}
async function verifyAndSetSession(value: { token?: unknown; expiresAt?: unknown }, epoch: number) {
  if (typeof value.token !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(value.token)
      || typeof value.expiresAt !== 'number' || value.expiresAt <= Date.now()
      || value.expiresAt > Date.now() + MAX_SESSION_MS) throw new Error('authentication_failed');
  // Do not publish provisional credentials: an old SW may replay a cached login.
  // Only a fresh server echo can unlock existing device-local results.
  const nonce = crypto.randomUUID();
  let response: Response;
  try {
    response = await fetch(base + prefix + 'session', {
      headers: { 'X-ARGUS-OWNER-SESSION': value.token, 'X-ARGUS-OWNER-NONCE': nonce },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(10_000),
    });
  } catch { throw new Error('session_check_unavailable'); }
  // Only the server's own 401/403 or its explicit "not authenticated" is a
  // rejection. A timeout, a 429/5xx or an unechoed body (an old Service
  // Worker's replay) says nothing about the session.
  if (response.status === 401 || response.status === 403) throw new Error('authentication_failed');
  if (!response.ok || response.headers.get('X-ARGUS-OWNER-NONCE') !== nonce) throw new Error('session_check_unavailable');
  let body: { authenticated?: unknown } | null = null;
  try { body = await response.json(); } catch { throw new Error('session_check_unavailable'); }
  if (body?.authenticated !== true) throw new Error('authentication_failed');
  if (epoch !== ceremonyEpoch || navigator.onLine === false) throw new Error('authentication_cancelled');
  setSession(value);
}
export async function passwordLogin(password: string) {
  const epoch = ++ceremonyEpoch;
  await verifyAndSetSession(await action('password', { password }), epoch);
}
export async function logoutOwner() {
  // Capture the logout request while credentials are present, then immediately
  // close the UI even if the network is unavailable. Server expiry still applies.
  inflight.forEach((controller) => controller.abort()); inflight.clear();
  const pending = action('logout'); clearOwnerSession('logout'); await pending;
}
export async function revokeOwnerDevices(password: string) {
  await action('revoke-all', { password }); clearOwnerSession('revoked');
}
function decode(value: string): ArrayBuffer {
  const binary = atob(value.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(binary, (c) => c.charCodeAt(0)).buffer;
}
function encode(value: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
export async function useOwnerPasskey(register: boolean) {
  const epoch = ++ceremonyEpoch;
  const start = await action(register ? 'register-options' : 'login-options');
  const options = start.publicKey;
  options.challenge = decode(options.challenge);
  if (options.user) options.user.id = decode(options.user.id);
  for (const key of ['excludeCredentials', 'allowCredentials']) {
    if (options[key]) options[key] = options[key].map((entry: { id: string }) => ({ ...entry, id: decode(entry.id) }));
  }
  const credential = (register
    ? await navigator.credentials.create({ publicKey: options })
    : await navigator.credentials.get({ publicKey: options })) as PublicKeyCredential | null;
  if (!credential) throw new Error('authentication_cancelled');
  const common = { id: credential.id, rawId: encode(credential.rawId), type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults() };
  // WebAuthn fields are prototype properties, not enumerable object entries.
  const r = credential.response;
  const response = register ? {
    clientDataJSON: encode(r.clientDataJSON),
    attestationObject: encode((r as AuthenticatorAttestationResponse).attestationObject),
    transports: (r as AuthenticatorAttestationResponse).getTransports?.() ?? [],
  } : {
    clientDataJSON: encode(r.clientDataJSON),
    authenticatorData: encode((r as AuthenticatorAssertionResponse).authenticatorData),
    signature: encode((r as AuthenticatorAssertionResponse).signature),
    userHandle: (r as AuthenticatorAssertionResponse).userHandle
      ? encode((r as AuthenticatorAssertionResponse).userHandle!) : null,
  };
  const result = await action(register ? 'register-verify' : 'login-verify', {
    challengeId: start.challengeId, credential: { ...common, response },
  });
  if (!register) await verifyAndSetSession(result, epoch);
}

// Short-lived bearer state is memory-only. Never attach it to another origin,
// redirects, logs, URLs, localStorage, IndexedDB or the legacy owner vault.
export const OWNER_AUTH_REQUIRED = import.meta.env.VITE_ARGUS_OWNER_AUTH_REQUIRED === '1';
const base = String(import.meta.env.VITE_ARGUS_BACKEND_URL ?? '').replace(/\/$/, '');
const prefix = '/api/argus/owner-auth/';
let token = '';
let expiresAt = 0;
let ceremonyEpoch = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();
export const subscribeOwner = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
export const hasOwnerSession = () => !!token && expiresAt > Date.now();
export function clearOwnerSession() {
  ceremonyEpoch += 1;
  token = ''; expiresAt = 0; clearTimeout(timer);
  listeners.forEach((fn) => fn());
}
function setSession(value: { token?: unknown; expiresAt?: unknown }) {
  if (typeof value.token !== 'string' || value.token.length < 32
      || typeof value.expiresAt !== 'number' || value.expiresAt <= Date.now()
      || value.expiresAt > Date.now() + 1_801_000) throw new Error('authentication_failed');
  token = value.token; expiresAt = value.expiresAt;
  clearTimeout(timer); timer = setTimeout(clearOwnerSession, expiresAt - Date.now());
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
      clearOwnerSession();
      throw new Error('owner_auth_required');
    }
    const headers = new Headers(req.headers);
    const loginRoute = ['password', 'login-options', 'login-verify'].some((name) => url.pathname === prefix + name);
    const nonce = hasOwnerSession() && !loginRoute ? crypto.randomUUID() : '';
    if (nonce) {
      headers.set('X-ARGUS-OWNER-SESSION', token);
      headers.set('X-ARGUS-OWNER-NONCE', nonce);
    }
    // Errors on redirects prevent disclosure of the custom credential header.
    const response = await original(new Request(req, { headers, cache: 'no-store', redirect: 'error' }));
    if (!authRoute && (capturedToken !== token || !hasOwnerSession())) {
      throw new Error('owner_session_changed');
    }
    // A prior Service Worker can ignore request cache policy. A unique server
    // echo proves that this response passed the session boundary for this read.
    if (nonce && response.headers.get('X-ARGUS-OWNER-NONCE') !== nonce) {
      if (token === capturedToken) clearOwnerSession();
      throw new Error('owner_response_unverified');
    }
    if (!authRoute && response.status === 401) clearOwnerSession();
    return response;
  };
  let validating = false;
  const validate = async () => {
    if (document.hidden || !token || validating) return;
    if (!hasOwnerSession()) { clearOwnerSession(); return; }
    validating = true;
    const captured = token;
    try {
      const response = await window.fetch(base + prefix + 'session', {
        cache: 'no-store', signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok && token === captured) clearOwnerSession();
    } catch { if (token === captured) clearOwnerSession(); }
    finally { validating = false; }
  };
  window.setInterval(() => { void validate(); }, 30_000);
  document.addEventListener('visibilitychange', () => { void validate(); });
  window.addEventListener('pagehide', clearOwnerSession);
  window.addEventListener('offline', clearOwnerSession);
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
      || value.expiresAt > Date.now() + 1_801_000) throw new Error('authentication_failed');
  // Do not publish provisional credentials: an old SW may replay a cached login.
  // Only a fresh server echo can unlock existing device-local results.
  const nonce = crypto.randomUUID();
  const response = await fetch(base + prefix + 'session', {
    headers: { 'X-ARGUS-OWNER-SESSION': value.token, 'X-ARGUS-OWNER-NONCE': nonce },
    cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok || response.headers.get('X-ARGUS-OWNER-NONCE') !== nonce
      || (await response.json())?.authenticated !== true) throw new Error('authentication_failed');
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
  const pending = action('logout'); clearOwnerSession(); await pending;
}
export async function revokeOwnerDevices(password: string) {
  await action('revoke-all', { password }); clearOwnerSession();
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

// Server-side acceptance only. Secrets stay in this process; no browser/profile
// injection, files, URLs, or admin privilege substitution for owner acceptance.
import { randomUUID } from 'node:crypto';

const PREFIX = '/api/argus/owner-auth/';
export class OwnerReaderError extends Error {
  constructor(code) { super(`owner_reader:${code}`); this.name = 'OwnerReaderError'; }
}
const fail = (code) => { throw new OwnerReaderError(code); };
function origin(value) {
  let url;
  try { url = new URL(value); } catch { fail('configuration'); }
  if (url.protocol !== 'https:' || url.username || url.password
      || url.pathname !== '/' || url.search || url.hash) fail('configuration');
  return url.origin;
}
export function readerConfiguration(baseUrl, env = process.env) {
  const mode = env.ARGUS_ACCEPTANCE_OWNER_AUTH || '0';
  if (!['0', '1'].includes(mode)) fail('configuration');
  if (mode === '0') return { enabled: false };
  const backend = origin(baseUrl);
  const browserOrigin = origin(env.ARGUS_ACCEPTANCE_OWNER_ORIGIN);
  const password = env.ARGUS_ACCEPTANCE_OWNER_PASSWORD;
  if (typeof password !== 'string' || !password || password.length > 1024) fail('configuration');
  return { enabled: true, backend, browserOrigin, password };
}

export async function createOwnerReader({ baseUrl, env = process.env,
  fetchImpl = fetch, now = () => Date.now(), nonce = randomUUID,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
  const config = readerConfiguration(baseUrl, env);
  if (!config.enabled) return { enabled: false, fetch: fetchImpl, close: async () => {} };
  let token = '', expiresAt = 0, closed = false;
  async function send(url, init = {}) {
    try {
      const response = await fetchImpl(url, { ...init, redirect: 'error', cache: 'no-store',
        signal: init.signal || AbortSignal.timeout(15_000) });
      if (response.redirected || response.status >= 300 && response.status < 400) fail('redirect');
      if (response.url && new URL(response.url).origin !== config.backend) fail('redirect');
      return response;
    } catch (error) {
      if (error instanceof OwnerReaderError) throw error;
      // Transport messages can contain custom headers/passwords. Never retain
      // message, stack, cause, request options or response body in diagnostics.
      fail('transport');
    }
  }
  async function json(response) {
    try { return await response.json(); } catch { fail('body'); }
  }
  async function authenticated(url, init = {}) {
    if (!token || expiresAt <= now()) fail('session_expired');
    const challenge = nonce();
    if (!/^[0-9a-f-]{36}$/i.test(challenge)) fail('nonce');
    const headers = new Headers(init.headers);
    if (headers.has('X-ARGUS-ADMIN-TOKEN') || headers.has('Authorization')) fail('privilege');
    headers.set('X-ARGUS-OWNER-SESSION', token);
    headers.set('X-ARGUS-OWNER-NONCE', challenge);
    const response = await send(url, { ...init, headers });
    if ([401, 403].includes(response.status)) fail('rejected');
    if (response.headers.get('X-ARGUS-OWNER-NONCE') !== challenge) fail('unverified');
    return response;
  }
  async function logout() {
    if (!token) return;
    try {
      const response = await authenticated(config.backend + PREFIX + 'logout', {
        method: 'POST', headers: { Origin: config.browserOrigin, 'Content-Type': 'application/json' },
        body: '{}',
      });
      if (response.status !== 200 || (await json(response))?.loggedOut !== true) fail('logout');
    } finally { token = ''; expiresAt = 0; }
  }
  async function login() {
    const response = await send(config.backend + PREFIX + 'password', {
      method: 'POST', headers: { Origin: config.browserOrigin, 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: config.password }),
    });
    if (response.status !== 200) fail('login');
    const body = await json(response);
    if (typeof body?.token !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(body.token)
        || !Number.isSafeInteger(body.expiresAt) || body.expiresAt <= now()
        || body.expiresAt > now() + 86_401_000) fail('session_shape');
    token = body.token; expiresAt = body.expiresAt;
    const proof = await authenticated(config.backend + PREFIX + 'session');
    if (proof.status !== 200 || (await json(proof))?.authenticated !== true) fail('session_proof');
  }
  async function close() {
    closed = true;
    try { await logout(); } finally { config.password = ''; }
  }
  try {
    // A 502/503/504 here is the backend being swapped by a later merge's
    // deploy (2026-09-30: 13.7.84's acceptance met #575's restart and failed
    // owner_reader:boundary). The browser reader already waits out a cutover;
    // this reader waits the same way, at most three times, and still requires
    // the exact 401 owner_auth_required boundary before any credential is sent.
    let unauthenticated = await send(config.backend + PREFIX + 'session');
    for (let cutover = 0; [502, 503, 504].includes(unauthenticated.status) && cutover < 3; cutover += 1) {
      await sleep(20_000);
      unauthenticated = await send(config.backend + PREFIX + 'session');
    }
    if (unauthenticated.status !== 401
        || (await json(unauthenticated))?.error !== 'owner_auth_required') fail('boundary');
    await login();
  } catch (error) {
    try { await close(); } catch { fail('initialization_and_logout'); }
    throw error;
  }
  return {
    enabled: true,
    async fetch(input, init = {}) {
      if (closed) fail('closed');
      let url;
      try { url = new URL(input); } catch { fail('target'); }
      if (url.origin !== config.backend || url.username || url.password || url.hash
          || !url.pathname.startsWith('/api/argus/') || url.pathname.startsWith(PREFIX)
          || (init.method || 'GET').toUpperCase() !== 'GET' || init.body != null) fail('target');
      // Proactive renewal only; no credential retry after a server rejection.
      if (expiresAt - now() < 30_000) { await logout(); await login(); }
      return authenticated(url.href, init);
    },
    close,
  };
}

export async function withOwnerReader(options, callback) {
  const reader = await createOwnerReader(options);
  let result, failure;
  try { result = await callback(reader); } catch (error) { failure = error; }
  try { await reader.close(); } catch { fail(failure ? 'operation_and_logout' : 'logout'); }
  if (failure) throw failure;
  return result;
}

// No credentials or business body: compare release configuration before work.
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
export class OwnerModeError extends Error {
  constructor(code) { super(`owner_mode:${code}`); this.name = 'OwnerModeError'; }
}
const fail = code => { throw new OwnerModeError(code); };
export function ownerMode(value) {
  if (value !== '0' && value !== '1') fail('configuration');
  return value;
}
export function assertModes({ frontend, reader, server }) {
  for (const value of [frontend, reader, server]) ownerMode(value);
  if (frontend !== reader || server !== reader) fail('mismatch');
  return { status: 'PASS', mode: reader };
}
export function htmlOwnerMode(html, expectedSha) {
  if (!/^[a-f0-9]{40}$/.test(expectedSha || '')) fail('identity');
  const modes = [...html.matchAll(/globalThis\.__ARGUS_OWNER_AUTH_MODE__\s*=\s*"([^"]*)"\s*;/g)];
  const shas = [...html.matchAll(/globalThis\.__ARGUS_BUILD_SHA__\s*=\s*"([^"]*)"\s*;/g)];
  if (modes.length !== 1) fail('frontend_marker');
  if (shas.length !== 1 || shas[0][1] !== expectedSha) fail('identity');
  return ownerMode(modes[0][1]);
}
function secureUrl(raw) {
  let url; try { url = new URL(raw); } catch { fail('configuration'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) fail('configuration');
  return url;
}
export async function verifyOwnerModes({ publicUrl, baseUrl, expectedSha, mode, fetchImpl = fetch }) {
  ownerMode(mode);
  const frontendUrl = secureUrl(publicUrl), backend = secureUrl(baseUrl);
  if (backend.pathname !== '/') fail('configuration');
  const nonce = randomUUID();
  frontendUrl.searchParams.set('owner-mode-probe', nonce);
  const serverUrl = new URL('/api/argus/owner-auth/session', backend);
  serverUrl.searchParams.set('owner-mode-probe', nonce);
  async function get(url) {
    try {
      const r = await fetchImpl(url.href, { redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(15000) });
      if (r.redirected || r.status >= 300 && r.status < 400 || r.url && new URL(r.url).origin !== url.origin) fail('redirect');
      return r;
    } catch (e) { if (e instanceof OwnerModeError) throw e; fail('transport'); }
  }
  const front = await get(frontendUrl);
  if (front.status !== 200) fail('frontend_http');
  let html; try { html = await front.text(); } catch { fail('frontend_body'); }
  const frontend = htmlOwnerMode(html, expectedSha);
  if (frontend !== mode) fail('mismatch');
  const response = await get(serverUrl);
  let body; try { body = await response.json(); } catch { fail('server_body'); }
  let server;
  if (response.status === 401 && body?.error === 'owner_auth_required') server = '1';
  else if (response.status === 503 && body?.error === 'owner_auth_disabled') server = '0';
  else fail('server_boundary');
  return assertModes({ frontend, reader: mode, server });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const result = await verifyOwnerModes({ publicUrl: process.env.ARGUS_PUBLIC_URL,
      baseUrl: process.env.ARGUS_BACKEND_URL, expectedSha: process.env.ARGUS_EXPECTED_SHA,
      mode: process.env.ARGUS_ACCEPTANCE_OWNER_AUTH || '0' });
    console.log(JSON.stringify(result));
  } catch (error) {
    console.error(error instanceof OwnerModeError ? error.message : 'owner_mode:failed');
    process.exitCode = 1;
  }
}

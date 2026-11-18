// 2026-11-18 owner 「やはり作る」: the iPhone's notification registration
// expired on 10/8 and nothing on the screen said so for six weeks. A device
// that once registered asks the server, when ARGUS opens, whether it is
// still on the list. Only a definite answer shows the notice; a network or
// sign-in failure shows nothing.
export const PUSH_REGISTERED_KEY = 'argus.webPush.registered.v1';

export type PushServerAnswer = 'enabled' | 'disabled' | 'missing' | 'unknown';
export type PushRegistrationState = 'ok' | 'lost' | 'none' | 'unknown';

export async function pushRegistrationState(deps: {
  registered: boolean;
  subscriptionEndpoint: () => Promise<string | null>;
  serverAnswer: (identity: string) => Promise<PushServerAnswer>;
  digest: (text: string) => Promise<string>;
}): Promise<PushRegistrationState> {
  let endpoint: string | null;
  try { endpoint = await deps.subscriptionEndpoint(); } catch { return 'unknown'; }
  if (!endpoint) return deps.registered ? 'lost' : 'none';
  let answer: PushServerAnswer;
  try { answer = await deps.serverAnswer(await deps.digest(endpoint)); } catch { return 'unknown'; }
  if (answer === 'enabled') return 'ok';
  if (answer === 'unknown') return 'unknown';
  return deps.registered ? 'lost' : 'none';
}

export function rememberPushRegistered(on: boolean): void {
  try {
    if (on) localStorage.setItem(PUSH_REGISTERED_KEY, '1');
    else localStorage.removeItem(PUSH_REGISTERED_KEY);
  } catch { /* Storage off: the notice simply cannot be shown later. */ }
}

async function sha256Hex(text: string): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('');
}

/** The real check on this device (no request when ARGUS cannot know). */
export async function checkThisDevicePush(): Promise<PushRegistrationState> {
  let registered = false; let token = '';
  try {
    registered = localStorage.getItem(PUSH_REGISTERED_KEY) === '1';
    token = localStorage.getItem('argus.ownerSyncToken.v1') || '';
  } catch { return 'unknown'; }
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
  if (!token || !base || !('serviceWorker' in navigator) || !('PushManager' in window)) return 'unknown';
  const state = await pushRegistrationState({
    registered,
    subscriptionEndpoint: async () => {
      const scope = new URL(import.meta.env.BASE_URL, window.location.origin).href;
      const reg = await navigator.serviceWorker.getRegistration(scope);
      if (!reg || reg.scope !== scope) throw new Error('no_worker');
      return (await reg.pushManager.getSubscription())?.endpoint ?? null;
    },
    serverAnswer: async identity => {
      const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(base + '/api/argus/owner-dialogue', { method: 'POST', cache: 'no-store',
          signal: controller.signal, headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'notifications', ownerToken: token, operation: 'status', subscriptionId: identity }) });
        const data = await response.json().catch(() => ({}));
        if (response.ok) return data.enabled === true ? 'enabled' : data.enabled === false ? 'disabled' : 'unknown';
        return response.status === 400 && data.error === 'push_subscription_missing' ? 'missing' : 'unknown';
      } finally { clearTimeout(timer); }
    },
    digest: sha256Hex,
  });
  // A device found registered is remembered, so a later expiry can be told.
  if (state === 'ok') rememberPushRegistered(true);
  return state;
}

import React from 'react';
import ReactDOM from 'react-dom/client';
import { registerSW } from 'virtual:pwa-register';
import App from './App';
import { AssetsProvider } from './hooks/useAssets';
import './styles/theme.css';

// ── PWA update reliability (v10.70) ─────────────────────────────────────────
// History: registerType is 'autoUpdate' + a 60s r.update() poll (v10.32), but
// installed PWAs STILL got wedged on an old build ("10.59から変わらない"): the new
// SW would install yet the open app never reloaded into it, so the rendered
// version stayed stale indefinitely.
// Fix: actively compare the RUNNING build (__APP_VERSION__, baked into the served
// index.html) against the freshly-fetched DEPLOYED index.html (cache-busted, so
// it bypasses the SW precache). On mismatch we force updateSW(true) + reload; if
// that doesn't take after a couple of tries the SW is wedged, so we self-heal —
// unregister SWs, clear caches, hard reload. Everything is best-effort + loop-
// guarded (sessionStorage counter) so it can never brick or reload-loop the app.
const RUNNING = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : '';
const RUNNING_PRODUCT = typeof __PRODUCT_VERSION__ === 'string' ? __PRODUCT_VERSION__ : '';
const RUNNING_SHA = typeof __FRONTEND_BUILD_SHA__ === 'string' ? __FRONTEND_BUILD_SHA__ : '';
const RUNNING_IDENTITY = `${RUNNING}|${RUNNING_PRODUCT}|${RUNNING_SHA}`;
const TRIES_KEY = 'argus_update_tries';
const PWA_STEP_TIMEOUT_MS = 12_000;
const PWA_RECONCILE_TIMEOUT_MS = 36_000;

function waitAtMost<T>(promise: Promise<T>, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => resolve(false), timeoutMs);
    promise.then(
      () => { window.clearTimeout(timeout); resolve(true); },
      (error: unknown) => { window.clearTimeout(timeout); reject(error); },
    );
  });
}

async function fetchDeployedIdentity(): Promise<string | null> {
  const ctrl = new AbortController();
  const timeout = window.setTimeout(() => ctrl.abort(), PWA_STEP_TIMEOUT_MS);
  try {
    const url = `${import.meta.env.BASE_URL}index.html?cb=${Date.now()}`;
    const html = await fetch(url, { cache: 'no-store', signal: ctrl.signal }).then((r) => r.text());
    const app = html.match(/__ARGUS_VERSION__\s*=\s*"([^"]+)"/)?.[1];
    const product = html.match(/__ARGUS_PRODUCT_VERSION__\s*=\s*"([^"]+)"/)?.[1];
    const sha = html.match(/__ARGUS_BUILD_SHA__\s*=\s*"([^"]+)"/)?.[1];
    return app && product && sha ? `${app}|${product}|${sha}` : null;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function selfHeal(): Promise<void> {
  try {
    const regs = (await navigator.serviceWorker?.getRegistrations?.()) || [];
    await Promise.all(regs.map((r) => r.unregister().catch(() => false)));
    if (window.caches) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
    // v13.5.14: the Today headline document also lives in IndexedDB and
    // survived every previous self-heal — a durable 「古いまま」 path.
    await new Promise<void>((resolve) => {
      try {
        const request = indexedDB.deleteDatabase('argus-verified-snapshots');
        request.onsuccess = () => resolve();
        request.onerror = () => resolve();
        request.onblocked = () => resolve();
      } catch {
        resolve();
      }
    });
  } catch {
    /* ignore — fall through to reload */
  }
}

let registeredServiceWorker: ServiceWorkerRegistration | undefined;
const updateSW = registerSW({
  immediate: true,
  onRegisteredSW(_url, r) {
    registeredServiceWorker = r;
  },
});

async function reconcileVersion(): Promise<void> {
  const deployed = await fetchDeployedIdentity();
  if (!deployed || !RUNNING_IDENTITY || deployed === RUNNING_IDENTITY) {
    localStorage.setItem('argus.bundle.identity', RUNNING_IDENTITY);
    document.documentElement.style.visibility = 'visible';
    sessionStorage.removeItem(TRIES_KEY); // up to date (or can't tell) — reset
    return;
  }
  const tries = Number(sessionStorage.getItem(TRIES_KEY) || '0');
  sessionStorage.setItem(TRIES_KEY, String(tries + 1));
  if (tries >= 5) return; // give up this session; avoid any reload loop
  if (tries >= 1) {
    // First updateSW didn't take → the SW swapped index.html but kept stale JS
    // chunks. Self-heal aggressively: unregister SWs, clear caches, hard reload.
    await selfHeal();
    window.location.reload();
    return;
  }
  try {
    const completed = await waitAtMost(updateSW(true), PWA_STEP_TIMEOUT_MS);
    if (!completed) window.location.reload();
  } catch {
    window.location.reload();
  }
}

let versionReconcileInFlight: Promise<void> | null = null;
function reconcileVersionOnce(): Promise<void> {
  if (versionReconcileInFlight) return versionReconcileInFlight;
  const current = reconcileVersion().finally(() => {
    if (versionReconcileInFlight === current) versionReconcileInFlight = null;
  });
  versionReconcileInFlight = current;
  return current;
}

let serviceWorkerUpdateInFlight: Promise<void> | null = null;
function updateServiceWorkerOnce(): Promise<void> {
  if (!registeredServiceWorker) return Promise.resolve();
  if (serviceWorkerUpdateInFlight) return serviceWorkerUpdateInFlight;
  const current = registeredServiceWorker.update()
    .then(() => undefined)
    .catch(() => {})
    .finally(() => {
      if (serviceWorkerUpdateInFlight === current) serviceWorkerUpdateInFlight = null;
    });
  serviceWorkerUpdateInFlight = current;
  return current;
}

let pwaPollInFlight: Promise<void> | null = null;
function pollPwaState(checkServiceWorker = true): Promise<void> {
  if (pwaPollInFlight) return pwaPollInFlight;
  const current = (async () => {
    if (checkServiceWorker) {
      // ServiceWorkerRegistration.update() has no AbortSignal. Keep its own
      // single-flight promise, but do not let a stalled browser operation block
      // deployed-version reconciliation forever.
      await waitAtMost(updateServiceWorkerOnce(), PWA_STEP_TIMEOUT_MS);
    }
    // A defensive outer bound also covers browser cache/self-heal APIs that do
    // not accept AbortSignal. Their tracked promise remains single-flight even
    // if this cycle proceeds after the bound.
    await waitAtMost(reconcileVersionOnce(), PWA_RECONCILE_TIMEOUT_MS);
  })().finally(() => {
    if (pwaPollInFlight === current) pwaPollInFlight = null;
  });
  pwaPollInFlight = current;
  return current;
}

// Check shortly after first paint, then use one 60s scheduler for both the SW
// update check and deployed-version reconciliation.
window.setTimeout(() => { pollPwaState(false).catch(() => {}); }, 4_000);
window.setInterval(() => { pollPwaState().catch(() => {}); }, 60_000);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AssetsProvider>
      <App />
    </AssetsProvider>
  </React.StrictMode>
);

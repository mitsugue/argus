import React from 'react';
import ReactDOM from 'react-dom/client';
import { registerSW } from 'virtual:pwa-register';
import App from './App';
import { OwnerAccess } from './components/OwnerAccess';
import { OWNER_AUTH_REQUIRED, installOwnerTransport } from './lib/ownerSession';
installOwnerTransport();
import { AssetsProvider } from './hooks/useAssets';
import { WatchlistSyncLifecycle } from './hooks/useWatchlistSync';
import { clearVerifiedSnapshotCache } from './lib/verifiedSnapshot';
import { repairAppCaches } from './lib/pwaRecovery';
import { deployedPwaIdentity, authenticationOnlyUpdate, deployedEntryScript, deployedIsBehind,
  identityDiffersOnlyInBuildSha } from './lib/pwaIdentity';
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
const RUNNING_IDENTITY = `${RUNNING}|${RUNNING_PRODUCT}|${RUNNING_SHA}|${OWNER_AUTH_REQUIRED ? '1' : '0'}`;
// Record the executing bundle before the first 4s poll: a quick close must not
// make the next offline launch purge the shell it has just installed.
try { localStorage.setItem('argus.bundle.identity', RUNNING_IDENTITY); } catch { /* storage unavailable */ }
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

// The entry module this code runs from (the built bundle's file name); null
// outside a production build, where the served-page comparison is skipped.
const RUNNING_ENTRY_SCRIPT = (() => {
  try {
    const name = new URL(import.meta.url).pathname.split('/').pop() ?? '';
    return /^index-[A-Za-z0-9_-]+\.js$/.test(name) ? name : null;
  } catch {
    return null;
  }
})();

interface ServedPage { identity: string | null; entryScript: string | null }

async function fetchDeployedPage(): Promise<ServedPage | null> {
  const ctrl = new AbortController();
  const timeout = window.setTimeout(() => ctrl.abort(), PWA_STEP_TIMEOUT_MS);
  try {
    const url = `${import.meta.env.BASE_URL}index.html?cb=${Date.now()}`;
    const html = await fetch(url, { cache: 'no-store', signal: ctrl.signal }).then((r) => r.text());
    return { identity: deployedPwaIdentity(html), entryScript: deployedEntryScript(html) };
  } catch {
    return null;
  } finally {
    window.clearTimeout(timeout);
  }
}

/** A served page that is not an update of the running code: the previous
 *  release still on an edge, or a page whose entry module is the one already
 *  running (a release that changed nothing the page loads). Reloading into
 *  either gains nothing and drops the in-memory owner session. 2026-09-30:
 *  for minutes after each Pages release the 60s poll met such pages, and the
 *  owner (and every acceptance click) landed on the lock screen again. */
function servedPageIsNotAnUpdate(served: ServedPage, running: string): boolean {
  if (!served.identity || served.identity === running) return false;
  if (deployedIsBehind(running, served.identity)) return true;
  return !!RUNNING_ENTRY_SCRIPT && served.entryScript === RUNNING_ENTRY_SCRIPT
    && identityDiffersOnlyInBuildSha(running, served.identity);
}

async function selfHeal(preserveSnapshots: boolean): Promise<void> {
  try {
    await repairAppCaches(import.meta.env.BASE_URL);
    // IndexedDB also holds owner-created chart drawings. Refresh only the
    // server-derived views, and bound the wait if another tab blocks storage.
    if (!preserveSnapshots) await waitAtMost(clearVerifiedSnapshotCache(), PWA_STEP_TIMEOUT_MS);
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
  const served = await fetchDeployedPage();
  const deployed = served?.identity ?? null;
  if (!deployed || !RUNNING_IDENTITY || deployed === RUNNING_IDENTITY
      || (served && servedPageIsNotAnUpdate(served, RUNNING_IDENTITY))) {
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
    await selfHeal(authenticationOnlyUpdate(RUNNING_IDENTITY, deployed));
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

// Installed apps often suspend timers while closed. Reconcile on return as well.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') pollPwaState().catch(() => {});
});
window.addEventListener('online', () => { pollPwaState().catch(() => {}); });

// Check shortly after first paint, then use one 60s scheduler for both the SW
// update check and deployed-version reconciliation.
window.setTimeout(() => { pollPwaState(false).catch(() => {}); }, 4_000);
window.setInterval(() => { pollPwaState().catch(() => {}); }, 60_000);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <OwnerAccess>
    <AssetsProvider>
      <WatchlistSyncLifecycle />
      <App />
    </AssetsProvider>
    </OwnerAccess>
  </React.StrictMode>
);

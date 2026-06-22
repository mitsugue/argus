import React from 'react';
import ReactDOM from 'react-dom/client';
import { registerSW } from 'virtual:pwa-register';
import App from './App';
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
const TRIES_KEY = 'argus_update_tries';

async function fetchDeployedVersion(): Promise<string | null> {
  try {
    const url = `${import.meta.env.BASE_URL}index.html?cb=${Date.now()}`;
    const html = await fetch(url, { cache: 'no-store' }).then((r) => r.text());
    const m = html.match(/__ARGUS_VERSION__\s*=\s*"([^"]+)"/);
    return m ? m[1] : null;
  } catch {
    return null;
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
  } catch {
    /* ignore — fall through to reload */
  }
}

const updateSW = registerSW({
  immediate: true,
  onRegisteredSW(_url, r) {
    if (r) setInterval(() => { r.update().catch(() => {}); }, 60_000);
  },
});

async function reconcileVersion(): Promise<void> {
  const deployed = await fetchDeployedVersion();
  if (!deployed || !RUNNING || deployed === RUNNING) {
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
    await updateSW(true); // installs waiting SW + reloads
  } catch {
    window.location.reload();
  }
}

// Check shortly after first paint, then alongside the 60s SW poll.
window.setTimeout(() => { reconcileVersion().catch(() => {}); }, 4_000);
window.setInterval(() => { reconcileVersion().catch(() => {}); }, 60_000);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

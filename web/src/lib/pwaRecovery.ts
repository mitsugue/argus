/** Repair the app shell without removing notification subscriptions or other apps. */
export async function repairAppCaches(baseUrl: string): Promise<void> {
  const base = new URL(baseUrl, location.href);
  const registrations = await navigator.serviceWorker?.getRegistrations?.() || [];
  await Promise.all(registrations.map(async (registration) => {
    if (registration.scope !== base.href) return;
    const workers = [registration.active, registration.waiting, registration.installing].filter(Boolean);
    if (!workers.length || workers.some((worker) => {
      const script = new URL(worker!.scriptURL);
      return script.origin !== base.origin || !['sw.js', 'dev-sw.js'].some((file) =>
        script.pathname === new URL(file, base).pathname);
    })) return;
    try {
      // A failed subscription lookup is not proof that there is no subscription.
      if (registration.pushManager && await registration.pushManager.getSubscription()) return;
      await registration.unregister();
    } catch { /* Keep the registration; the normal update path can still run. */ }
  }));
  if (globalThis.caches) {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key === 'argus-api'
      || (key.startsWith('workbox-precache-') && key.endsWith(base.href)))
      .map((key) => caches.delete(key)));
  }
}

/* Standard Web Push receiver, imported by the existing app service worker. */
(() => {
  const receiptDb = () => new Promise((resolve, reject) => {
    const request = indexedDB.open('argus.webPush.receipts.v1', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('receipts', {keyPath:'deliveryId'});
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  async function receipt(id, field) {
    const db = await receiptDb();
    try { await new Promise((resolve,reject) => {
      const tx = db.transaction('receipts','readwrite'); const store = tx.objectStore('receipts');
      const get = store.get(id);
      get.onsuccess = () => store.put({...get.result, deliveryId:id, [field]:get.result?.[field] || new Date().toISOString()});
      tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
    }); } finally { db.close(); }
  }
  const safeHash = hash => hash === '#settings' || hash === '#notifications'
    || /^#notifications\/news\/[A-Za-z0-9:_-]{1,150}$/.test(hash)
    || /^#notifications\/sq\/jp-monthly-sq-\d{4}-\d{2}$/.test(hash)
    // A registered symbol's screen; the same shape argus_web_push.ASSET_SYMBOL sends.
    || /^#asset\/[A-Z0-9]{1,10}(?:[.-][A-Z0-9]{1,5})?$/.test(hash);
  // Focus an open ARGUS window, then move it to the target. When navigate is
  // missing, refused (iOS home-screen apps) or throws, open the target instead:
  // a tap must never end with nothing opened.
  async function openTarget(target) {
    const scope = new URL(self.registration.scope);
    let windows = [];
    try { windows = await self.clients.matchAll({type:'window',includeUncontrolled:true}); } catch { /* Open below. */ }
    for (const client of windows) {
      let url; try { url = new URL(client.url); } catch { continue; }
      if (url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) continue;
      let current = client;
      try { current = (await client.focus()) || client; } catch { /* Navigation may still work. */ }
      try {
        if (typeof current.navigate === 'function' && await current.navigate(target)) return;
      } catch { /* Fall through to openWindow. */ }
      break;
    }
    await self.clients.openWindow(target);
  }
  self.addEventListener('push', event => {
    event.waitUntil((async () => {
      let data; try { data = event.data.json(); } catch { return; }
      if (data.schemaVersion !== 'argus-web-push-v1' || typeof data.deliveryId !== 'string'
          || !/^[a-f0-9-]{36}$/.test(data.deliveryId) || !safeHash(data.hash)
          || typeof data.title !== 'string' || typeof data.body !== 'string'
          || !Number.isFinite(Date.parse(data.expiresAt)) || Date.parse(data.expiresAt) <= Date.now()) return;
      await self.registration.showNotification(data.title.slice(0,100), {
        body:data.body.slice(0,220), tag:'argus-'+data.deliveryId, renotify:false,
        icon:new URL('icon-192.svg',self.registration.scope).href,
        data:{deliveryId:data.deliveryId,hash:data.hash},
      });
      // Resolving showNotification is browser-reported display, not human receipt.
      try { await receipt(data.deliveryId,'displayedAt'); } catch { /* Display still succeeded. */ }
    })());
  });
  self.addEventListener('notificationclick', event => {
    const data = event.notification.data;
    if (!data || !safeHash(data.hash) || !/^[a-f0-9-]{36}$/.test(data.deliveryId)) return;
    event.notification.close();
    event.waitUntil((async () => {
      // Record the open alongside the navigation so storage never delays the
      // click's permission to focus or open a window.
      const opened = receipt(data.deliveryId,'openedAt').catch(() => { /* Navigation remains available. */ });
      try { await openTarget(new URL(data.hash,self.registration.scope).href); }
      finally { await opened; }
    })());
  });
})();

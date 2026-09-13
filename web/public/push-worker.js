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
    || /^#notifications\/sq\/jp-monthly-sq-\d{4}-\d{2}$/.test(hash);
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
      try { await receipt(data.deliveryId,'openedAt'); } catch { /* Navigation remains available. */ }
      const target = new URL(data.hash,self.registration.scope).href;
      const windows = await self.clients.matchAll({type:'window',includeUncontrolled:true});
      for (const client of windows) {
        const url = new URL(client.url); const scope = new URL(self.registration.scope);
        if (url.origin === scope.origin && url.pathname.startsWith(scope.pathname)) {
          const navigated = await client.navigate(target); if (navigated) await navigated.focus(); return;
        }
      }
      await self.clients.openWindow(target);
    })());
  });
})();

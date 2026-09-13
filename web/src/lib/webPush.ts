export type PushStatus = {subscriptionId:string;enabled:boolean;sq:boolean;news:boolean;deliveries:Array<{
  id:string;status:string;attempted:number|null;display_at:string|null;opened_at:string|null}>};
export async function pushRequest(token:string, operation:string, fields:Record<string,unknown>={}) {
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string|undefined)?.replace(/\/$/,'');
  if (!base) throw new Error('接続先を確認できません。');
  const controller = new AbortController(); const timer = setTimeout(()=>controller.abort(),15000);
  try {
    const response = await fetch(base+'/api/argus/owner-dialogue',{method:'POST',cache:'no-store',signal:controller.signal,
      headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'notifications',ownerToken:token,operation,...fields})});
    const data = await response.json();
    if (!response.ok) throw new Error(response.status===401||response.status===403?'所有者の接続キーを確認してください。':
      data.error==='push_not_configured'?'サーバーの通知接続は準備中です。':data.error==='push_test_cooldown'?'確認通知は1分間隔で送れます。':'通知設定を確認できませんでした。');
    return data;
  } finally { clearTimeout(timer); }
}
export function applicationKey(value:string):Uint8Array<ArrayBuffer> {
  const decoded=atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4));
  return Uint8Array.from(decoded,c=>c.charCodeAt(0));
}
export async function appPushRegistration() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window))
    throw new Error('この環境はWeb Pushに対応していません。iPhoneはホーム画面のARGUSで操作してください。');
  const scope = new URL(import.meta.env.BASE_URL,window.location.origin).href;
  const reg = await navigator.serviceWorker.getRegistration(scope);
  if (!reg || reg.scope !== scope || !reg.active) throw new Error('アプリの更新後に開き直して、もう一度お試しください。');
  return reg;
}
export async function pushReceipts():Promise<Array<{deliveryId:string;displayedAt:string|null;openedAt:string|null}>> {
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open('argus.webPush.receipts.v1',1);
    request.onupgradeneeded=()=>request.result.createObjectStore('receipts',{keyPath:'deliveryId'});
    request.onerror=()=>reject(request.error);
    request.onsuccess=()=>{
      const db=request.result;const tx=db.transaction('receipts','readonly');const read=tx.objectStore('receipts').getAll();
      read.onsuccess=()=>resolve(read.result.sort((a,b)=>String(b.displayedAt||b.openedAt).localeCompare(String(a.displayedAt||a.openedAt))).slice(0,50)
        .map(r=>({deliveryId:r.deliveryId,displayedAt:r.displayedAt||null,openedAt:r.openedAt||null})));
      tx.oncomplete=()=>db.close();tx.onerror=()=>{db.close();reject(tx.error);};
    };
  });
}

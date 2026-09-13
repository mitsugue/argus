import React,{useState} from 'react';
import {appPushRegistration,applicationKey,pushReceipts,pushRequest,type PushStatus} from '../../lib/webPush';
import './AiUsagePanel.css';
import './WebPushPanel.css';
const initialToken=()=>{try{return localStorage.getItem('argus.ownerSyncToken.v1')||'';}catch{return '';}};
const labels:Record<string,string>={QUEUED:'配信待ち',SENDING:'配信処理中',SERVICE_ACCEPTED:'配信サービス受付済み',SERVICE_REJECTED:'配信サービスが拒否',SUBSCRIPTION_EXPIRED:'端末の購読が失効',DELIVERY_UNKNOWN:'配信結果を確認できず',EXPIRED:'配信期限切れ',CANCELLED:'停止済み'};
const stamp=(value:string|null)=>value?new Date(value).toLocaleString('ja-JP'):'未記録';
export function WebPushPanel(){
  const [token,setToken]=useState(initialToken);const [publicKey,setPublicKey]=useState('');
  const [sq,setSq]=useState(true);const [news,setNews]=useState(true);
  const [status,setStatus]=useState<PushStatus|null>(null);const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);
  const run=async(work:()=>Promise<void>)=>{setBusy(true);setMessage('');try{await work();}
    catch(e){setMessage(e instanceof Error?e.message:'通知を確認できませんでした。');}finally{setBusy(false);}};
  const show=(data:PushStatus)=>{setStatus(data);setSq(data.sq);setNews(data.news);};
  const load=()=>run(async()=>{
    const config=await pushRequest(token,'configuration');
    if(!config.configured||typeof config.publicKey!=='string')throw new Error('サーバーの通知接続は準備中です。');
    setPublicKey(config.publicKey);
    const reg=await appPushRegistration();const sub=await reg.pushManager.getSubscription();
    if(sub){const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(sub.endpoint));
      const identity=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');
      show(await pushRequest(token,'receipts',{subscriptionId:identity,receipts:await pushReceipts()}));
    }else{setStatus(null);setMessage('この端末では未登録です。通知する項目を選び「通知を有効にする」を押してください。');}
  });
  const enable=()=>{
    // Start the OS permission request directly in the user gesture.
    if(!('Notification'in window)){setMessage('iPhoneはホーム画面のARGUSで操作してください。');return;}
    const permission=Notification.requestPermission();
    void run(async()=>{
      if(await permission!=='granted')throw new Error('通知が許可されていません。端末の通知設定でARGUSを確認してください。');
      const reg=await appPushRegistration();let sub=await reg.pushManager.getSubscription();
      if(sub?.options.applicationServerKey){const actual=new Uint8Array(sub.options.applicationServerKey);const expected=applicationKey(publicKey);
        if(actual.length!==expected.length||actual.some((b,i)=>b!==expected[i]))throw new Error('通知接続キーが変わっています。既存の通知を停止してから再登録してください。');}
      sub=sub||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:applicationKey(publicKey)});
      show(await pushRequest(token,'subscribe',{subscription:sub.toJSON(),sq,news}));
      setMessage('この端末の通知設定をサーバーへ保存しました。実受信はまだ確認していません。');
    });
  };
  const disable=()=>run(async()=>{
    if(!status)return;show(await pushRequest(token,'disable',{subscriptionId:status.subscriptionId}));
    const sub=await(await appPushRegistration()).pushManager.getSubscription();if(sub&&!await sub.unsubscribe())throw new Error('サーバー配信は停止しました。端末の購読解除は未確認です。');
    setMessage('この端末への外部配信を停止しました。');
  });
  const test=()=>run(async()=>{if(!status)return;show(await pushRequest(token,'test',{subscriptionId:status.subscriptionId}));
    setMessage('約1分後の確認通知を予約しました。アプリを閉じて確認し、戻って「接続・受信状況を更新」を押してください。');});
  return <section className="card ai-usage web-push" aria-label="アプリを閉じたときの通知"><h3>アプリを閉じたときの通知</h3>
    <p>SQの週・最終取引日・当日の案内と、新しい重大ニュースを知らせます。売買の指示ではありません。</p>
    <p>iPhoneはiOS 16.4以降のホーム画面版で、通知の許可が必要です。対応するSafari・Chrome・Firefoxでも利用できます。</p>
    <details><summary>所有者の接続設定</summary><label>接続キー<input type="password" autoComplete="off" value={token} disabled={busy}
      onChange={e=>{setToken(e.target.value);setStatus(null);setPublicKey('');setMessage('');}}/></label>
      <p>この欄の入力は端末へ保存しません。購読先と通知設定をサーバーに保存します。保有情報や記事本文は通知に送りません。</p></details>
    <div className="ai-usage__controls"><button disabled={busy||!token} onClick={()=>void load()}>接続・受信状況を更新</button></div>
    <label className="web-push__preference"><input type="checkbox" checked={sq} disabled={busy} onChange={e=>setSq(e.target.checked)}/>SQの日程案内</label>
    <label className="web-push__preference"><input type="checkbox" checked={news} disabled={busy} onChange={e=>setNews(e.target.checked)}/>新しい重大ニュース</label>
    <div className="ai-usage__controls"><button disabled={busy||!token||!publicKey} onClick={enable}>{status?.enabled?'通知項目を保存':'通知を有効にする'}</button>
      {status?.enabled&&<><button disabled={busy} onClick={()=>void test()}>1分後に確認通知</button><button disabled={busy} onClick={()=>void disable()}>この端末への通知を停止</button></>}</div>
    {busy&&<p role="status">通知の接続を確認しています。</p>}{message&&<p role="status">{message}</p>}
    {status&&<><p>サーバー設定：{status.enabled?'有効':'停止中'}</p>
      {status.deliveries.map(d=><article key={d.id} className="ai-usage__group"><strong>{labels[d.status]||'状態を確認中'}</strong>
        <p>端末から報告された表示処理：{stamp(d.display_at)}<br/>通知を開いた記録：{stamp(d.opened_at)}</p></article>)}
      {!status.deliveries.length&&<p>この端末の配信記録はまだありません。</p>}</>}
    <details><summary>通知の確認範囲</summary><p>配信サービスの受付と、端末での実受信は別です。通知が実際に見えたかは、アプリを閉じた端末で確認します。集中モード等で表示が遅れる場合があります。</p>
      <p>結果不明の配信は重複を避けて自動再送しません。再起動後の端末設定は保存しますが、遠隔バックアップからの復旧は未確認です。</p>
      <p>上の端末内通知履歴とは別の配信設定です。保有銘柄固有の外部通知は未接続です。</p></details>
  </section>;
}

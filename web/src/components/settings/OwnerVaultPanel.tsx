import React,{useState} from 'react';
import {buildBackupPayload,hasBackupContent,restoreBackup,type BackupFile} from '../../lib/backup';
import {getVaultPass,vaultIdFrom} from '../../lib/vault';
import {saveOwnerVault,readOwnerVault,vaultRequest,type VaultSnapshot} from '../../lib/ownerVault';
import './AiUsagePanel.css';
const tokenValue=()=>{try{return localStorage.getItem('argus.ownerSyncToken.v1')||'';}catch{return '';}};
export function OwnerVaultPanel(){
 const [token,setToken]=useState(tokenValue);const [pass,setPass]=useState(()=>getVaultPass()||'');
 const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [error,setError]=useState('');
 const [rows,setRows]=useState<VaultSnapshot[]>([]);const [next,setNext]=useState<number|null>(null);
 const [preview,setPreview]=useState<{id:string;payload:BackupFile}|null>(null);
 const run=async(work:()=>Promise<void>)=>{setBusy(true);setError('');try{await work();}catch(e){setError(e instanceof Error?e.message:'保存先を確認できませんでした。');}finally{setBusy(false);}};
 const clear=()=>{setRows([]);setPreview(null);setNext(null);setMessage('');setError('');};
 const list=async(more=false)=>{const data=await vaultRequest(token,await vaultIdFrom(pass),'list',more&&next!==null?{offset:next}:{});
   if(!Array.isArray(data.snapshots)||!data.snapshots.every((r:VaultSnapshot)=>/^[a-f0-9]{64}$/.test(r.snapshotId)&&Number.isFinite(r.savedAt)&&Number.isFinite(r.bytes)))throw new Error('保存点一覧の形式を確認できません。');
   setRows(old=>more?[...old,...data.snapshots]:data.snapshots);setNext(data.nextOffset);
   if(!data.snapshots.length)setMessage('この接続とパスフレーズに対応する新しい保存点はありません。旧方式の復元は下の欄から利用できます。');};
 const save=()=>run(async()=>{const result=await saveOwnerVault(token,pass,setMessage);setMessage(`暗号化保存・読み戻し・復号照合が完了しました（${new Date(result.savedAt*1000).toLocaleString('ja-JP')}）。別端末での復元確認はまだです。`);await list();});
 const inspect=(row:VaultSnapshot)=>run(async()=>{setMessage('選択した保存点を復号し、隔離領域で内容を確認しています。');
   const payload=await readOwnerVault(token,pass,row.snapshotId);setPreview({id:row.snapshotId,payload});setMessage('保存点の内容を確認しました。端末のデータはまだ変更していません。');});
 const restore=()=>run(async()=>{if(!preview)return;const selected=preview;
   if(hasBackupContent()){setMessage('現在の端末データを別の保存点へ退避しています。');await saveOwnerVault(token,pass,setMessage,buildBackupPayload());}
   setMessage('選択した保存点を復元しています。');const count=restoreBackup(selected.payload);
   if(!count)throw new Error('復元できる項目を確認できませんでした。');
   window.dispatchEvent(new CustomEvent('argus:data-synced'));setMessage(`${count}項目を復元しました。変更前のデータも保存点に保持しています。画面を開き直すと全設定に反映されます。`);setPreview(null);await list();});
 const assets=preview?.payload.data['argus.assets.v1'];const judgments=preview?.payload.data['argus.judgmentLog.v1'];
 return <section className="card ai-usage" aria-label="所有者の暗号化保存と端末復元"><h3>端末データを暗号化して保存</h3>
   <p>保有銘柄・設定・判断履歴を、所有者専用の非公開保存先へ退避します。以前の保存点は上書きしません。</p>
   <details><summary>接続と暗号化の設定</summary><label>所有者の接続キー<input type="password" value={token} autoComplete="off" disabled={busy} onChange={e=>{setToken(e.target.value);clear();}}/></label>
     <label>暗号化のパスフレーズ<input type="password" value={pass} autoComplete="off" disabled={busy} onChange={e=>{setPass(e.target.value);clear();}}/></label>
     <p>パスフレーズはサーバーに送信しません。この欄の入力も端末へ保存しません。別端末での復元には、接続キーと同じパスフレーズが必要です。</p></details>
   <div className="ai-usage__controls"><button disabled={busy||!token||!pass} onClick={()=>void save()}>今のデータを保存・送信再開</button>
     <button disabled={busy||!token||!pass} onClick={()=>void run(()=>list())}>保存点を確認</button></div>
   {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
   {rows.map(row=><article key={row.snapshotId} className="ai-usage__group"><p>作成 {new Date(row.exportedAt).toLocaleString('ja-JP')} · {(row.bytes/1024).toFixed(0)} KiB</p>
     <button disabled={busy} onClick={()=>void inspect(row)}>この保存点の内容を確認</button></article>)}
   {next!==null&&<button disabled={busy} onClick={()=>void run(()=>list(true))}>以前の保存点</button>}
   {preview&&<div className="ai-usage__group"><h4>復元前の確認</h4><p>登録銘柄 {Array.isArray(assets)?assets.length:'未収録'}件 · 判断記録 {Array.isArray(judgments)?judgments.length:'未収録'}件 · 収録項目 {Object.keys(preview.payload.data).length}</p>
     <p>現在のデータがある場合は先に別の保存点へ退避します。選択した保存点にない項目は消しません。</p>
     <button disabled={busy} onClick={()=>void restore()}>現在分を退避して、この保存点へ復元</button><button disabled={busy} onClick={()=>setPreview(null)}>閉じる</button></div>}
   <details><summary>保存される範囲</summary><p>この操作は端末データの保存点を作ります。端末同士の変更を自動統合する機能ではありません。保存後の編集は次の保存まで遠隔保護されません。</p>
     <p>暗号化後8 MiBまで。アプリ更新・通信切断で止まった送信は、同じデータから再開できます。履歴を削って容量を合わせることはしません。</p>
     <p>接続キー・パスフレーズ・Web Push購読、サーバーに保存する私的対話は、この端末バックアップの対象に含めません。</p></details>
 </section>;
}

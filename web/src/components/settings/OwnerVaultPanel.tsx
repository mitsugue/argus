import { TriangleStepLoader } from '../common/TriangleStepLoader';
import React,{useEffect,useState} from 'react';
import {buildBackupPayload,hasBackupContent,restoreBackup,type BackupFile} from '../../lib/backup';
import {getVaultPass,vaultIdFrom} from '../../lib/vault';
import {saveOwnerVault,readOwnerVault,vaultRequest,type VaultSnapshot} from '../../lib/ownerVault';
import {autoSaveEnabled,autoSaveState,disableAutoSave,enableAutoSave} from '../../lib/ownerVaultAutoSave';
import './AiUsagePanel.css';
const tokenValue=()=>{try{return localStorage.getItem('argus.ownerSyncToken.v1')||'';}catch{return '';}};
export function OwnerVaultPanel(){
 const [token,setToken]=useState(tokenValue);const [pass,setPass]=useState(()=>getVaultPass()||'');
 const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [error,setError]=useState('');
 const [rows,setRows]=useState<VaultSnapshot[]>([]);const [next,setNext]=useState<number|null>(null);
 const [preview,setPreview]=useState<{id:string;payload:BackupFile}|null>(null);
 const [automatic,setAutomatic]=useState(autoSaveEnabled);const [autoState,setAutoState]=useState(autoSaveState);
 useEffect(()=>{const refresh=()=>{setAutomatic(autoSaveEnabled());setAutoState(autoSaveState());};
   window.addEventListener('argus:vault-auto-state',refresh);window.addEventListener('argus:vault-auto-config',refresh);window.addEventListener('storage',refresh);
   return()=>{window.removeEventListener('argus:vault-auto-state',refresh);window.removeEventListener('argus:vault-auto-config',refresh);window.removeEventListener('storage',refresh);};},[]);
 const run=async(work:()=>Promise<void>)=>{setBusy(true);setError('');setMessage('');try{await work();}catch(e){setError(e instanceof Error?e.message:'保存先を確認できませんでした。');}finally{setBusy(false);}};
 const clear=()=>{setRows([]);setPreview(null);setNext(null);setMessage('');setError('');};
 const list=async(more=false)=>{const data=await vaultRequest(token,await vaultIdFrom(pass),'list',more&&next!==null?{offset:next}:{});
   if(!Array.isArray(data.snapshots)||!data.snapshots.every((r:VaultSnapshot)=>/^[a-f0-9]{64}$/.test(r.snapshotId)&&Number.isFinite(r.savedAt)&&Number.isFinite(r.bytes)))throw new Error('保存点一覧の形式を確認できません。');
   setRows(old=>more?[...old,...data.snapshots]:data.snapshots);setNext(data.nextOffset);
   if(!data.snapshots.length)setMessage('保存点なし');};
 const save=()=>run(async()=>{const result=await saveOwnerVault(token,pass,setMessage);setMessage(`保存・照合済み（${new Date(result.savedAt*1000).toLocaleString('ja-JP')}）`);await list();});
 const inspect=(row:VaultSnapshot)=>run(async()=>{setMessage('選択した保存点を復号し、隔離領域で内容を確認しています。');
   const payload=await readOwnerVault(token,pass,row.snapshotId);setPreview({id:row.snapshotId,payload});setMessage('保存点の内容を確認しました。端末のデータはまだ変更していません。');});
 const restore=()=>run(async()=>{if(!preview)return;const selected=preview;
   if(hasBackupContent()){setMessage('現在の端末データを別の保存点へ退避しています。');await saveOwnerVault(token,pass,setMessage,buildBackupPayload());}
   setMessage('選択した保存点を復元しています。');const count=restoreBackup(selected.payload);
   if(!count)throw new Error('復元できる項目を確認できませんでした。');
   window.dispatchEvent(new CustomEvent('argus:data-synced'));setMessage(`${count}項目を復元しました。変更前のデータも保存点に保持しています。画面を開き直すと全設定に反映されます。`);setPreview(null);await list();});
 const assets=preview?.payload.data['argus.assets.v1'];const judgments=preview?.payload.data['argus.judgmentLog.v1'];
 return <section className="card ai-usage" aria-label="所有者の暗号化保存と端末復元"><h3>端末データを暗号化して保存</h3>
   <details><summary>接続と暗号化の設定</summary><label>所有者の接続キー<input type="password" value={token} autoComplete="off" disabled={busy||automatic} onChange={e=>{setToken(e.target.value);clear();}}/></label>
     <label>暗号化のパスフレーズ<input type="password" value={pass} autoComplete="off" disabled={busy||automatic} onChange={e=>{setPass(e.target.value);clear();}}/></label>
     <p>自動保存中は接続キーとパスフレーズをこの端末に保持します</p></details>
   <div className="ai-usage__group"><h4>編集後の自動保存</h4><p>アプリを開いている間だけ</p>
     <button disabled={busy||(!automatic&&(!token||!pass))} onClick={()=>{setError('');try{if(automatic)disableAutoSave();else enableAutoSave(token,pass);setAutomatic(autoSaveEnabled());}catch(e){setError(e instanceof Error?e.message:'自動保存の設定を変更できませんでした。');}}}>{automatic?'自動保存を停止':'接続情報を端末に保持して自動保存を開始'}</button>
     <p role="status" data-vault-auto-phase={autoState.phase}>{autoState.phase==='SAVING'?<TriangleStepLoader label={autoState.message}/>:autoState.message}</p>
     {autoState.lastSuccessAt&&<p>最終保存照合 {new Date(autoState.lastSuccessAt).toLocaleString('ja-JP')}</p>}
</div>
   <div className="ai-usage__controls"><button disabled={busy||automatic||!token||!pass} onClick={()=>void save()}>今のデータを保存・送信再開</button>
     <button disabled={busy||!token||!pass} onClick={()=>void run(()=>list())}>保存点を確認</button></div>
   {busy&&<p><TriangleStepLoader label={message||"保存データを確認しています"}/></p>}{!busy&&message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
   {rows.map(row=><article key={row.snapshotId} className="ai-usage__group"><p>作成 {new Date(row.exportedAt).toLocaleString('ja-JP')} · {(row.bytes/1024).toFixed(0)} KiB</p>
     <button disabled={busy} onClick={()=>void inspect(row)}>この保存点の内容を確認</button></article>)}
   {next!==null&&<button disabled={busy} onClick={()=>void run(()=>list(true))}>以前の保存点</button>}
   {preview&&<div className="ai-usage__group"><h4>復元前の確認</h4><p>登録銘柄 {Array.isArray(assets)?assets.length:'未収録'}件 · 判断記録 {Array.isArray(judgments)?judgments.length:'未収録'}件 · 収録項目 {Object.keys(preview.payload.data).length}</p>
     {automatic&&<p>復元する場合は、先に自動保存を停止してください。</p>}
     <button disabled={busy||automatic} onClick={()=>void restore()}>現在分を退避して、この保存点へ復元</button><button disabled={busy} onClick={()=>setPreview(null)}>閉じる</button></div>}

 </section>;
}

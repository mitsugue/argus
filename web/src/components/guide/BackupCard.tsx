import React, { useRef, useState } from 'react';
import { TriangleStepLoader } from '../common/TriangleStepLoader';
import { downloadBackup, restoreBackup, type BackupFile } from '../../lib/backup';
import { cloudRestore, getVaultPass, setVaultPass, lastCloudBackupAt, lastSyncInfo } from '../../lib/vault';
import {preserveBeforeOwnerRestore} from '../../lib/ownerRestoreGuard';

// Complete device-data backup UI. Only this full export advances global
// backup-protection state; portfolio-only tools remain separately labelled.

export const BackupCard: React.FC = () => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState('');
  const [pass, setPass] = useState('');
  const [cloudMsg, setCloudMsg] = useState('');
  const [operation, setOperation] = useState<'file' | 'cloud' | null>(null);
  const busy = operation !== null;
  const enabled = !!getVaultPass();

  async function restoreCloud() {
    const p = pass.trim();
    if (!p) { setCloudMsg('復元にはパスフレーズを入力してください。'); return; }
    setOperation('cloud');
    try {
      let ownerWorkflow=false;
      const n = await cloudRestore(p,async()=>{ownerWorkflow=await preserveBeforeOwnerRestore(setCloudMsg);});
      if (n > 0) {
        if(!ownerWorkflow)setVaultPass(p);
        setCloudMsg(`✅ ${n}項目をクラウドから復元しました。再読み込みします…`);
        window.setTimeout(() => location.reload(), 1200);
      } else {
        setCloudMsg('復元できるデータがありませんでした。');
      }
    } catch (e) {
      setCloudMsg(String(e instanceof Error ? e.message : e));
    } finally { setOperation(null); }
  }

  function doExport() {
    const n = downloadBackup(false);
    setMsg(n > 0
      ? `完全バックアップをエクスポートしました(${n}項目)。iCloud Drive等の安全な場所に保存してください。`
      : '完全バックアップを作成できませんでした。保存データの形式を確認してください。');
  }

  function doImport(file: File) {
    setOperation('file');
    const reader = new FileReader();
    reader.onerror=()=>{setMsg('ファイルを読み込めませんでした。端末データは変更していません。');setOperation(null);};
    reader.onload = async () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as BackupFile;
        if(parsed.app!=='argus'||!parsed.data)throw new Error('invalid_backup');
        await preserveBeforeOwnerRestore(setMsg);
        const n = restoreBackup(parsed);
        if (n === 0) { setMsg('このファイルはARGUSのバックアップではないようです。'); return; }
        setMsg(`${n}項目を復元しました(${parsed.exportedAt?.slice(0, 10)}のバックアップ)。再読み込みします…`);
        window.setTimeout(() => location.reload(), 1200);
      } catch (error) {
        setMsg(error instanceof Error&&error.message!=='invalid_backup'
          ? error.message : '読み込みに失敗しました。正しいバックアップファイルか確認してください。');
      }finally{setOperation(null);}
    };
    reader.readAsText(file);
  }

  return (
    <div className="card guide-card">
      <div className="backup__actions">
        <button className="asset-btn asset-btn--primary" disabled={busy} onClick={doExport}>
          完全バックアップJSONを書き出す
        </button>
        <button className="asset-btn" disabled={busy} onClick={() => fileRef.current?.click()}>
          インポート(バックアップから復元)
        </button>
        <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }}
               onChange={(e) => { const f = e.target.files?.[0]; if (f) doImport(f); e.target.value = ''; }} />
      </div>
      {msg && <p className="backup__msg">{msg}</p>}
      {operation === 'file' && <p><TriangleStepLoader label="読み込み中" /></p>}
      <p className="backup__note">
        ※復元はこの端末の現在のデータを上書きします。
      </p>

      <div className="backup__cloud">
        <p className="backup__lead">
          <b>☁️ 既存の暗号化バックアップから復元(読み取り専用)</b>
        </p>
        <p className="backup__note" style={{ borderLeft: '3px solid var(--amber,#fbbf24)', paddingLeft: 8 }}>
          <b>この旧方式は読み取り専用で、送信と端末間ライブ同期は行いません。</b>
        </p>
        <div className="backup__actions">
          <input className="modal__input backup__pass" type="password" value={pass}
                 placeholder="既存バックアップのパスフレーズ"
                 onChange={(e) => setPass(e.target.value)} autoComplete="off" />
          <button className="asset-btn" disabled={busy} onClick={restoreCloud}>クラウドから復元</button>
        </div>
        <p className="backup__note">
          保存済みパスフレーズ: {enabled ? 'あり' : 'なし'} ·
          既存復旧点: {lastCloudBackupAt() ? new Date(lastCloudBackupAt()).toLocaleString('ja-JP') : '未確認'} ·
          最終取込: {lastSyncInfo()?.lastPullAppliedAt
            ? new Date(lastSyncInfo()!.lastPullAppliedAt!).toLocaleString('ja-JP') : '未記録'}<br />
          復旧点より新しい変更はこの端末内だけです。
          パスフレーズを忘れると誰にも復元できません(本人含む)。
        </p>
        {lastSyncInfo()?.historyRestoreBlocked && <p className="backup__msg" role="status">
          取込み保留（履歴を検証できません・端末データは維持）
        </p>}
        {operation === 'cloud' && <p><TriangleStepLoader label="読み込み中" /></p>}
        {cloudMsg && <p className="backup__msg">{cloudMsg}</p>}
      </div>
    </div>
  );
};

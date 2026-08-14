import React, { useRef, useState } from 'react';
import { downloadBackup, restoreBackup, type BackupFile } from '../../lib/backup';
import { cloudRestore, getVaultPass, setVaultPass, lastCloudBackupAt, lastSyncInfo } from '../../lib/vault';

// Device-data backup UI (v10.3.2; auto-weekly added in v10.3.3 — see
// lib/backup.ts). Export/restore the only two device-local keys.

export const BackupCard: React.FC = () => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState('');
  const [pass, setPass] = useState('');
  const [cloudMsg, setCloudMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const enabled = !!getVaultPass();

  async function restoreCloud() {
    const p = pass.trim();
    if (!p) { setCloudMsg('復元にはパスフレーズを入力してください。'); return; }
    setBusy(true);
    try {
      const n = await cloudRestore(p);
      if (n > 0) {
        setVaultPass(p);
        setCloudMsg(`✅ ${n}項目をクラウドから復元しました。再読み込みします…`);
        window.setTimeout(() => location.reload(), 1200);
      } else {
        setCloudMsg('復元できるデータがありませんでした。');
      }
    } catch (e) {
      setCloudMsg(String(e instanceof Error ? e.message : e));
    } finally { setBusy(false); }
  }

  function doExport() {
    const n = downloadBackup(false);
    setMsg(n > 0
      ? `エクスポートしました(${n}項目)。iCloud Drive等の安全な場所に保存してください。`
      : 'まだ保存するデータがありません。');
  }

  function doImport(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as BackupFile;
        const n = restoreBackup(parsed);
        if (n === 0) { setMsg('このファイルはARGUSのバックアップではないようです。'); return; }
        setMsg(`${n}項目を復元しました(${parsed.exportedAt?.slice(0, 10)}のバックアップ)。再読み込みします…`);
        window.setTimeout(() => location.reload(), 1200);
      } catch {
        setMsg('読み込みに失敗しました。正しいバックアップファイルか確認してください。');
      }
    };
    reader.readAsText(file);
  }

  return (
    <div className="card guide-card">
      <p className="backup__lead">
        保有、判断記録、通知、学習履歴はこの端末に保存されます。
        「今すぐエクスポート」でバックアップJSONを安全な場所へ保存し、新しい端末では「インポート」で復元できます。
      </p>
      <div className="backup__actions">
        <button className="asset-btn asset-btn--primary" onClick={doExport}>
          今すぐエクスポート
        </button>
        <button className="asset-btn" onClick={() => fileRef.current?.click()}>
          インポート(バックアップから復元)
        </button>
        <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }}
               onChange={(e) => { const f = e.target.files?.[0]; if (f) doImport(f); e.target.value = ''; }} />
      </div>
      {msg && <p className="backup__msg">{msg}</p>}
      <p className="backup__note">
        ※復元はこの端末の現在のデータを上書きします。自動ダウンロードは行いません。
      </p>

      <div className="backup__cloud">
        <p className="backup__lead">
          <b>☁️ 既存の暗号化バックアップから復元(読み取り専用)</b>
        </p>
        <p className="backup__note" style={{ borderLeft: '3px solid var(--amber,#fbbf24)', paddingLeft: 8 }}>
          <b>現在、公開ブラウザからのクラウド送信と端末間ライブ同期は利用できません。</b>
          15秒ポーリングや失敗する送信再試行は行いません。既に保存済みの暗号文は読み取り・復元できます。
          新しい復旧点は上のJSONエクスポートで作成してください。
        </p>
        <div className="backup__actions">
          <input className="modal__input backup__pass" type="password" value={pass}
                 placeholder="既存バックアップのパスフレーズ"
                 onChange={(e) => setPass(e.target.value)} autoComplete="off" />
          <button className="asset-btn" disabled={busy} onClick={restoreCloud}>クラウドから復元</button>
        </div>
        <p className="backup__note">
          状態: クラウド読取のみ。保存済みパスフレーズ: {enabled ? 'あり' : 'なし'}。
          既存復旧点: {lastCloudBackupAt() ? new Date(lastCloudBackupAt()).toLocaleString('ja-JP') : '未確認'}。
          最終取込: {lastSyncInfo()?.lastPullAppliedAt
            ? new Date(lastSyncInfo()!.lastPullAppliedAt!).toLocaleString('ja-JP') : '未記録'}。
          データは端末上で暗号化され、サーバーとGitHubには<b>暗号文しか</b>渡りません。
          パスフレーズを忘れると誰にも復元できません(本人含む)。
        </p>
        {cloudMsg && <p className="backup__msg">{cloudMsg}</p>}
      </div>
    </div>
  );
};

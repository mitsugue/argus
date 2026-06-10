import React, { useRef, useState } from 'react';
import { downloadBackup, restoreBackup, type BackupFile } from '../../lib/backup';

// Device-data backup UI (v10.3.2; auto-weekly added in v10.3.3 — see
// lib/backup.ts). Export/restore the only two device-local keys.

export const BackupCard: React.FC = () => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState('');

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
        この端末に保存されているのは「ウォッチリスト+保有数量・取得単価」と「判断ログ」の2つだけです
        (それ以外は全てクラウド側)。<b>週に1回、アプリを開いた時に自動でバックアップファイルが
        ダウンロードフォルダに保存されます</b>。端末を替える時はそのファイルを「インポート」するだけです。
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
        ※復元はこの端末の現在のデータを上書きします。保有数量などの機微データを含むため
        ファイルの保管場所には注意(ARGUSのサーバーには送信されません)。自動バックアップは
        週1回・ファイル名 argus-backup-日付-auto.json です。
      </p>
    </div>
  );
};

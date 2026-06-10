import React, { useRef, useState } from 'react';

// Device-data backup (v10.3.2). ONLY two things live on this device:
//   argus.assets.v1       — watchlist + holdings (quantity / avg cost)
//   argus.judgmentLog.v1  — the daily judgment log
// Everything else (code, prediction ledger, prices, AI runs) already lives in
// the cloud. Export downloads one JSON file; import restores it on a new
// device. No server involved — the file never leaves the user's hands.

const KEYS = ['argus.assets.v1', 'argus.judgmentLog.v1'] as const;

interface BackupFile {
  app: 'argus';
  exportedAt: string;
  version: string;
  data: Record<string, unknown>;
}

export const BackupCard: React.FC = () => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState('');

  function doExport() {
    const data: Record<string, unknown> = {};
    for (const k of KEYS) {
      try {
        const raw = localStorage.getItem(k);
        if (raw) data[k] = JSON.parse(raw);
      } catch { /* skip unreadable key */ }
    }
    const payload: BackupFile = {
      app: 'argus',
      exportedAt: new Date().toISOString(),
      version: __APP_VERSION__,
      data,
    };
    const date = new Date().toISOString().slice(0, 10);
    const blob = new Blob([JSON.stringify(payload, null, 1)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `argus-backup-${date}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    setMsg(`エクスポートしました(${Object.keys(data).length}項目)。このファイルを安全な場所(iCloud Drive等)に保存してください。`);
  }

  function doImport(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as BackupFile;
        if (parsed.app !== 'argus' || !parsed.data) {
          setMsg('このファイルはARGUSのバックアップではないようです。');
          return;
        }
        let n = 0;
        for (const k of KEYS) {
          if (parsed.data[k] != null) {
            localStorage.setItem(k, JSON.stringify(parsed.data[k]));
            n++;
          }
        }
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
        (それ以外は全てクラウド側)。端末の買い替え・故障に備えて、ときどきエクスポートしてください。
      </p>
      <div className="backup__actions">
        <button className="asset-btn asset-btn--primary" onClick={doExport}>
          エクスポート(バックアップを保存)
        </button>
        <button className="asset-btn" onClick={() => fileRef.current?.click()}>
          インポート(バックアップから復元)
        </button>
        <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }}
               onChange={(e) => { const f = e.target.files?.[0]; if (f) doImport(f); e.target.value = ''; }} />
      </div>
      {msg && <p className="backup__msg">{msg}</p>}
      <p className="backup__note">
        ※復元はこの端末の現在のデータを上書きします。保有数量などの機微データはファイル内に含まれるため、
        ファイルの保管場所には注意してください(ARGUSのサーバーには送信されません)。
      </p>
    </div>
  );
};

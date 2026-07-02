import React, { useRef, useState } from 'react';
import { downloadBackup, restoreBackup, type BackupFile } from '../../lib/backup';
import { cloudBackupNow, cloudRestore, getVaultPass, setVaultPass, lastCloudBackupAt, lastSyncInfo } from '../../lib/vault';

// Device-data backup UI (v10.3.2; auto-weekly added in v10.3.3 — see
// lib/backup.ts). Export/restore the only two device-local keys.

export const BackupCard: React.FC = () => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState('');
  const [pass, setPass] = useState('');
  const [cloudMsg, setCloudMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const enabled = !!getVaultPass();

  async function enableCloud() {
    const p = pass.trim();
    if (p.length < 8) { setCloudMsg('パスフレーズは8文字以上にしてください(長いほど安全)。'); return; }
    setBusy(true);
    try {
      setVaultPass(p);
      const note = await cloudBackupNow(p);
      setCloudMsg(`✅ 有効化し、初回バックアップを送信しました。${note} ※このパスフレーズを忘れると復元できません。`);
      setPass('');
    } catch (e) {
      setCloudMsg(`送信に失敗しました(${e instanceof Error ? e.message : e})。後で自動再試行されます。`);
    } finally { setBusy(false); }
  }

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
        ※復元はこの端末の現在のデータを上書きします。ファイル自動バックアップは週1回
        (argus-backup-日付-auto.json)。
      </p>

      <div className="backup__cloud">
        <p className="backup__lead">
          <b>☁️ クラウド自動バックアップ＋端末間同期</b> — パスフレーズを決めて有効化すると、
          以後は<b>自動で暗号化バックアップがクラウド(GitHub)に保存</b>され、さらに
          <b>同じパスフレーズを設定した端末どうしが自動で同期</b>します。
        </p>
        <p className="backup__note" style={{ borderLeft: '3px solid var(--amber,#fbbf24)', paddingLeft: 8 }}>
          <b>⚠ アプリとウェブを常に同期させるには、両方で同じパスフレーズを「有効化」してください。</b>
          片方だけだと同期しません。両方で有効化すれば、<b>ウォッチリストは銘柄ごとにマージ同期</b>されます:
          どちらで追加しても両方に現れ、削除も両方に反映され、丸ごと上書きで消えることはありません
          (約5〜20秒・タブ/アプリに戻ると即時取得。ウォッチリストは初回の「クラウドから復元」不要)。
          判断ログ・取引記録・リサーチノートは「新しい方を丸ごと採用」のため、
          <b>それらのデータが既にある端末では初回のみ「クラウドから復元」を推奨</b>します。
        </p>
        <div className="backup__actions">
          <input className="modal__input backup__pass" type="password" value={pass}
                 placeholder={enabled ? '復元 / パスフレーズ変更用に入力' : 'パスフレーズ(8文字以上・忘れない物)'}
                 onChange={(e) => setPass(e.target.value)} autoComplete="off" />
          <button className="asset-btn asset-btn--primary" disabled={busy} onClick={enableCloud}>
            {enabled ? '今すぐ送信 / 変更' : '有効化して初回送信'}
          </button>
          <button className="asset-btn" disabled={busy} onClick={restoreCloud}>クラウドから復元</button>
        </div>
        <p className="backup__note">
          状態: {enabled
            ? `✅ この端末は同期 有効(最終送信 ${lastCloudBackupAt() ? new Date(lastCloudBackupAt()).toLocaleString('ja-JP') : '—'}・最終同期チェック ${(() => { const s = lastSyncInfo(); return s ? `${new Date(s.at).toLocaleTimeString('ja-JP')} ${s.outcome === 'applied' ? '=取込あり' : s.outcome === 'pushed' ? '=送信' : s.merged ? '=一致' : ''}` : '—'; })()})。両端末で有効化していれば約5〜20秒で同期。恒久保存は1日6回(平日 9/12/16/19/22時・深夜2時)。`
            : '⚠ この端末は同期 未設定(上でパスフレーズを決めて有効化。もう片方の端末でも同じパスフレーズで有効化が必要)。'}
          データは端末上で暗号化され、サーバーとGitHubには<b>暗号文しか</b>渡りません。
          パスフレーズを忘れると誰にも復元できません(本人含む)。古い世代は自動削除(直近8世代保持)。
        </p>
        {cloudMsg && <p className="backup__msg">{cloudMsg}</p>}
      </div>
    </div>
  );
};

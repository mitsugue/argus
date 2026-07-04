import React from 'react';
import type { UseAssets } from '../../hooks/useAssets';
import { latestExposure } from '../../lib/positionExposureShare';
import {
  applyImport, createSnapshot, downloadPortfolioBackup, listSnapshots,
  previewImport, syncMeta, type ImportPreview,
} from '../../lib/portfolioSync';

// V11.9.0 — PORTFOLIO SYNC & BACKUP (Core Portfolio). Owner-facing truth about
// where holdings live + export/import/snapshot tools. The cloud only ever sees
// ciphertext (passphrase vault); server-side plaintext sync stays disabled.

const fmtTs = (iso?: string) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—');

export const PortfolioSyncCard: React.FC<{ assetsApi: UseAssets; appVersion: string }> = ({ assetsApi, appVersion }) => {
  const { assets, add, updateHolding } = assetsApi;
  const [, bump] = React.useReducer((x: number) => x + 1, 0);
  const [preview, setPreview] = React.useState<ImportPreview | null>(null);
  const [applied, setApplied] = React.useState<string | null>(null);
  const [snapMsg, setSnapMsg] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  const meta = syncMeta();
  const snaps = listSnapshots();
  const vaultOn = typeof window !== 'undefined' && !!localStorage.getItem('argus.vaultPass.v1');

  const onFile = async (f: File | undefined) => {
    setApplied(null);
    if (!f) return;
    if (f.size > 5_000_000) { setPreview({ ok: false, errorJa: 'ファイルが大きすぎます(5MB上限)。', withQuantity: 0, watchOnly: 0, snapshots: 0, symbols: [] }); return; }
    const text = await f.text();
    setPreview(previewImport(text));
  };

  const onApply = (mode: 'merge' | 'replace') => {
    if (!preview?.ok || !preview.file) return;
    const r = applyImport(preview.file, assets, mode, { updateHolding, add: add as never });
    setApplied(`${mode === 'merge' ? '統合' : '置換'}完了: 更新${r.updated}件 / 追加${r.added}件 / スナップショット取込${r.snapshotsMerged}件`);
    setPreview(null);
    if (fileRef.current) fileRef.current.value = '';
    bump();
  };

  const onSnapshot = () => {
    const pe = latestExposure();
    if (!pe) { setSnapMsg('先にTodayページを開いて計算させてください。'); return; }
    const s = createSnapshot(pe, { appVersion });
    setSnapMsg(s ? `スナップショット作成: ${s.asOf}(端末内・暗号化バックアップに含まれます)`
      : '保有数量・価格が揃っていないため、スナップショットは作成できません(捏造しません)。');
    bump();
  };

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">PORTFOLIO SYNC & BACKUP</span>
        <span className="section-head__count">v11.9 · 端末内+暗号化バックアップ</span>
      </div>
      <div className="card cmd-alloc">
        <div className="cmd-alloc__note" style={{ fontSize: 12, color: 'var(--text-sub)' }}>
          保存モード: <b>{vaultOn ? '端末内 + パスフレーズ暗号化バックアップ(端末間同期 有効)' : '端末内のみ(Local only)'}</b>
        </div>
        <div className="cmd-alloc__note">
          現在、保有データはこの端末内に保存されています。サーバーには送信されません。
          {!vaultOn && ' Guideの「バックアップと同期」でパスフレーズを設定すると、Mac/iPhone/iPad間で暗号化同期されます。'}
        </div>
        <div className="cmd-alloc__note">
          クラウド同期(平文)は安全な認証が整うまで無効です。将来、Mac/iPhone/iPadで同期できるようにするため、同期用データ構造だけ先に準備しています。
        </div>
        <div className="cmd-alloc__note">
          最終スナップショット: {fmtTs(meta.lastSnapshotAt)}(計{snaps.length}件) / 最終エクスポート: {fmtTs(meta.lastExportAt)} / 最終インポート: {fmtTs(meta.lastImportAt)}
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0 4px' }}>
          <button type="button" onClick={() => { downloadPortfolioBackup(assets, appVersion); bump(); }}
                  style={btn}>バックアップJSONを書き出す</button>
          <button type="button" onClick={() => fileRef.current?.click()} style={btn}>JSONを読み込む</button>
          <button type="button" onClick={onSnapshot} style={btn}>今すぐスナップショット作成</button>
          <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }}
                 onChange={(e) => void onFile(e.target.files?.[0])} />
        </div>
        <p className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)' }}>
          このファイルには保有数量・取得単価などの個人投資情報が含まれます。iCloud Drive等の安全な場所に保管してください。
        </p>

        {preview && !preview.ok && (
          <p className="cmd-alloc__note" style={{ color: 'var(--value-negative)' }}>読み込み不可: {preview.errorJa}</p>
        )}
        {preview?.ok && (
          <div className="cmd-alloc__note" style={{ border: '1px solid var(--line)', borderRadius: 6, padding: 8 }}>
            <b>インポート内容の確認</b> — 保有あり{preview.withQuantity}件 / 監視のみ{preview.watchOnly}件 /
            スナップショット{preview.snapshots}件
            {preview.symbols.length > 0 && <> ・銘柄例: {preview.symbols.join(' / ')}</>}
            <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
              <button type="button" style={btn} onClick={() => onApply('merge')}>統合(ファイルの銘柄だけ更新)</button>
              <button type="button" style={btn} onClick={() => onApply('replace')}>置換(ファイルに無い銘柄の数量はクリア)</button>
              <button type="button" style={btnGhost} onClick={() => { setPreview(null); if (fileRef.current) fileRef.current.value = ''; }}>キャンセル</button>
            </div>
            <p style={{ margin: '4px 0 0', fontSize: 10, color: 'var(--text-faint)' }}>
              どちらのモードも銘柄そのものは削除しません。適用前にこのプレビューで内容を確認してください。
            </p>
          </div>
        )}
        {applied && <p className="cmd-alloc__note" style={{ color: 'var(--value-positive)' }}>{applied}</p>}
        {snapMsg && <p className="cmd-alloc__note">{snapMsg}</p>}

        {snaps.length > 0 && (
          <div className="cmd-alloc__note">
            スナップショット履歴: {snaps.slice(0, 5).map((s) => s.asOf).join(' / ')}{snaps.length > 5 ? ` 他${snaps.length - 5}件` : ''}
            <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>
              (復元 = バックアップJSONを書き出して新端末で「JSONを読み込む」)
            </span>
          </div>
        )}
        <p className="cmd-alloc__note" style={{ fontSize: 10 }}>
          日次スナップショットはTodayを開くと自動で1日1回、端末内に記録されます(あの日ARGUSが何を言っていたかの将来検証用・売買指示ではありません)。
        </p>
      </div>
    </section>
  );
};

const btn: React.CSSProperties = {
  fontSize: 12, cursor: 'pointer', background: 'transparent', color: 'var(--accent)',
  border: '1px solid var(--line)', borderRadius: 6, padding: '4px 10px',
};
const btnGhost: React.CSSProperties = { ...btn, color: 'var(--text-faint)' };

export default PortfolioSyncCard;

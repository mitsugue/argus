import React from 'react';
import type { UseAssets } from '../../hooks/useAssets';
import { latestExposure } from '../../lib/positionExposureShare';
import {
  applyImport, createSnapshot, downloadPortfolioBackup, listSnapshots,
  previewImport, syncMeta, type ImportPreview,
} from '../../lib/portfolioSync';
import { assessBackupSafety, runRecoveryDrill, drillMeta, LEVEL_TONE } from '../../lib/backupSafety';
import { certifiedCompleteExportAt } from '../../lib/backupMeta';

// Owner-facing LOCAL BACKUP & RESTORE: where holdings live plus
// export/import/snapshot tools. Browser cloud push remains unavailable.

const fmtTs = (iso?: string) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—');

export const PortfolioSyncCard: React.FC<{ assetsApi: UseAssets; appVersion: string }> = ({ assetsApi, appVersion }) => {
  const { assets, add, updateHolding } = assetsApi;
  const [, bump] = React.useReducer((x: number) => x + 1, 0);
  const [preview, setPreview] = React.useState<ImportPreview | null>(null);
  const [applied, setApplied] = React.useState<string | null>(null);
  const [snapMsg, setSnapMsg] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  const meta = syncMeta();
  const completeExportAt = certifiedCompleteExportAt(meta);
  const snaps = listSnapshots();
  const safety = assessBackupSafety(assets);
  const [drillMsg, setDrillMsg] = React.useState<string | null>(drillMeta().lastDrillResultJa ?? null);
  const vaultOn = typeof window !== 'undefined' && !!localStorage.getItem('argus.vaultPass.v1');

  const onFile = async (f: File | undefined) => {
    setApplied(null);
    if (!f) return;
    if (f.size > 5_000_000) { setPreview({ ok: false, errorJa: 'ファイルが大きすぎます(5MB上限)。', withQuantity: 0, watchOnly: 0, snapshots: 0, decisions: 0, symbols: [] }); return; }
    const text = await f.text();
    setPreview(previewImport(text));
  };

  const onApply = (mode: 'merge' | 'replace') => {
    if (!preview?.ok || !preview.file) return;
    if (mode === 'replace' && !window.confirm(
      '置換モード: ファイルに無い銘柄の保有数量はクリアされます(銘柄自体は残ります)。実行しますか?')) return;
    const r = applyImport(preview.file, assets, mode, { updateHolding, add: add as never });
    setApplied(`${mode === 'merge' ? '統合' : '置換'}完了: 更新${r.updated}件 / 追加${r.added}件 / スナップショット取込${r.snapshotsMerged}件 / 判断記録取込${r.decisionAuditMerged}件`);
    setPreview(null);
    if (fileRef.current) fileRef.current.value = '';
    bump();
  };

  const onSnapshot = () => {
    const pe = latestExposure();
    if (!pe) { setSnapMsg('先にTodayページを開いて計算させてください。'); return; }
    const s = createSnapshot(pe, { appVersion });
    setSnapMsg(s ? `スナップショット作成: ${s.asOf}(この端末内に保存。保護するにはJSONを書き出してください)`
      : '保有数量・価格が揃っていないため、スナップショットは作成できません(捏造しません)。');
    bump();
  };

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">LOCAL BACKUP &amp; RESTORE</span>
        <span className="section-head__count">端末内 + 手動JSON</span>
      </div>
      <div className="card cmd-alloc">
        {/* BACKUP SAFETY (v11.16.0) — 保護状態の見える化(端末内判定) */}
        <div className="cmd-alloc__note" style={{ fontSize: 12.5 }}>
          <b style={{ color: LEVEL_TONE[safety.protectionLevel], border: `1px solid ${LEVEL_TONE[safety.protectionLevel]}`,
                      borderRadius: 999, padding: '0 8px' }}>
            {safety.protectionLevelJa}
          </b>
          <span style={{ marginLeft: 6, color: 'var(--text-sub)' }}>{safety.statusJa}</span>
        </div>
        {safety.riskJa && (
          <div className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)' }}>{safety.riskJa}</div>
        )}
        <div className="cmd-alloc__note">
          次の一歩: {safety.nextStepJa}
          <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>
            復元確認: {safety.restoreVerified ? `済(${(safety.lastDrillAt ?? '').slice(0, 10)})` : '未'}
          </span>
        </div>
        <details>
          <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>何が消える可能性があるか</summary>
          <p className="cmd-alloc__note" style={{ fontSize: 10.5 }}>{safety.whatCanBeLostJa}</p>
        </details>

        <div className="cmd-alloc__note" style={{ fontSize: 12, color: 'var(--text-sub)' }}>
          保存モード: <b>端末内 + 手動JSONエクスポート</b>
          {vaultOn && ' / 既存の暗号化復旧点は読み取り可能'}
        </div>
        <div className="cmd-alloc__note">
          現在、保有データはこの端末内に保存されています。公開ブラウザからサーバーへは送信されません。
        </div>
        <div className="cmd-alloc__note">
          クラウド送信・端末間ライブ同期は無効です。既存暗号文の読み取り/復元と、ローカルexport/importだけ利用できます。
        </div>
        <div className="cmd-alloc__note">
          最終スナップショット: {fmtTs(meta.lastSnapshotAt)}(計{snaps.length}件) / 最終完全バックアップ: {fmtTs(completeExportAt)} / ポートフォリオのみ書出: {fmtTs(meta.lastPortfolioExportAt)} / ポートフォリオ取込: {fmtTs(meta.lastImportAt)}
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0 4px' }}>
          <button type="button" onClick={() => { downloadPortfolioBackup(assets, appVersion); bump(); }}
                  style={btn}>ポートフォリオのみJSONを書き出す</button>
          <button type="button" onClick={() => fileRef.current?.click()} style={btn}>ポートフォリオJSONを読み込む</button>
          <button type="button" onClick={onSnapshot} style={btn}>今すぐスナップショット作成</button>
          <button type="button" style={btn}
                  onClick={() => { const r = runRecoveryDrill(assets, appVersion); setDrillMsg(r.resultJa); bump(); }}>
            復元ドリルを実行(非破壊)</button>
          <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }}
                 onChange={(e) => void onFile(e.target.files?.[0])} />
        </div>
        <p className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)' }}>
          これは保有・スナップショット・判断記録だけの部分ファイルです。取引・調査・FIRE Core・通知等の完全保護には、上の「完全バックアップJSONを書き出す」を使用してください。
        </p>

        {preview && !preview.ok && (
          <p className="cmd-alloc__note" style={{ color: 'var(--value-negative)' }}>読み込み不可: {preview.errorJa}</p>
        )}
        {preview?.ok && (
          <div className="cmd-alloc__note" style={{ border: '1px solid var(--line)', borderRadius: 6, padding: 8 }}>
            <b>インポート内容の確認</b> — 保有あり{preview.withQuantity}件 / 監視のみ{preview.watchOnly}件 /
            スナップショット{preview.snapshots}件 / 判断記録{preview.decisions}件
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
        {drillMsg && <p className="cmd-alloc__note">{drillMsg}</p>}

        {snaps.length > 0 && (
          <div className="cmd-alloc__note">
            スナップショット履歴: {snaps.slice(0, 5).map((s) => s.asOf).join(' / ')}{snaps.length > 5 ? ` 他${snaps.length - 5}件` : ''}
            <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>
              (部分復元 = ポートフォリオのみJSONを書き出して新端末で読み込む)
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

import React from 'react';
import {ownerVaultProtection} from '../../lib/ownerVault';
import type { AssetItem } from '../../types/assetItem';
import { assessBackupSafety, drillMeta } from '../../lib/backupSafety';
import { syncMeta } from '../../lib/portfolioSync';
import { certifiedCompleteExportAt } from '../../lib/backupMeta';
import { lastCloudBackupAt, lastSyncInfo } from '../../lib/vault';
import { buildRestoreReadiness } from '../../domain/restoreReadiness';
import './SystemDecision.css';

const fmt = (value?: string | number | null) => {
  if (!value) return '未記録';
  const date = new Date(typeof value === 'number' ? value : value);
  return Number.isNaN(date.getTime()) ? '未記録' : date.toLocaleString('ja-JP');
};

export const BackupStatusOverview: React.FC<{ assets: AssetItem[] }> = ({ assets }) => {
  const [ownerPoint,setOwnerPoint]=React.useState<Awaited<ReturnType<typeof ownerVaultProtection>>>(null);
  React.useEffect(()=>{
    let active=true;let revision=0;
    const refresh=()=>{const id=++revision;void ownerVaultProtection().then(value=>{if(active&&id===revision)setOwnerPoint(value);});};
    const edited=()=>{setOwnerPoint(previous=>previous?{...previous,current:false}:null);refresh();};
    const timer=window.setInterval(()=>{if(!document.hidden)refresh();},15000);
    refresh();window.addEventListener('argus:vault-saved',refresh);window.addEventListener('argus:data-synced',edited);window.addEventListener('argus:local-data-edited',edited);window.addEventListener('focus',refresh);window.addEventListener('storage',edited);
    return()=>{active=false;window.clearInterval(timer);window.removeEventListener('argus:vault-saved',refresh);window.removeEventListener('argus:data-synced',edited);window.removeEventListener('argus:local-data-edited',edited);window.removeEventListener('focus',refresh);window.removeEventListener('storage',edited);};
  },[assets]);
  const safety = assessBackupSafety(assets);
  const sync = lastSyncInfo();
  const local = syncMeta();
  const completeExportAt = certifiedCompleteExportAt(local);
  const drill = drillMeta();
  const readiness = buildRestoreReadiness(safety);
  const readinessTone = readiness.state === 'ready' ? 'var(--value-positive)'
    : readiness.state === 'no_data' ? 'var(--text-faint)'
    : readiness.state === 'recovery_point_required' ? 'var(--value-negative)'
    : 'var(--amber, #fbbf24)';
  const recoveryTimes = [
    sync?.lastPushAt || lastCloudBackupAt(),
    completeExportAt,
  ].map((value) => value ? new Date(value).getTime() : 0).filter((value) => Number.isFinite(value) && value > 0);
  const latestRecoveryPoint = recoveryTimes.length ? Math.max(...recoveryTimes) : null;

  if(ownerPoint)return <section className="backup-overview" aria-label="暗号化保存点の確認状況">
    <div className="backup-overview__command"><span>端末データの保存点</span><strong style={{color:ownerPoint.current?'var(--value-positive)':'var(--amber, #fbbf24)'}}>{ownerPoint.current?'保存・復号照合済み':'保存点あり・変更の保存待ち'}</strong>
      <small>{ownerPoint.current?'現在の保存対象データと、非公開保存先から読み戻して復号した内容が一致しています。端末間の自動統合は行いません。':'暗号化保存点の後に端末データが変わっています。以前の保存点は残っていますが、現在の変更はまだ照合済みではありません。'}</small></div>
    <div className="backup-overview__grid"><article><span>作成時点</span><strong>{fmt(ownerPoint.exportedAt)}</strong></article>
      <article><span>遠隔保存・読み戻し確認</span><strong>{fmt(ownerPoint.savedAt*1000)}</strong></article>
      <article className="backup-overview__wide"><span>次の確認</span><strong>{ownerPoint.current?'別端末では接続キーとパスフレーズで保存点を開き、復元内容を確認してください。実機受入は別の確認です。':'現在分を暗号化保存し、読み戻し照合を確認してください。既存の保存点を削除する必要はありません。'}</strong></article></div>
  </section>;

  return <section className="backup-overview" aria-labelledby="backup-status">
    <div className="backup-overview__command">
      <span id="backup-status">RESTORE READINESS</span>
      <strong style={{ color: readinessTone }}>
        {readiness.label}
      </strong>
      <small>{readiness.summary}</small>
    </div>
    {sync?.historyRestoreBlocked && <p role="status">
      クラウド履歴の取込みを保留中です。保存済みデータは維持しています。
      バックアップの形式確認・移行が必要です。
    </p>}
    <div className="backup-overview__grid">
      <article><span>RECOVERY SOURCES</span>
        <strong>{readiness.sources.length ? readiness.sources.join(' / ') : 'NONE VERIFIED'}</strong></article>
      <article><span>LATEST RECOVERY POINT</span><strong>{fmt(latestRecoveryPoint)}</strong></article>
      <article><span>INTEGRITY</span>
        <strong>{readiness.integrity}</strong>
        {!!safety.riskFlags.length && <small>{safety.riskFlags.length} risk flags</small>}
      </article>
      <article><span>LAST RESTORE DRILL</span>
        <strong>{safety.restoreVerified ? `PASS · ${fmt(drill.lastDrillAt)}` : 'NOT VERIFIED'}</strong></article>
      <article className="backup-overview__wide"><span>DATA AT RISK</span>
        <strong>{readiness.atRisk}</strong></article>
      <article className="backup-overview__wide"><span>NEXT ACTION</span>
        <strong>{readiness.nextAction}</strong></article>
    </div>
  </section>;
};

import React from 'react';
import type { AssetItem } from '../../types/assetItem';
import { assessBackupSafety, drillMeta } from '../../lib/backupSafety';
import { syncMeta } from '../../lib/portfolioSync';
import { lastCloudBackupAt, lastSyncInfo } from '../../lib/vault';
import { buildRestoreReadiness } from '../../domain/restoreReadiness';
import './SystemDecision.css';

const fmt = (value?: string | number | null) => {
  if (!value) return '未記録';
  const date = new Date(typeof value === 'number' ? value : value);
  return Number.isNaN(date.getTime()) ? '未記録' : date.toLocaleString('ja-JP');
};

export const BackupStatusOverview: React.FC<{ assets: AssetItem[] }> = ({ assets }) => {
  const safety = assessBackupSafety(assets);
  const sync = lastSyncInfo();
  const local = syncMeta();
  const drill = drillMeta();
  const readiness = buildRestoreReadiness(safety);
  const readinessTone = readiness.state === 'ready' ? 'var(--value-positive)'
    : readiness.state === 'no_data' ? 'var(--text-faint)'
    : readiness.state === 'recovery_point_required' ? 'var(--value-negative)'
    : 'var(--amber, #fbbf24)';
  const recoveryTimes = [
    sync?.lastPushAt || lastCloudBackupAt(),
    local.lastExportAt,
  ].map((value) => value ? new Date(value).getTime() : 0).filter((value) => Number.isFinite(value) && value > 0);
  const latestRecoveryPoint = recoveryTimes.length ? Math.max(...recoveryTimes) : null;

  return <section className="backup-overview" aria-labelledby="backup-status">
    <div className="backup-overview__command">
      <span id="backup-status">RESTORE READINESS</span>
      <strong style={{ color: readinessTone }}>
        {readiness.label}
      </strong>
      <small>{readiness.summary}</small>
    </div>
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

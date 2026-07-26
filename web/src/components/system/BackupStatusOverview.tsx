import React from 'react';
import type { AssetItem } from '../../types/assetItem';
import { assessBackupSafety, drillMeta, LEVEL_TONE } from '../../lib/backupSafety';
import { syncMeta } from '../../lib/portfolioSync';
import { lastCloudBackupAt, lastSyncInfo } from '../../lib/vault';
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
  const protectedState = safety.protectionLevel === 'protected';
  const hasProtectedData = safety.protectionLevel !== 'unknown';

  return <section className="backup-overview" aria-labelledby="backup-status">
    <div className="backup-overview__command">
      <span id="backup-status">BACKUP STATUS</span>
      <strong style={{ color: LEVEL_TONE[safety.protectionLevel] }}>
        {protectedState ? 'PROTECTED' : safety.protectionLevelJa}
      </strong>
      <small>{safety.statusJa}</small>
    </div>
    <div className="backup-overview__grid">
      <article><span>LAST LOCAL SAVE</span><strong>{fmt(local.lastSnapshotAt)}</strong></article>
      <article><span>LAST CLOUD SYNC</span>
        <strong>{fmt(sync?.lastPushAt || lastCloudBackupAt())}</strong></article>
      <article><span>INTEGRITY</span>
        <strong>{!hasProtectedData ? '対象データなし'
          : safety.riskFlags.length ? `${safety.riskFlags.length} risk flags` : 'OK'}</strong></article>
      <article><span>RESTORE TESTED</span>
        <strong>{!hasProtectedData ? '対象データなし'
          : safety.restoreVerified ? `PASS · ${fmt(drill.lastDrillAt)}` : 'NOT VERIFIED'}</strong></article>
      <article className="backup-overview__wide"><span>NEXT ACTION</span>
        <strong>{safety.nextStepJa}</strong></article>
    </div>
  </section>;
};

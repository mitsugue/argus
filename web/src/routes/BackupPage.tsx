import React from 'react';
import { useAssets } from '../hooks/useAssets';
import { PortfolioSyncCard } from '../components/dashboard/PortfolioSyncCard';
import { BackupCard } from '../components/guide/BackupCard';
import { BackupStatusOverview } from '../components/system/BackupStatusOverview';

// Lean v13: backup and recovery live under Settings. The public browser can
// export/import local JSON and read/restore an existing encrypted envelope;
// cloud push and live sync are intentionally unavailable.

export const BackupSettingsPanel: React.FC<{ initiallyOpen?: boolean }> = ({ initiallyOpen = false }) => {
  const assetsApi = useAssets();
  const [actionsOpen, setActionsOpen] = React.useState(initiallyOpen);

  React.useEffect(() => {
    setActionsOpen(initiallyOpen);
  }, [initiallyOpen]);

  return (
    <section id="settings-recovery" aria-label="Backup and recovery">
      <BackupStatusOverview assets={assetsApi.assets} />
      <details className="backup-actions" open={actionsOpen}
        onToggle={(event) => setActionsOpen(event.currentTarget.open)}>
        <summary>Manual export / import / restore actions</summary>
        {actionsOpen && <div className="backup-actions__body">
      {/* ① 既存暗号化バックアップのread/restore — public push is unavailable. */}
      <section>
        <div className="section-head">
          <span className="section-head__title">暗号化バックアップ / 読み取り復元</span>
          <span className="section-head__count">クラウド送信なし · 既存暗号文のみ</span>
        </div>
        <BackupCard />
      </section>

      {/* ② portfolio-only export/import plus complete-backup protection/drill status */}
      <PortfolioSyncCard assetsApi={assetsApi} appVersion={__APP_VERSION__} />

      <p style={{ margin: '4px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
        バックアップの保護状態(保護済み/一部保護/未保護)と復元ドリルの結果は上のBACKUP SAFETYに表示されます。
        サーバーはパスフレーズの有無・保護状態・バックアップ内容を一切知りません。
      </p>
        </div>}
      </details>
    </section>
  );
};

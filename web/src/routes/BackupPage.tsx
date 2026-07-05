import React from 'react';
import { PageShell } from './PageShell';
import { useAssets } from '../hooks/useAssets';
import { PortfolioSyncCard } from '../components/dashboard/PortfolioSyncCard';
import { BackupCard } from '../components/guide/BackupCard';

// V11.19.1 — Backup page (owner request 2026-07-05): バックアップ関連の操作が
// ④Core Portfolio(PORTFOLIO SYNC & BACKUP)と⑤Guide(バックアップ/パスフレーズ)に
// 散在していたため、専用ページに集約。ナビ下側・Guideの隣。
// 中身は既存コンポーネントの移設であり、保存仕様・暗号化仕様は一切変更しない。

export const BackupPage: React.FC = () => {
  const assetsApi = useAssets();

  return (
    <PageShell
      title="Backup"
      subtitle="保有・判断記録・通知・学習履歴のバックアップ操作をここに集約。①パスフレーズで暗号化バックアップ(端末間同期・クラウドには暗号文のみ)②バックアップJSONの書き出し/読み込み③スナップショット④復元ドリル(非破壊)。パスフレーズは忘れると復元不能・チャット等に絶対貼らないでください。"
    >
      {/* ① 暗号化バックアップ(パスフレーズ)設定 — Guideから移設 */}
      <section>
        <div className="section-head">
          <span className="section-head__title">暗号化バックアップ / 端末間同期</span>
          <span className="section-head__count">パスフレーズ · 暗号文のみクラウドへ</span>
        </div>
        <BackupCard />
      </section>

      {/* ② JSONエクスポート/インポート・スナップショット・復元ドリル — Core Portfolioから移設 */}
      <PortfolioSyncCard assetsApi={assetsApi} appVersion={__APP_VERSION__} />

      <p style={{ margin: '4px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
        バックアップの保護状態(保護済み/一部保護/未保護)と復元ドリルの結果は上のBACKUP SAFETYに表示されます。
        サーバーはパスフレーズの有無・保護状態・バックアップ内容を一切知りません。
      </p>
    </PageShell>
  );
};

export default BackupPage;

import React, { useEffect, useState } from 'react';
import { PageShell } from './PageShell';
import { AIReview } from '../components/dashboard/AIReview';
import { ProHandoffButton } from '../components/dashboard/ProHandoffButton';
import { AssetDeskList, type AssetFocusIntent } from '../components/assetDesk/AssetDeskList';
import { DownsideIncidentCard } from '../components/dashboard/DownsideIncidentCard';
import { EntityProfileEditor } from '../components/dashboard/EntityProfileEditor';
import { AddAssetModal } from '../components/dashboard/AddAssetModal';
import { TradeJournalCard } from '../components/dashboard/TradeJournalCard';
import { useAssets } from '../hooks/useAssets';
import { useLocale, t } from '../i18n';
import '../components/dashboard/Dashboard.css';

// V12.2.12 — ASSET DESK(route key `watchlist` 不変): 個別銘柄情報の唯一の正本。
// 判断はdomain/assetDecision+useAssetIntel(publish:false)経由でTodayと同一。
// ページ全体機能(AI総評/急落カード/追加・削除/プロファイル/売買記録/Handoff)は
// 旧Watchlistから残置。Portfolio ExposureとWhat-ifはPositions & Riskへ移動済み。

function ageLabel(ts: number, nowMs: number): string {
  const m = Math.max(0, Math.round((nowMs - ts) / 60000));
  return m < 1 ? 'just now' : `${m}m ago`;
}

interface Props {
  /** Today等からのdeep-link(展開+スクロール)。App.tsxのpendingAssetFocus。 */
  assetFocus?: AssetFocusIntent | null;
}

export const Watchlist: React.FC<Props> = ({ assetFocus }) => {
  useLocale();   // re-render on locale switch
  const { assets, add, remove, reorderGenre, updateHolding } = useAssets();
  const [addOpen, setAddOpen] = useState(false);
  const [nonce, setNonce] = useState(0);            // rescan → remounts the data section
  const [updatedAt, setUpdatedAt] = useState(() => Date.now());
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(t);
  }, []);

  function rescan() {
    setNonce((n) => n + 1);
    setUpdatedAt(Date.now());
    setNowMs(Date.now());
  }

  return (
    <PageShell
      title="ASSET DESK"
      subtitle="保有・監視中の個別資産について、現在の判断と根拠を確認します。"
    >
      <AIReview />

      <DownsideIncidentCard />

      <div className="asset-toolbar asset-toolbar--end">
        <span className="asset-toolbar__age">{t('wl.updated')} {ageLabel(updatedAt, nowMs)}</span>
        <button className="asset-btn" onClick={rescan} aria-label="Rescan (rule-based refresh, no AI run)">{t('wl.rescan')}</button>
        <button className="asset-btn asset-btn--primary" onClick={() => setAddOpen(true)} aria-label="Add asset">{t('wl.addAsset')}</button>
      </div>

      <AssetDeskList
        key={nonce}
        assets={assets}
        onReorder={reorderGenre}
        onRemove={remove}
        onUpdateHolding={updateHolding}
        focus={assetFocus}
      />

      <EntityProfileEditor />

      <TradeJournalCard assets={assets} />

      <div className="watch-toolbar">
        <ProHandoffButton />
      </div>

      {addOpen && <AddAssetModal onClose={() => setAddOpen(false)} onAdd={add} />}
    </PageShell>
  );
};

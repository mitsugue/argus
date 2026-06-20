import React, { useEffect, useMemo, useState } from 'react';
import { PageShell } from './PageShell';
import { AIReview } from '../components/dashboard/AIReview';
import { ProHandoffButton } from '../components/dashboard/ProHandoffButton';
import { AssetStrategySection } from '../components/dashboard/AssetStrategySection';
import { AddAssetModal } from '../components/dashboard/AddAssetModal';
import { TradeJournalCard } from '../components/dashboard/TradeJournalCard';
import { useAssets } from '../hooks/useAssets';
import '../components/dashboard/Dashboard.css';

function ageLabel(ts: number, nowMs: number): string {
  const m = Math.max(0, Math.round((nowMs - ts) / 60000));
  return m < 1 ? 'just now' : `${m}m ago`;
}

export const Watchlist: React.FC = () => {
  const { assets, add, remove, reorderGenre, updateHolding } = useAssets();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [nonce, setNonce] = useState(0);            // rescan → remounts the data section
  const [updatedAt, setUpdatedAt] = useState(() => Date.now());
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(t);
  }, []);

  const sorted = useMemo(() => assets.slice().sort((a, b) => a.sortOrder - b.sortOrder), [assets]);

  function rescan() {
    setNonce((n) => n + 1);
    setUpdatedAt(Date.now());
    setNowMs(Date.now());
  }

  return (
    <PageShell
      title="Watchlist"
      subtitle="Assets grouped by genre. Drag the handle to reorder; tap a row for its strategy. Rule-based, no automatic AI."
    >
      <AIReview />

      <div className="asset-toolbar asset-toolbar--end">
        <span className="asset-toolbar__age">Strategy updated {ageLabel(updatedAt, nowMs)}</span>
        <button className="asset-btn" onClick={rescan} aria-label="Rescan strategies (rule-based, no AI)">Rescan</button>
        <button className="asset-btn asset-btn--primary" onClick={() => setAddOpen(true)} aria-label="Add asset">+ Add Asset</button>
      </div>

      <AssetStrategySection
        key={nonce}
        assets={sorted}
        expandedId={expandedId}
        onToggleExpand={(id) => setExpandedId((cur) => (cur === id ? null : id))}
        onReorder={reorderGenre}
        onRemove={(id) => { setExpandedId((cur) => (cur === id ? null : cur)); remove(id); }}
        onUpdateHolding={updateHolding}
      />

      <TradeJournalCard assets={assets} />

      <div className="watch-toolbar">
        <ProHandoffButton />
      </div>

      {addOpen && <AddAssetModal onClose={() => setAddOpen(false)} onAdd={add} />}
    </PageShell>
  );
};

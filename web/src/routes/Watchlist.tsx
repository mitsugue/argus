import React, { useEffect, useMemo, useState } from 'react';
import { PageShell } from './PageShell';
import { AIReview } from '../components/dashboard/AIReview';
import { ProHandoffButton } from '../components/dashboard/ProHandoffButton';
import { CorporateCatalysts } from '../components/dashboard/CorporateCatalysts';
import { AssetStrategySection } from '../components/dashboard/AssetStrategySection';
import { AddAssetModal } from '../components/dashboard/AddAssetModal';
import { useAssets } from '../hooks/useAssets';
import { ASSET_TAB, tabMatches, type AssetTab } from '../types/assetItem';
import '../components/dashboard/Dashboard.css';

function ageLabel(ts: number, nowMs: number): string {
  const m = Math.max(0, Math.round((nowMs - ts) / 60000));
  if (m < 1) return 'just now';
  return `${m}m ago`;
}

export const Watchlist: React.FC = () => {
  const { assets, add, remove, move, toggle } = useAssets();
  const [tab, setTab] = useState<AssetTab>('All');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [nonce, setNonce] = useState(0);            // rescan → remounts the data section
  const [updatedAt, setUpdatedAt] = useState(() => Date.now());
  const [nowMs, setNowMs] = useState(() => Date.now());

  // Tick the "updated Xm ago" label without re-fetching.
  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(t);
  }, []);

  const visible = useMemo(
    () => assets.slice().sort((a, b) => a.sortOrder - b.sortOrder).filter((a) => tabMatches(tab, a)),
    [assets, tab],
  );

  function rescan() {
    setNonce((n) => n + 1);
    setUpdatedAt(Date.now());
    setNowMs(Date.now());
  }

  return (
    <PageShell
      title="Watchlist"
      subtitle="Unified assets — Japan / US / Core / Crypto. Tap a row for its strategy. Rule-based; no automatic AI."
    >
      <AIReview />

      <div className="asset-toolbar">
        <div className="asset-tabs" role="tablist" aria-label="Asset filter">
          {ASSET_TAB.map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              className={`asset-tab${tab === t ? ' asset-tab--on' : ''}`}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="asset-toolbar__right">
          <span className="asset-toolbar__age">Strategy updated {ageLabel(updatedAt, nowMs)}</span>
          <button className="asset-btn" onClick={rescan} aria-label="Rescan strategies (rule-based, no AI)">Rescan</button>
          <button className="asset-btn asset-btn--primary" onClick={() => setAddOpen(true)} aria-label="Add asset">+ Add Asset</button>
        </div>
      </div>

      <AssetStrategySection
        key={nonce}
        assets={visible}
        reorderable={tab === 'All'}
        expandedId={expandedId}
        onToggleExpand={(id) => setExpandedId((cur) => (cur === id ? null : id))}
        onMove={move}
        onRemove={(id) => { setExpandedId((cur) => (cur === id ? null : cur)); remove(id); }}
        onToggleEnabled={toggle}
      />

      <CorporateCatalysts />

      <div className="watch-toolbar">
        <ProHandoffButton />
      </div>

      {addOpen && <AddAssetModal onClose={() => setAddOpen(false)} onAdd={add} />}
    </PageShell>
  );
};

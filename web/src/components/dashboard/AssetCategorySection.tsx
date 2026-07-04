import React from 'react';
import type { AssetCardModel } from '../../domain/assetCard';
import type { PositionNote } from '../../domain/positionExposure';
import { UnifiedAssetCard } from './UnifiedAssetCard';
import './AssetCategorySection.css';

// A Today category container (v10.140): JAPAN WATCHLIST / US …, CRYPTO.
// v11.5.7+: NO hard cap — Today must show the SAME symbols as the Watchlist page
// (the old slice(0,10) silently dropped names past #10 and even the count badge
// lied). Clutter control stays: initial 5 + "SHOW N MORE" expands to everything,
// and at most ONE card auto-expands so the screen never thrashes.

interface Props {
  title: string;
  sub?: string;
  cards: AssetCardModel[];
  emptyJa?: string;
  /** v11.8.0: device-local position note by SYMBOL (upper). */
  positionNotes?: Record<string, PositionNote>;
}

export const AssetCategorySection: React.FC<Props> = ({ title, sub, cards, emptyJa, positionNotes }) => {
  const autoId = cards.find((c) => c.autoExpand)?.id ?? null;   // at most one
  const [openIds, setOpenIds] = React.useState<Set<string>>(() => new Set(autoId ? [autoId] : []));
  const [expanded, setExpanded] = React.useState(false);         // Show N More

  const shown = expanded ? cards : cards.slice(0, 5);
  const toggle = (id: string) => setOpenIds((s) => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
  });

  return (
    <section className="acs">
      <div className="acs-head">
        <span className="acs-title">{title}</span>
        {sub && <span className="acs-sub">{sub}</span>}
        <span className="acs-count">{cards.length}</span>
      </div>
      {cards.length === 0 ? (
        <p className="acs-empty">{emptyJa ?? '該当なし'}</p>
      ) : (
        <div className="acs-rows">
          {shown.map((c) => (
            <UnifiedAssetCard key={c.id} card={c} open={openIds.has(c.id)} onToggle={() => toggle(c.id)}
              positionNote={positionNotes?.[c.symbol.toUpperCase()]} />
          ))}
          {cards.length > 5 && (
            <button className="acs-more" onClick={() => setExpanded((v) => !v)}>
              {expanded ? '閉じる' : `SHOW ${cards.length - 5} MORE`}
            </button>
          )}
        </div>
      )}
    </section>
  );
};

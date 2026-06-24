import React from 'react';
import type { AssetCardModel } from '../../domain/assetCard';
import { UnifiedAssetCard } from './UnifiedAssetCard';
import './AssetCategorySection.css';

// A Today category container (v10.140): JAPAN WATCHLIST / EMERGING, US …, CRYPTO.
// Max 10 cards, initial 5 + "Show 5 More", at most ONE auto-expanded card so the
// screen never thrashes; user-opened cards keep their own state.

interface Props {
  title: string;
  sub?: string;
  cards: AssetCardModel[];
  emptyJa?: string;
}

export const AssetCategorySection: React.FC<Props> = ({ title, sub, cards, emptyJa }) => {
  const capped = cards.slice(0, 10);
  const autoId = capped.find((c) => c.autoExpand)?.id ?? null;   // at most one
  const [openIds, setOpenIds] = React.useState<Set<string>>(() => new Set(autoId ? [autoId] : []));
  const [expanded, setExpanded] = React.useState(false);         // Show 5 More

  const shown = expanded ? capped : capped.slice(0, 5);
  const toggle = (id: string) => setOpenIds((s) => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
  });

  return (
    <section className="acs">
      <div className="acs-head">
        <span className="acs-title">{title}</span>
        {sub && <span className="acs-sub">{sub}</span>}
        <span className="acs-count">{capped.length}</span>
      </div>
      {capped.length === 0 ? (
        <p className="acs-empty">{emptyJa ?? '該当なし'}</p>
      ) : (
        <div className="acs-rows">
          {shown.map((c) => (
            <UnifiedAssetCard key={c.id} card={c} open={openIds.has(c.id)} onToggle={() => toggle(c.id)} />
          ))}
          {capped.length > 5 && (
            <button className="acs-more" onClick={() => setExpanded((v) => !v)}>
              {expanded ? '閉じる' : `SHOW ${capped.length - 5} MORE`}
            </button>
          )}
        </div>
      )}
    </section>
  );
};

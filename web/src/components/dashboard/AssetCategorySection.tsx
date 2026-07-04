import React from 'react';
import type { AssetCardModel } from '../../domain/assetCard';
import type { PositionNote } from '../../domain/positionExposure';
import type { SupplyDemandSignal } from '../../hooks/useSupplyDemand';
import type { APItem } from '../../domain/actionPriority';
import type { LocalScenarioSet } from '../../domain/scenario';
import type { LocalPlan } from '../../domain/positionPlan';
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
  /** v11.10.0: 需給ランク(JP watchlist). */
  supplyDemandSignals?: SupplyDemandSignal[];
  /** v11.12.0: 優先度(端末内計算). */
  actionPriorities?: APItem[];
  /** v11.17.0: 条件付きシナリオ(端末内合成・保有加味). */
  scenarios?: LocalScenarioSet[];
  /** v11.18.0: 計画(端末内合成・売買指示なし). */
  plans?: LocalPlan[];
}

export const AssetCategorySection: React.FC<Props> = ({ title, sub, cards, emptyJa, positionNotes, supplyDemandSignals, actionPriorities, scenarios, plans }) => {
  const apBySym = React.useMemo(() => {
    const m = new Map<string, APItem>();
    for (const it of actionPriorities ?? []) m.set(it.symbol, it);
    return m;
  }, [actionPriorities]);
  const scBySym = React.useMemo(() => {
    const m = new Map<string, LocalScenarioSet>();
    for (const s of scenarios ?? []) m.set(s.symbol.toUpperCase(), s);
    return m;
  }, [scenarios]);
  const ppBySym = React.useMemo(() => {
    const m = new Map<string, LocalPlan>();
    for (const p of plans ?? []) m.set(p.symbol.toUpperCase(), p);
    return m;
  }, [plans]);
  const sdBySym = React.useMemo(() => {
    const m = new Map<string, SupplyDemandSignal>();
    for (const s of supplyDemandSignals ?? []) m.set(s.symbol.toUpperCase(), s);
    return m;
  }, [supplyDemandSignals]);
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
              positionNote={positionNotes?.[c.symbol.toUpperCase()]}
              supplyDemand={sdBySym.get(c.symbol.toUpperCase())}
              actionPriority={apBySym.get(c.symbol.toUpperCase())}
              scenario={scBySym.get(c.symbol.toUpperCase())}
              plan={ppBySym.get(c.symbol.toUpperCase())} />
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

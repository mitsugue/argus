import React, { useState } from 'react';
import type { DeskCardData } from './types';
import { sectionAnchorId } from './types';
import { AssetDecisionSummary } from './AssetDecisionSummary';
import { AssetTargetDetails } from './AssetTargetDetails';
import { AssetEarningsDetails } from './AssetEarnings';
import { AssetFlowPanel } from './AssetFlowPanel';
import { AssetEventsPanel } from './AssetEventsPanel';
import { AssetScenarioPanel } from './AssetScenarioPanel';
import { AssetResearchPanel } from './AssetResearchPanel';
import { AssetNumbers } from './AssetNumbers';
import { OwnerOverview } from '../dialogue/OwnerOverview';
import { OsintDeepDive } from '../dashboard/OsintDeepDive';
import '../dashboard/UnifiedAssetCard.css';
import '../dashboard/Dashboard.css';
import './AssetDesk.css';
import '../common/AssetReadingCard.css';

interface Props {
  d: DeskCardData;
  open: boolean;
  onToggle: () => void;
  onRemove: (id: string) => void;
  nowMs: number;
  dragHandle?: React.ReactNode;
  focusSection?: string;
  collapsible?: boolean;
}

// 2026-10-25 (owner): one page read from the top — the conclusion, four
// numbers, the material, then folded details. Market-wide views stay on
// Today; nothing here repeats them.

const first = (text?: string | null) => {
  const value = (text ?? '').trim();
  const cut = value.indexOf('。');
  return cut > 0 ? value.slice(0, cut + 1) : value;
};

// A folded part mounts only once opened, so its reads start on demand.
const Fold: React.FC<{ symbol: string; id: string; title: string; open?: boolean; children: React.ReactNode }> =
  ({ symbol, id, title, open = false, children }) => {
    const [isOpen, setOpen] = useState(open);
    return (
      <details className="ad-fold" id={sectionAnchorId(symbol, id)} open={isOpen}
        onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>{title}</summary>
        {isOpen && <div className="ad-fold__body">{children}</div>}
      </details>
    );
  };

export const AssetDecisionCard: React.FC<Props> = ({
  d, open, onToggle, onRemove, dragHandle, focusSection, collapsible = true,
}) => {
  const sym = d.asset.symbol;
  const view = d.decisionFirst;
  const market = d.asset.market;
  const stock = market === 'JP' || market === 'US';
  const lead = d.incident?.moverCause?.bestLeadJa ?? null;
  const focus = (...ids: string[]) => !!focusSection && ids.includes(focusSection);
  return (
    <article className={`uac ad-card asset-reading-card uac--${open ? 'open' : 'compact'}`} id={sectionAnchorId(sym)}>
      {dragHandle}
      <AssetDecisionSummary d={d} open={open} onToggle={onToggle} interactive={collapsible} />
      {open && (
        <div className="uac-body ad-expanded">
          <section className="ad-block" id={sectionAnchorId(sym, 'decision')}>
            <h4 className="ad-block__label">結論</h4>
            {stock
              ? <OwnerOverview key={`${market}:${sym}`} symbol={sym} market={market} horizon={5} asset={d.asset}
                  line={{ fallback: first(view.whyJa) || '見立てなし', fallbackChange: first(view.whatChangesJa) || undefined }} />
              : <div className="ad-conclusion"><p className="ad-conclusion__view">{first(view.whyJa) || '見立てなし'}</p></div>}
          </section>
          {stock && <section className="ad-block"><h4 className="ad-block__label">数字</h4><AssetNumbers d={d} /></section>}
          {stock && <section className="ad-block" id={sectionAnchorId(sym, 'why-downside')}>
            <h4 className="ad-block__label">材料</h4>
            {lead && <p className="ad-material__lead">{lead}</p>}
            <OsintDeepDive symbol={sym} market={market} name={d.asset.displayNameJa ?? d.asset.displayName} />
          </section>}
          <div className="ad-folds">
            {stock && <Fold symbol={sym} id="earnings" title="決算の内訳"><AssetEarningsDetails market={market} symbol={sym} /></Fold>}
            <Fold symbol={sym} id="flow-supply" title="需給の数値" open={focus('flow-supply')}><AssetFlowPanel d={d} /></Fold>
            <Fold symbol={sym} id="scenarios" title="条件・目標" open={focus('scenarios', 'technical', 'chart')}>
              {view.nextJa && <p className="ad-fold__line">次に確認：{first(view.nextJa)}</p>}
              <AssetTargetDetails d={d} />
              <AssetScenarioPanel d={d} />
            </Fold>
            {d.eventTags.length > 0 && <Fold symbol={sym} id="events" title="関連イベント" open={focus('events')}><AssetEventsPanel d={d} /></Fold>}
            <Fold symbol={sym} id="research" title="メモ・記録" open={focus('research')}><AssetResearchPanel d={d} onRemove={onRemove} /></Fold>
          </div>
        </div>
      )}
    </article>
  );
};

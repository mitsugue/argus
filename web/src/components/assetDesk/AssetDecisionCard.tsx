import React, { useEffect, useState } from 'react';
import type { DeskCardData, DeskTab } from './types';
import { sectionAnchorId, tabForDeskSection } from './types';
import { AssetDecisionSummary } from './AssetDecisionSummary';
import { AssetTargetDetails } from './AssetTargetDetails';
import { AssetEarningsDetails } from './AssetEarnings';
import { AssetDecisionDetails } from './AssetDecisionDetails';
import { AssetMarketContext } from './AssetMarketContext';
import { AssetWhyPanel } from './AssetWhyPanel';
import { AssetFlowPanel } from './AssetFlowPanel';
import { AssetEventsPanel } from './AssetEventsPanel';
import { AssetScenarioPanel } from './AssetScenarioPanel';
import { AssetResearchPanel } from './AssetResearchPanel';
import { AssetDataQuality } from './AssetDataQuality';
import { AssetEvidenceSummary } from './AssetEvidenceSummary';
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

const TABS: Array<{ id: DeskTab; label: string }> = [
  { id: 'decision', label: '見立て' },
  { id: 'chart', label: '目標・条件' },
  { id: 'evidence', label: '需給・材料' },
];

const Section: React.FC<{
  symbol: string; id: string; title?: string; children: React.ReactNode;
}> = ({ symbol, id, title, children }) => (
  <section className="ad-tab-section" id={sectionAnchorId(symbol, id)}>
    {title && <h4>{title}</h4>}
    {children}
  </section>
);

export const AssetDecisionCard: React.FC<Props> = ({
  d, open, onToggle, onRemove, nowMs, dragHandle, focusSection,
  collapsible = true,
}) => {
  const [tab, setTab] = useState<DeskTab>('decision');
  const [supportOpen, setSupportOpen] = useState(false);
  const sym = d.asset.symbol;
  const actionTone = { BUY: 'var(--value-positive)', HOLD: 'var(--accent)',
    WAIT: 'var(--amber, #fbbf24)', REDUCE: 'var(--event-high)', EXIT: 'var(--value-negative)' } as const;
  const sigColor = actionTone[d.decisionFirst.canonicalPrimaryAction ?? 'WAIT'];

  useEffect(() => {
    if (!open) { setTab('decision'); setSupportOpen(false); return; }
    if (focusSection) {
      setTab(tabForDeskSection(focusSection));
      if (['research', 'data-quality', 'ai-review'].includes(focusSection)) setSupportOpen(true);
    }
  }, [open, focusSection]);

  const onTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = TABS.findIndex((item) => item.id === tab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1
      : event.key === 'ArrowRight' ? (index + 1) % TABS.length
      : (index - 1 + TABS.length) % TABS.length;
    setTab(TABS[next].id);
    const list = event.currentTarget.parentElement;
    window.requestAnimationFrame(() => {
      (list?.querySelector(`[data-tab="${TABS[next].id}"]`) as HTMLButtonElement | null)?.focus();
    });
  };

  return (
    <article className={`uac ad-card asset-reading-card uac--${open ? 'open' : 'compact'}${d.decisionFirst.held ? ' uac--held' : ''}`}
         id={sectionAnchorId(sym)} style={{ ['--uac-sig' as string]: sigColor }}>
      {dragHandle}
      <AssetDecisionSummary d={d} open={open} onToggle={onToggle} interactive={collapsible} />
      {open && (
        <div className="uac-body ad-expanded">
          <div className="ad-tabs" role="tablist" aria-label={`${sym} 詳細`}>
            {TABS.map((item) => (
              <button key={item.id} type="button" role="tab"
                id={`ad-tab-${sym}-${item.id}`}
                aria-selected={tab === item.id}
                aria-controls={`ad-panel-${sym}-${item.id}`}
                tabIndex={tab === item.id ? 0 : -1}
                data-tab={item.id}
                className={tab === item.id ? 'is-active' : ''}
                onClick={() => setTab(item.id)}
                onKeyDown={onTabKeyDown}>
                {item.label}
              </button>
            ))}
          </div>

          <div role="tabpanel" id={`ad-panel-${sym}-${tab}`}
               aria-labelledby={`ad-tab-${sym}-${tab}`} className="ad-tab-panel">
            {tab === 'decision' && (
              <Section symbol={sym} id="decision">
                <AssetDecisionDetails d={d} />
                <AssetEarningsDetails market={d.asset.market} symbol={sym} />
                <AssetMarketContext symbol={sym} market={d.asset.market} asset={d.asset} />
              </Section>
            )}
            {tab === 'chart' && (
              <Section symbol={sym} id="technical">
                <AssetTargetDetails d={d} />
                <Section symbol={sym} id="scenarios" title="状況ごとの条件">
                  <AssetScenarioPanel d={d} />
                </Section>
                <p className="ad-chart-retired" data-asset-chart="retired">
                  値動きのチャートは他のアプリで確認できます。
                </p>
              </Section>
            )}
            {tab === 'evidence' && (
              <>
                <Section symbol={sym} id="why-downside">
                  <AssetEvidenceSummary d={d} />
                </Section>
                <details className="ad-evidence-details" open>
                  <summary>需給の根拠と数値</summary>
                  <Section symbol={sym} id="flow-supply"><AssetFlowPanel d={d} /></Section>
                </details>
                <details className="ad-evidence-details" open={focusSection === 'events'}>
                  <summary>関連イベント・材料</summary>
                  <Section symbol={sym} id="events"><AssetEventsPanel d={d} /></Section>
                </details>
                <details className="ad-evidence-details" open={focusSection === 'why-downside'}>
                  <summary>値動きの経緯・原因候補</summary>
                  <Section symbol={sym} id="evidence-raw"><AssetWhyPanel d={d} /></Section>
                </details>
              </>
            )}
          </div>
          <details className="ad-research-drawer" open={supportOpen}
            data-secondary-utility="research-data"
            onToggle={(event) => setSupportOpen(event.currentTarget.open)}>
            <summary>記録・データ</summary>
            {supportOpen && <div className="ad-research-drawer__body">
              <Section symbol={sym} id="research" title="銘柄メモ・調査記録">
                <AssetResearchPanel d={d} onRemove={onRemove} />
              </Section>
              <Section symbol={sym} id="data-quality" title="データの状態">
                <AssetDataQuality d={d} nowMs={nowMs} />
              </Section>
            </div>}
          </details>
        </div>
      )}
    </article>
  );
};

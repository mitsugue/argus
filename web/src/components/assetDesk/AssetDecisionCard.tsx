import React, { useEffect, useState } from 'react';
import type { DeskCardData, DeskTab } from './types';
import { sectionAnchorId, tabForDeskSection } from './types';
import { SIGNALS } from '../../domain/actionLevel';
import { AssetDecisionSummary, deskSignalCode } from './AssetDecisionSummary';
import { AssetDecisionDetails } from './AssetDecisionDetails';
import { AssetAIReview } from './AssetAIReview';
import { AssetPositionPanel } from './AssetPositionPanel';
import { AssetWhyPanel } from './AssetWhyPanel';
import { AssetFlowPanel } from './AssetFlowPanel';
import { AssetEventsPanel } from './AssetEventsPanel';
import { AssetEntryScout, fetchScout, type ScoutState } from './AssetEntryScout';
import { AssetScenarioPanel } from './AssetScenarioPanel';
import { AssetResearchPanel } from './AssetResearchPanel';
import { AssetDataQuality } from './AssetDataQuality';
import { AssetEvidenceSummary } from './AssetEvidenceSummary';
import { ChartIntelligencePanel } from '../chart/ChartIntelligencePanel';
import '../dashboard/UnifiedAssetCard.css';
import '../dashboard/Dashboard.css';
import './AssetDesk.css';

interface Props {
  d: DeskCardData;
  open: boolean;
  onToggle: () => void;
  onRemove: (id: string) => void;
  onUpdateHolding: (id: string, h: { quantity?: number | null; avgCost?: number | null }) => void;
  nowMs: number;
  dragHandle?: React.ReactNode;
  focusSection?: string;
}

const TABS: Array<{ id: DeskTab; label: string }> = [
  { id: 'decision', label: 'Decision' },
  { id: 'chart', label: 'Chart' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'position', label: 'Position' },
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
  d, open, onToggle, onRemove, onUpdateHolding, nowMs, dragHandle, focusSection,
}) => {
  const [scout, setScout] = useState<ScoutState>(null);
  const [tab, setTab] = useState<DeskTab>('decision');
  const [supportOpen, setSupportOpen] = useState(false);
  const runScout = () => {
    setScout('loading');
    void fetchScout(d.asset.symbol, d.asset.market).then(setScout);
  };
  const sym = d.asset.symbol;
  const sigColor = `var(${SIGNALS[deskSignalCode(d)].token})`;

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
    <article className={`uac ad-card uac--${open ? 'open' : 'compact'}${d.decisionFirst.held ? ' uac--held' : ''}`}
         id={sectionAnchorId(sym)} style={{ ['--uac-sig' as string]: sigColor }}>
      {dragHandle}
      <AssetDecisionSummary d={d} open={open} onToggle={onToggle} />
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
                <details className="ad-plan-detail">
                  <summary>条件と分岐を確認</summary>
                  <AssetScenarioPanel d={d} />
                </details>
              </Section>
            )}
            {tab === 'chart' && (
              <Section symbol={sym} id="technical">
                <ChartIntelligencePanel scope="asset" symbol={sym}
                  market={d.asset.market} enabled />
                <AssetEntryScout market={d.asset.market} scout={scout} onRun={runScout} />
              </Section>
            )}
            {tab === 'evidence' && (
              <>
                <Section symbol={sym} id="why-downside">
                  <AssetEvidenceSummary d={d} />
                </Section>
                <details className="ad-evidence-details">
                  <summary>検証詳細</summary>
                  <Section symbol={sym} id="flow-supply" title="FLOW / SUPPLY">
                    <AssetFlowPanel d={d} />
                  </Section>
                  <Section symbol={sym} id="events" title="EVENTS">
                    <AssetEventsPanel d={d} />
                  </Section>
                  <Section symbol={sym} id="evidence-raw" title="CAUSE / DOWNSIDE">
                    <AssetWhyPanel d={d} />
                  </Section>
                </details>
              </>
            )}
            {tab === 'position' && (
              <Section symbol={sym} id="owner-position">
                <AssetPositionPanel d={d} onUpdateHolding={onUpdateHolding} />
              </Section>
            )}
          </div>
          <details className="ad-research-drawer" open={supportOpen}
            data-secondary-utility="research-data"
            onToggle={(event) => setSupportOpen(event.currentTarget.open)}>
            <summary>Utility · Research &amp; Data</summary>
            <div className="ad-research-drawer__body">
              <Section symbol={sym} id="ai-review" title="AI REVIEW / RULE CHECK">
                <AssetAIReview d={d} />
              </Section>
              <Section symbol={sym} id="research" title="RESEARCH / NOTES">
                <AssetResearchPanel d={d} scout={scout} onRemove={onRemove} />
              </Section>
              <Section symbol={sym} id="data-quality" title="DATA QUALITY">
                <AssetDataQuality d={d} nowMs={nowMs} />
              </Section>
            </div>
          </details>
        </div>
      )}
    </article>
  );
};

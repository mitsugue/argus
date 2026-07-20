import React, { useState } from 'react';
import type { DeskCardData, DeskSection } from './types';
import { sectionAnchorId } from './types';
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
import { ChartIntelligencePanel } from '../chart/ChartIntelligencePanel';
import '../dashboard/UnifiedAssetCard.css';
import '../dashboard/Dashboard.css';
import './AssetDesk.css';

// V12.2.12 — 個別銘柄の正本カード(§6/§7)。閉=要約、開=固定順の10セクション。
// 判断はdomain/assetDecision+useAssetIntelの出力のみ(このカードは表示専用)。

interface Props {
  d: DeskCardData;
  open: boolean;
  onToggle: () => void;
  onRemove: (id: string) => void;
  onUpdateHolding: (id: string, h: { quantity?: number | null; avgCost?: number | null }) => void;
  nowMs: number;
  dragHandle?: React.ReactNode;
}

const Sec: React.FC<{ symbol: string; id: DeskSection; title: string; children: React.ReactNode }> =
  ({ symbol, id, title, children }) => (
    <div className="uac-sec ad-sec" id={sectionAnchorId(symbol, id)}>
      <div className="uac-sec-t">{title}</div>
      {children}
    </div>
  );

export const AssetDecisionCard: React.FC<Props> = ({ d, open, onToggle, onRemove, onUpdateHolding, nowMs, dragHandle }) => {
  const [scout, setScout] = useState<ScoutState>(null);
  const runScout = () => {
    setScout('loading');
    void fetchScout(d.asset.symbol, d.asset.market).then(setScout);
  };
  const sym = d.asset.symbol;
  const sigColor = `var(${SIGNALS[deskSignalCode(d)].token})`;
  return (
    <div className={`uac ad-card uac--${open ? 'open' : 'compact'}${(d.pn?.held || (d.asset.quantity ?? 0) > 0) ? ' uac--held' : ''}`}
         id={sectionAnchorId(sym)} style={{ ['--uac-sig' as string]: sigColor }}>
      {dragHandle}
      <AssetDecisionSummary d={d} open={open} onToggle={onToggle} />
      {open && (
        <div className="uac-body">
          <Sec symbol={sym} id="decision" title="DECISION"><AssetDecisionDetails d={d} /></Sec>
          <Sec symbol={sym} id="ai-review" title="AI REVIEW / RULE CHECK"><AssetAIReview d={d} /></Sec>
          <Sec symbol={sym} id="owner-position" title="OWNER POSITION">
            <AssetPositionPanel d={d} onUpdateHolding={onUpdateHolding} />
          </Sec>
          <Sec symbol={sym} id="why-downside" title="WHY / DOWNSIDE"><AssetWhyPanel d={d} /></Sec>
          <Sec symbol={sym} id="flow-supply" title="FLOW & SUPPLY"><AssetFlowPanel d={d} /></Sec>
          <Sec symbol={sym} id="events" title="EVENTS & CATALYSTS"><AssetEventsPanel d={d} /></Sec>
          <Sec symbol={sym} id="technical" title="TECHNICAL & ENTRY">
            <ChartIntelligencePanel scope="asset" symbol={d.asset.symbol} market={d.asset.market} />
            <AssetEntryScout market={d.asset.market} scout={scout} onRun={runScout} />
          </Sec>
          <Sec symbol={sym} id="scenarios" title="SCENARIOS"><AssetScenarioPanel d={d} /></Sec>
          <Sec symbol={sym} id="research" title="RESEARCH & NOTES">
            <AssetResearchPanel d={d} scout={scout} onRemove={onRemove} />
          </Sec>
          <Sec symbol={sym} id="data-quality" title="DATA QUALITY"><AssetDataQuality d={d} nowMs={nowMs} /></Sec>
          {/* 免責はカード内で1回だけ */}
          <p className="uac-next" style={{ margin: '4px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
            ※ シナリオ/計画/優先度は条件付きの判断支援であり売買指示ではありません(確率は帯のみ・注文機能なし・価格の目安は確認ポイント)。
          </p>
        </div>
      )}
    </div>
  );
};

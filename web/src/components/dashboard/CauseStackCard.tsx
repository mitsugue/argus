import React from 'react';
import { useCauseAttribution } from '../../hooks/useCauseAttribution';
import './CauseStackCard.css';

// Cause-stack card (v10.117) — the integrity view for a material move: what is
// the confirmed immediate trigger (often NONE), the likely-cause distribution
// (with a non-zero UNKNOWN), how far it propagated, positioning context (no named
// institution), and what would change the conclusion. Decision-support only.

const CAUSE_JA: Record<string, string> = {
  EARNINGS_RESULT_SHOCK: '決算結果ショック', PRE_EARNINGS_DE_RISKING: '決算前の手仕舞い',
  CROWDED_TRADE_UNWIND: '人気トレードの巻き戻し', VALUATION_REPRICING: 'バリュエーション調整',
  RATE_SHOCK: '金利ショック', AI_CAPEX_ROI_CONCERN: 'AI設備投資ROI懸念',
  SECTOR_WIDE_DELEVERAGING: 'セクター全体の手仕舞い', LONG_LIQUIDATION: 'ロング解消',
  NEW_SHORT_BUILDUP: '新規空売り', SHORT_COVERING: '買い戻し', DISTRIBUTION: '大口の売り',
  COMPANY_SPECIFIC_CATALYST: '個別材料', UNKNOWN: '原因未確認',
};
const SCOPE_JA: Record<string, string> = {
  company_specific: '個別銘柄', subsector_wide: 'サブセクター', sector_wide: 'セクター全体',
  cross_market: 'クロスマーケット', global_growth_unwind: 'グローバル景気の巻き戻し', unconfirmed: '未確認',
};
const POS_JA: Record<string, string> = {
  newLongAccumulation: '新規ロング', longLiquidation: 'ロング解消', newShortBuildup: '新規空売り',
  shortCovering: '買い戻し', distribution: '大口売り', retailNoise: '個人ノイズ', unknown: '不明',
};

export const CauseStackCard: React.FC<{ symbol: string; market?: string }> = ({ symbol, market = 'JP' }) => {
  const { data } = useCauseAttribution(symbol, market);
  if (!data) return null;
  const causes = Object.entries(data.causeProbabilities || {}).sort((a, b) => b[1] - a[1]).slice(0, 4);
  const posTop = Object.entries(data.positioning?.probabilities || {}).sort((a, b) => b[1] - a[1])[0];

  return (
    <section className="csc-card">
      <header className="csc-head">
        <h2>原因スタック <span className="csc-en">cause attribution</span></h2>
        <span className="csc-sym">{data.symbol}{typeof data.changePct === 'number' ? ` ${data.changePct.toFixed(1)}%` : ''}</span>
      </header>

      <div className="csc-trigger">
        <span className="csc-k">確定した即時引き金</span>
        {data.immediateTrigger ? (
          <span className="csc-trigger-v">{CAUSE_JA[data.immediateTrigger.cause] ?? data.immediateTrigger.cause}（信頼度 {Math.round(data.immediateTrigger.confidence * 100)}%）</span>
        ) : (
          <span className="csc-trigger-none">確認できず（断定しない）</span>
        )}
      </div>

      <div className="csc-causes">
        <span className="csc-k">推定原因の分布</span>
        {causes.map(([c, p]) => (
          <div className="csc-cause" key={c}>
            <span className={`csc-cause-name${c === 'UNKNOWN' ? ' csc-cause-name--unknown' : ''}`}>{CAUSE_JA[c] ?? c}</span>
            <span className="csc-bar"><i style={{ width: `${Math.round(p * 100)}%` }} className={c === 'UNKNOWN' ? 'csc-bar--unknown' : ''} /></span>
            <span className="csc-pct">{Math.round(p * 100)}%</span>
          </div>
        ))}
      </div>

      <div className="csc-grid">
        <div><span className="csc-k">波及範囲</span><span className="csc-v">{SCOPE_JA[data.contagion?.scope] ?? data.contagion?.scope ?? '—'}{data.contagion?.peersTotal ? `（${data.contagion.peersDown}/${data.contagion.peersTotal}銘柄）` : ''}</span></div>
        {posTop && <div><span className="csc-k">需給(高速)</span><span className="csc-v">{POS_JA[posTop[0]] ?? posTop[0]} {Math.round(posTop[1] * 100)}% <span className="csc-dim">・投資家特定は不可</span></span></div>}
        <div><span className="csc-k">未確認の割合</span><span className="csc-v">{Math.round((data.unknownShare || 0) * 100)}%</span></div>
        {data.preEvent?.preEventDeRiskingProbability >= 0.4 && (
          <div><span className="csc-k">決算前手仕舞い</span><span className="csc-v">{Math.round(data.preEvent.preEventDeRiskingProbability * 100)}%（結果は未確定）</span></div>
        )}
      </div>

      <p className="csc-next"><b>何が変われば結論が変わるか:</b> {data.preEvent?.nextEvidenceRequired}</p>
      {data.dataLimitations?.length > 0 && (
        <p className="csc-limits">データ制約: {data.dataLimitations.join(' / ')}</p>
      )}
      <p className="csc-foot">決定支援のみ・原因の断定や機関名の名指しはしません。</p>
    </section>
  );
};

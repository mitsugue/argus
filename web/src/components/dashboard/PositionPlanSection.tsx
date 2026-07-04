import React from 'react';
import type { LocalPlan } from '../../domain/positionPlan';
import { STANCE_TONE } from '../../domain/positionPlan';
import type { APItem } from '../../domain/actionPriority';
import { jpDisplay } from '../../lib/displayName';

// V11.18.0 — POSITION PLAN on Today (top planning items ONLY, never the full
// list): 保有リスク確認/利確検討 → イベント待ち → 追いかけ注意 → 小さく追加可 →
// P0-P2の押し目限定。計画であり売買指示ではない。

const PICK_ORDER: LocalPlan['currentStance'][] = [
  'risk_review', 'trim_consideration', 'avoid_chase', 'small_add_allowed', 'add_only_on_pullback',
];

export const PositionPlanSection: React.FC<{ plans: LocalPlan[]; apItems: APItem[] }> =
  ({ plans, apItems }) => {
    const topAP = new Set(apItems.filter((i) => ['P0', 'P1', 'P2'].includes(i.priorityRank))
      .map((i) => i.symbol));
    const shown: LocalPlan[] = [];
    for (const p of plans.filter((p) => p.planType === 'event_wait' && (p.isHeld || topAP.has(p.symbol)))) shown.push(p);
    for (const stance of PICK_ORDER) {
      for (const p of plans.filter((p) => p.currentStance === stance
        && (p.isHeld || topAP.has(p.symbol) || stance === 'avoid_chase' || stance === 'small_add_allowed'))) {
        if (!shown.includes(p)) shown.push(p);
      }
    }
    const top = shown.slice(0, 5);
    if (!top.length) return null;

    return (
      <section>
        <div className="section-head">
          <span className="section-head__title">POSITION PLAN</span>
          <span className="section-head__count">今日の計画上位 · 売買指示なし</span>
        </div>
        {top.map((p) => (
          <div key={p.symbol}
               style={{ borderLeft: `2px solid ${STANCE_TONE[p.currentStance]}`,
                        paddingLeft: 8, margin: '6px 0' }}>
            <p style={{ margin: 0, fontSize: 12.5 }}>
              <b style={{ color: STANCE_TONE[p.currentStance], border: `1px solid ${STANCE_TONE[p.currentStance]}`,
                          borderRadius: 4, padding: '0 5px', fontSize: 10.5 }}>
                {p.currentStanceJa}
              </b>
              <b style={{ marginLeft: 6 }}>{jpDisplay(p.symbol, p.assetName)}</b>
              {p.isHeld && <span style={{ marginLeft: 4, fontSize: 9.5, color: 'var(--amber, #fbbf24)',
                                          border: '1px solid var(--line)', borderRadius: 999, padding: '0 5px' }}>保有</span>}
            </p>
            <p style={{ margin: '2px 0 0', fontSize: 11.5, color: 'var(--text-sub)', lineHeight: 1.6 }}>
              {p.summaryJa}
            </p>
            {p.whatNotToDoJa.length > 0 && (
              <p style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
                やらないこと: {p.whatNotToDoJa[0]}
              </p>
            )}
          </div>
        ))}
        <p style={{ margin: '4px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
          エントリー条件・利確検討・無効化条件の詳細は各銘柄カードのPOSITION PLANで。
          これは計画であり売買指示ではありません(注文機能はありません)。
        </p>
      </section>
    );
  };

export default PositionPlanSection;

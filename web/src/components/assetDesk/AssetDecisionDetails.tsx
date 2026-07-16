import React from 'react';
import type { DeskCardData } from './types';
import { SIGNALS } from '../../domain/actionLevel';
import { existingJa } from '../../domain/assetCard';
import { PRIMARY_STANCE_TONE } from '../../domain/primaryStance';
import { STANCE_TONE } from '../../domain/positionPlan';
import { RANK_TONE as AP_TONE } from '../../domain/actionPriority';
import { DOM_TONE } from '../../domain/scenario';
import { ExpandableReason } from '../common/CollapsibleSection';
import { deskSignalCode } from './AssetDecisionSummary';

// V12.2.12 — DECISION(§7-1): 単一の構え+ARGUS VIEW+計画+優先度+NEXT。
// 旧Today UnifiedAssetCardのPRIMARY STANCE/ARGUS VIEW/POSITION PLAN/ACTION
// PRIORITY/NEXTと旧WatchlistのStrategy/Why/待つ条件/変化条件を1箇所に統合。

const AI_BADGE: Record<string, { txt: string; tone: string }> = {
  fresh: { txt: 'AI FRESH', tone: 'var(--value-positive)' },
  stale: { txt: 'AI STALE', tone: 'var(--value-neutral)' },
  unavailable: { txt: 'AI UNAVAILABLE', tone: 'var(--text-muted)' },
  rule_only: { txt: 'RULE ONLY', tone: 'var(--text-muted)' },
};

export const AssetDecisionDetails: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const c = d.card;
  const code = deskSignalCode(d);
  const perms = SIGNALS[code].permissions;
  const pst = d.pst;
  const ppl = d.ppl;
  const apx = d.apx;
  const ai = AI_BADGE[d.aiMeta.freshness] ?? AI_BADGE.rule_only;
  return (
    <>
      {/* 単一の構え(v12.0.8) — 全ページ共通チップ・矛盾排除 */}
      {pst && (
        <p className="uac-next" style={{ margin: '0 0 4px', fontSize: 12 }}>
          <b style={{ color: PRIMARY_STANCE_TONE[pst.primaryStance],
                      border: `1px solid ${PRIMARY_STANCE_TONE[pst.primaryStance]}`,
                      borderRadius: 999, padding: '1px 9px' }}>
            構え: {pst.stanceJa}
          </b>
          <span style={{ marginLeft: 6, color: 'var(--text-faint)', fontSize: 10.5 }}>
            確度{Math.round(pst.confidence * 100)}%{pst.capNotesJa.length > 0 ? ` · ${pst.capNotesJa[0]}` : ''}
          </span>
          {pst.reasonsJa.length > 0 && (
            <span style={{ display: 'block', marginTop: 2, color: 'var(--text-sub)', fontSize: 10.5 }}>
              {pst.reasonsJa.join(' / ')}
            </span>
          )}
        </p>
      )}
      {/* 新規/追加/既存の許可(閉じたカードから移設した詳細) */}
      <p className="uac-next" style={{ margin: '0 0 4px', fontSize: 11, color: 'var(--text-sub)' }}>
        {`新規${perms.newEntry === 'BLOCKED' ? '禁止' : '可'} · 追加${perms.add === 'BLOCKED' ? '禁止' : '可'} · 既存は${c?.permExistingJa ?? existingJa(code)}`}
      </p>
      {c && (
        <div className="uac-av">
          <div className="uac-av-h"><b>ARGUS VIEW</b>{c.lastUpdate && <span> · {c.lastUpdate}</span>}</div>
          <p className="uac-av-t">{c.argusViewJa}</p>
          {/* v12.2.12: overallJaが主判断の理由そのもの(=AI長文理由など)の時は重複
              表示しない — argusViewJaは先頭120字+permissionsで文字列不一致でも
              実質同文になるため。全文はAI REVIEW/RULE CHECKで読める。 */}
          {c.overallJa && c.overallJa !== c.argusViewJa
            && c.overallJa !== d.decision?.reasonJa
            && <p className="uac-overall">{c.overallJa}</p>}
          <div className="uac-av-src">
            <span>RULE + GPT-5.5 + GEMINI</span>
            <span className="uac-ai" style={{ color: ai.tone }}>· {ai.txt}</span>
          </div>
        </div>
      )}
      {/* ルールエンジンの説明系(旧Watchlist asset-detail__grid) */}
      <div className="asset-detail__grid">
        <div><span className="asset-detail__k">Strategy</span><span className="asset-detail__v">{d.strat.strategyJa}</span></div>
        <div><span className="asset-detail__k">Why</span><span className="asset-detail__v">{d.strat.reasonJa}</span></div>
        <div><span className="asset-detail__k">What to wait for</span><span className="asset-detail__v">{d.strat.nextConditionJa}</span></div>
        <div><span className="asset-detail__k">What changes it</span><span className="asset-detail__v">{d.strat.whatChangesJa}</span></div>
      </div>

      {/* POSITION PLAN (v11.18.0) — 執行語なし・売買指示ではない */}
      {ppl && (
        <div className="uac-sec">
          <div className="uac-sec-t">POSITION PLAN</div>
          <p className="uac-next" style={{ marginBottom: 2 }}>
            <b style={{ color: STANCE_TONE[ppl.currentStance], border: `1px solid ${STANCE_TONE[ppl.currentStance]}`,
                        borderRadius: 4, padding: '0 5px', fontSize: 10.5 }}>
              {ppl.currentStanceJa}
            </b>
            <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
              証拠: {ppl.evidenceQuality === 'strong' ? '強' : ppl.evidenceQuality === 'medium' ? '中' : ppl.evidenceQuality === 'weak' ? '弱' : '不足'}
            </span>
          </p>
          <ExpandableReason className="uac-next" style={{ marginBottom: 2, color: 'var(--text-sub)' }} text={ppl.summaryJa} />
          {ppl.strategicRole && (
            <p className="uac-next" style={{ marginBottom: 2, fontSize: 10.5 }}>
              <span style={{ border: '1px solid var(--line)', borderRadius: 999,
                             padding: '0 6px', color: 'var(--accent)' }}>
                役割: {ppl.strategicRole.roleJa}
              </span>
              <span style={{ marginLeft: 5, color: 'var(--text-faint)' }}>
                追加方針: {ppl.strategicRole.addPolicyJa} · {ppl.strategicRole.roleReasonJa}
              </span>
            </p>
          )}
          <details>
            <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>計画の詳細(条件・やらないこと)を見る</summary>
            {ppl.entryConditionsJa.length > 0 && (
              <p className="uac-next" style={{ margin: '3px 0 0', fontSize: 10.5 }}>
                入る条件: {ppl.entryConditionsJa.join(' / ')}
              </p>
            )}
            {ppl.isHeld && ppl.holdConditionsJa.length > 0 && (
              <p className="uac-next" style={{ margin: '2px 0 0', fontSize: 10.5 }}>
                保有の監視条件({ppl.holdModeJa}): {ppl.holdConditionsJa.join(' / ')}
              </p>
            )}
            {ppl.isHeld && ppl.trimReviewConditionsJa.length > 0 && (
              <p className="uac-next" style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--amber, #fbbf24)' }}>
                利確検討/リスク確認の条件: {ppl.trimReviewConditionsJa.join(' / ')}
              </p>
            )}
            {ppl.whatNotToDoJa.length > 0 && (
              <p className="uac-next" style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
                やらないこと: {ppl.whatNotToDoJa.join(' / ')}
              </p>
            )}
            <p className="uac-next" style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
              無効化条件: {ppl.invalidationJa.join(' / ')}
            </p>
            <p className="uac-next" style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
              次の確認: {ppl.nextChecksJa.join(' / ')}
            </p>
            {d.scn && (
              <p className="uac-next" style={{ margin: '2px 0 0', fontSize: 10.5 }}>
                <span style={{ color: DOM_TONE[d.scn.dominant] }}>シナリオ連動: {d.scn.dominantJa}に沿った計画。</span>
                <span style={{ color: 'var(--text-faint)' }}>支配シナリオが入れ替われば計画も組み直します。</span>
              </p>
            )}
          </details>
        </div>
      )}

      {/* ACTION PRIORITY (v11.12.0) — 注意配分・売買指示なし */}
      {apx && apx.priorityRank !== 'Ignore' && (
        <div className="uac-sec">
          <div className="uac-sec-t">ACTION PRIORITY</div>
          <p className="uac-next" style={{ marginBottom: 2 }}>
            <b style={{ color: AP_TONE[apx.priorityRank] }}>{apx.priorityRank} {apx.actionLabelJa}</b>
            <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>{apx.whyJa}</span>
          </p>
          <p className="uac-next" style={{ marginBottom: 0, fontSize: 10.5, color: 'var(--text-faint)' }}>
            変化条件: {apx.whatWouldChangeJa}
          </p>
        </div>
      )}

      {c?.nextJa && (
        <div className="uac-sec">
          <div className="uac-sec-t">NEXT</div>
          <p className="uac-next">{c.nextJa}</p>
        </div>
      )}
    </>
  );
};

import React from 'react';
import type { DeskCardData } from './types';

// V12.2.12 — AI REVIEW / RULE CHECK(§7-2)。
// AIが主判断の時: AI自身の内容(提案/理由/redFlags/実行時刻/モデル)+ルール判定
// 原文との相違。AIが使えない時もこの欄は消えない — 「RULE TEMPORARY+正確な理由
// +次回実行予定」を必ず表示する(§5)。AI理由が無い時にルール理由をAI文章として
// 見せない(reasonMissingを正直に表示)。

export const AssetAIReview: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const dec = d.decision;
  if (!dec) {
    return (
      <p className="uac-next" style={{ margin: 0, color: 'var(--text-faint)' }}>
        この資産クラス(投信/暗号資産)はAI判定・ルール判定ラベルの対象外です(ルールエンジンの戦略のみ)。
      </p>
    );
  }
  const ai = dec.ai;
  return (
    <>
      {ai.available && d.aiLabel ? (
        <div className="asset-ai">
          <div className="asset-ai__head">
            <span className="asset-ai__tag">
              AI見解{dec.ageJa ? `・${dec.ageJa}の実行` : ''}{ai.modelsJa ? ` [${ai.modelsJa}]` : ''}
            </span>
            {ai.viewJa && <span style={{ color: ai.viewTone }}>{ai.viewJa}</span>}
            <span className="asset-ai__action">
              AI提案: <b>{ai.finalAction ?? '—'}</b>
              {ai.confidencePct != null && <>（確信度{ai.confidencePct}%）</>}
            </span>
          </div>
          {ai.reasonJa && <p className="asset-ai__reason">{ai.reasonJa}</p>}
          {ai.reasonMissing && (
            <p className="asset-ai__reason" style={{ color: 'var(--text-faint)' }}>
              AIの理由文は未取得(アクションのみ) — ルール理由で代用はしません。
            </p>
          )}
          {ai.redFlags.length > 0 && (
            <p className="asset-ai__flags">⚑ {ai.redFlags.join(' / ')}</p>
          )}
        </div>
      ) : (
        <div className="asset-ai">
          <div className="asset-ai__head">
            <span className="asset-ai__tag" style={{ color: 'var(--amber, #fbbf24)' }}>RULE TEMPORARY</span>
            <span style={{ color: 'var(--text-sub)' }}>{ai.unavailableReasonJa ?? 'AI見解は未実行'}</span>
          </div>
          <p className="asset-ai__reason" style={{ color: 'var(--text-faint)' }}>
            {/* 次回時刻は実行が保証できる状態(未実行/stale)でのみ案内 —
                disabled/取得不能/品質制限/対象symbolなしでは約束しない。 */}
            {ai.nextRunJa ? `${ai.nextRunJa}。それまでは` : ''}ルール判定(ガードレール)が主判断です。
          </p>
        </div>
      )}
      {/* RULE CHECK — ルール判定の原文(AI主判断時の突き合わせ用) */}
      <div className="uac-sec" style={{ marginTop: 6 }}>
        <div className="uac-sec-t">RULE CHECK</div>
        <p className="uac-next" style={{ marginBottom: 2 }}>
          ルール判定: <b>{dec.rule.action}</b>
          {dec.rule.disagreementJa && (
            <span style={{ marginLeft: 6, color: 'var(--value-negative)' }}>不一致: {dec.rule.disagreementJa}</span>
          )}
        </p>
        {dec.rule.reasonJa && <p className="uac-next" style={{ marginBottom: 2, color: 'var(--text-sub)' }}>{dec.rule.reasonJa}</p>}
        {dec.rule.nextConditionJa && (
          <p className="uac-next" style={{ marginBottom: 0, fontSize: 10.5, color: 'var(--text-faint)' }}>
            次の条件: {dec.rule.nextConditionJa}
          </p>
        )}
      </div>
    </>
  );
};

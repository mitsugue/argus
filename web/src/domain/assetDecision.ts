// V13 Round 2 — SDA primary projection + legacy asset-evidence compatibility.
//
// 旧Today(AI優先マージ)とWatchlist(ルール主・AI第二意見)の形は
// 互換入力として残すが、どちらもEVIDENCE_ONLY。銘柄の主判断は
// projectCanonicalAssetDecisionが受け取るSDA結果だけであり、AI/旧ルールは上書きできない。
//
// この層は新しい投資判断を生成しない: 既存のAI結果・既存のルール結果・既存の
// incident overrideを正確に合成し、表示用語彙へ変換するだけ。
// フィールド単位でsourceを追跡し、AI理由が無い時にルール理由をAI文章として
// 見せかけない(aiReasonJa=nullで正直に区別)。

import type { AiFreshness } from './assetCard';
import { confidenceDisplay, type ConfidenceDisplay } from './decisionView';
import { exactAuthorityEpoch, liveAuthorityState } from './liveAuthority';
import type { SingleDecisionAuthorityResultV2 } from './singleDecisionAuthority';

// ── 入力(既存hookの形に緩く合わせる — 再計算しない) ─────────────────────────

export interface AiLabelLike {
  symbol: string;
  aiFinalAction?: string | null;
  reasonJa?: string | null;
  confidence?: number | null;
  aiView?: string;                    // confirm | caution | disagree | unavailable
  redFlags?: string[];
}

export interface AiDataLike {
  status?: string;                    // live | partial | ...
  asOf?: string;
  freshness?: string;                 // fresh | persisted | stale
  models?: { primary?: string | null; checker?: string | null };
  labels?: AiLabelLike[];
}

export interface RuleLabelLike {
  symbol: string;
  action: string;
  name?: string;
  reasonJa?: string;
  nextConditionJa?: string;
  confidence?: number | null;
  status?: string;
  supportingData?: { price?: number | null; changePct?: number; bigFlowRatio?: number | null; quoteDate?: string | null };
}

// ── AI可用性(Todayが使ってきた条件と同一 — ここが単一の定義) ─────────────────

export interface AiMeta {
  /** Fresh enough to display as challenge evidence; never final-action authority. */
  evidenceAvailable: boolean;
  authorityRole: 'EVIDENCE_ONLY';
  finalDecisionAuthorityActive: false;
  freshness: AiFreshness;
  ageMin: number | null;
  status: string | null;
  models: { primary?: string | null; checker?: string | null } | null;
  /** AI証拠を表示できない正確な理由(evidenceAvailable=falseの時のみ)。 */
  unavailableReasonJa: string | null;
  /** 実在スケジュールに基づく次回実行の案内。実行/更新を保証できない状態
      (disabled/取得不能/データ品質制限)ではnull — 16:05を約束しない。 */
  nextRunJa: string | null;
}

// 平日16:05 JST = AI本判定+台帳採点の実在cron(スケジュールが適用される状態のみ案内)。
const NEXT_RUN_JA = '次のAI実行予定: 平日16:05 JST';
const AI_EVIDENCE_AUTHORITY = {
  authorityRole: 'EVIDENCE_ONLY' as const,
  finalDecisionAuthorityActive: false as const,
};

export function assessAi(ai: AiDataLike | null | undefined, nowMs: number): AiMeta {
  if (!ai) {
    // データ自体が無い(接続中/取得失敗) — 実行を保証できないため次回時刻は約束しない。
    return { evidenceAvailable: false, ...AI_EVIDENCE_AUTHORITY,
      freshness: 'rule_only', ageMin: null, status: null,
      models: null, unavailableReasonJa: 'AI見解が未取得(接続中または取得失敗)', nextRunJa: null };
  }
  const t = exactAuthorityEpoch(ai.asOf);
  const ageMin = t != null && t <= nowMs ? Math.round((nowMs - t) / 60000) : null;
  const statusOk = ai.status === 'live' || ai.status === 'partial';
  const freshOk = ai.freshness === 'fresh' || ai.freshness === 'persisted';
  const freshness: AiFreshness = ai.freshness === 'fresh' ? 'fresh'
    : ai.freshness === 'persisted' || ai.freshness === 'stale' ? 'stale'
    : 'unavailable';   // データはあるが鮮度不明(旧CommandCenterと同一分類)
  if (!statusOk) {
    // 状態ごとの正確な理由。16:05を案内するのは「レイヤー有効で未実行」だけ。
    const st = ai.status ?? null;
    const reason = st === 'disabled' ? 'AI判定レイヤーは無効化中(自動実行なし)'
      : st === 'no_cached_result' ? 'AI見解は未実行'
      : st === 'mock' ? 'AI判定を取得できません(バックエンド未接続)'
      : 'AI取得不可(データ品質制限)';
    return { evidenceAvailable: false, ...AI_EVIDENCE_AUTHORITY,
      freshness, ageMin, status: st,
      models: ai.models ?? null, unavailableReasonJa: reason,
      nextRunJa: st === 'no_cached_result' ? NEXT_RUN_JA : null };
  }
  const timestampState = liveAuthorityState(ai.asOf, 'aiJudgment', nowMs);
  if (timestampState !== 'fresh') {
    const expired = timestampState === 'expired';
    return { evidenceAvailable: false, ...AI_EVIDENCE_AUTHORITY,
      freshness: expired ? 'stale' : 'unavailable', ageMin,
      status: ai.status ?? null, models: ai.models ?? null,
      unavailableReasonJa: expired
        ? 'AIデータが古い(72時間の判断期限を超過)'
        : 'AI基準時刻が不正または未来のため証拠表示に使わない',
      nextRunJa: expired ? NEXT_RUN_JA : null };
  }
  if (!freshOk) {
    // staleは実行済み+スケジュール実在 — 次の定期実行での更新を案内できる。
    return { evidenceAvailable: false, ...AI_EVIDENCE_AUTHORITY,
      freshness, ageMin, status: ai.status ?? null,
      models: ai.models ?? null, unavailableReasonJa: 'AIデータが古い(staleは証拠表示に使わない)',
      nextRunJa: NEXT_RUN_JA };
  }
  return { evidenceAvailable: true, ...AI_EVIDENCE_AUTHORITY,
    freshness: ai.freshness === 'fresh' ? 'fresh' : 'stale',   // 表示badge互換(persisted=stale表示)
    ageMin, status: ai.status ?? null, models: ai.models ?? null,
    unavailableReasonJa: null, nextRunJa: NEXT_RUN_JA };
}

// ── 旧AIマージ互換面(出力は必ずEVIDENCE_ONLY) ────────────────────────

/** @deprecated Name retained for callers; AI is attached as evidence and never merged into action. */
// ── 判断ビュー(閉じたカード+AI REVIEW/RULE CHECKパネル用) ───────────────────

const AI_VIEW_JA: Record<string, string> = {
  confirm: 'ルール判定と一致', caution: 'ルール判定より注意', disagree: 'ルール判定と不同意',
  unavailable: '比較不能',
};
const AI_VIEW_TONE: Record<string, string> = {
  confirm: 'var(--value-positive)', caution: 'var(--amber, #fbbf24)',
  disagree: 'var(--value-negative)', unavailable: 'var(--text-muted)',
};

export interface AssetDecisionView {
  symbol: string;
  judgmentSource: 'sda';
  sourceTagEn: 'SDA PRIMARY';
  /** Authority/evidence state and its exact availability reason. */
  sourceDetailJa: string;
  ageJa: string | null;
  /** SDA primary reason, or a legacy-rule reason on the compatibility resolver. */
  reasonJa: string;
  /** 理由のsource(ルール理由をAI文章に見せない)。 */
  reasonSource: 'sda';
  confidenceJa: ConfidenceDisplay;
  ai: {
    authorityRole: 'EVIDENCE_ONLY';
    finalDecisionAuthorityActive: false;
    available: boolean;
    finalAction: string | null;
    reasonJa: string | null;          // AI自身の理由のみ(欠落=null)
    reasonMissing: boolean;
    confidenceJa: ConfidenceDisplay;
    viewJa: string | null;            // ルールとの一致/注意/不同意
    viewTone: string;
    redFlags: string[];
    modelsJa: string | null;
    unavailableReasonJa: string | null;
    /** 次回実行の案内(保証できない状態と「この銘柄のAI判断なし」ではnull)。 */
    nextRunJa: string | null;
  };
  rule: {
    authorityRole: 'EVIDENCE_ONLY';
    finalDecisionAuthorityActive: false;
    action: string;                   // ルールの生アクション(RULE CHECK用)
    reasonJa: string | null;
    nextConditionJa: string | null;
    disagreementJa: string | null;    // AI/旧ルール証拠の相違点(ある時だけ)
  };
}

/**
 * Project the canonical five-action authority into the existing compact card
 * shape. AI and the former rule action are retained only in the review panel;
 * neither can replace ``result.primaryAction``.
 */
export function projectCanonicalAssetDecision(inp: {
  symbol: string;
  result: SingleDecisionAuthorityResultV2;
  ruleLabel: RuleLabelLike | undefined;
  aiLabel: AiLabelLike | undefined;
  meta: AiMeta;
}): AssetDecisionView {
  const ageJa = inp.meta.ageMin == null ? null
    : inp.meta.ageMin < 60 ? `${inp.meta.ageMin}分前`
    : inp.meta.ageMin < 1440 ? `${Math.round(inp.meta.ageMin / 60)}時間前`
    : `${Math.round(inp.meta.ageMin / 1440)}日前`;
  const models = inp.meta.models?.primary
    ? `${inp.meta.models.primary}${inp.meta.models.checker ? `+${inp.meta.models.checker}` : ''}`
    : null;
  const view = inp.aiLabel?.aiView ?? null;
  const missing = inp.result.missingReasonCodes.slice(0, 3);
  const conflict = inp.result.conflictReasonCodes.slice(0, 3);
  const reasonJa = inp.result.status === 'DATA_GATED'
    ? `SDAはWAITに固定（${[...missing, ...conflict].join(' / ') || '必要証拠未確認'}）`
    : `SDA ${inp.result.primaryAction}（制約 ${inp.result.guidance.riskConstraint}）`;
  const aiAvailable = !!inp.aiLabel && inp.meta.evidenceAvailable;
  const ruleAction = inp.ruleLabel?.action ?? 'HOLD';
  const aiAction = inp.aiLabel?.aiFinalAction ?? null;
  const dissent = [
    aiAction && aiAction !== inp.result.primaryAction
      ? `AI=${aiAction} / SDA=${inp.result.primaryAction}` : null,
    ruleAction !== inp.result.primaryAction
      ? `旧ルール=${ruleAction} / SDA=${inp.result.primaryAction}` : null,
  ].filter(Boolean).join(' · ') || null;
  return {
    symbol: inp.symbol,
    judgmentSource: 'sda',
    sourceTagEn: 'SDA PRIMARY',
    sourceDetailJa: `${inp.result.status} · ${inp.result.decisionId.slice(0, 16)}…`,
    ageJa,
    reasonJa,
    reasonSource: 'sda',
    confidenceJa: confidenceDisplay(inp.result.confidence.valueBps / 10_000),
    ai: {
      authorityRole: 'EVIDENCE_ONLY',
      finalDecisionAuthorityActive: false,
      available: aiAvailable,
      finalAction: aiAction,
      reasonJa: inp.aiLabel?.reasonJa ?? null,
      reasonMissing: !!inp.aiLabel && !inp.aiLabel.reasonJa,
      confidenceJa: confidenceDisplay(inp.aiLabel?.confidence),
      viewJa: view ? (AI_VIEW_JA[view] ?? view) : null,
      viewTone: AI_VIEW_TONE[view ?? 'unavailable'] ?? 'var(--text-muted)',
      redFlags: inp.aiLabel?.redFlags ?? [],
      modelsJa: models,
      unavailableReasonJa: inp.meta.unavailableReasonJa,
      nextRunJa: inp.meta.evidenceAvailable && !inp.aiLabel ? null : inp.meta.nextRunJa,
    },
    rule: {
      authorityRole: 'EVIDENCE_ONLY',
      finalDecisionAuthorityActive: false,
      action: ruleAction,
      reasonJa: inp.ruleLabel?.reasonJa ?? null,
      nextConditionJa: inp.ruleLabel?.nextConditionJa ?? null,
      disagreementJa: dissent,
    },
  };
}

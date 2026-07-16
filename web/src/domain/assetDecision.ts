// V12.2.12 — Asset Decision(個別銘柄判断の唯一の正本・純関数)。
//
// これまでToday(AI優先マージ)とWatchlist(ルール主・AI第二意見)で分裂していた
// 「同一銘柄の主判断」を、この1モジュールに集約する。TodayとAsset Deskは
// 必ずここを通るため、同一入力→同一判断が構造的に保証される。
//
// この層は新しい投資判断を生成しない: 既存のAI結果・既存のルール結果・既存の
// incident overrideを正確に合成し、表示用語彙へ変換するだけ。
// フィールド単位でsourceを追跡し、AI理由が無い時にルール理由をAI文章として
// 見せかけない(aiReasonJa=nullで正直に区別)。

import type { AiFreshness } from './assetCard';

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

export type Merged<R extends RuleLabelLike> = R & {
  judgmentSource: 'ai' | 'rule';
  /** AI自身の理由のみ(欠落時はnull — ルール理由でsourceを偽らない)。 */
  aiReasonJa: string | null;
};
export type MergedLabel = Merged<RuleLabelLike>;

// ── AI可用性(Todayが使ってきた条件と同一 — ここが単一の定義) ─────────────────

export interface AiMeta {
  primary: boolean;                   // AIを主判断にできるか
  freshness: AiFreshness;
  ageMin: number | null;
  status: string | null;
  models: { primary?: string | null; checker?: string | null } | null;
  /** AIを主判断にできない正確な理由(primary=falseの時のみ)。 */
  unavailableReasonJa: string | null;
  /** 実在スケジュールに基づく次回実行の案内。実行/更新を保証できない状態
      (disabled/取得不能/データ品質制限)ではnull — 16:05を約束しない。 */
  nextRunJa: string | null;
}

// 平日16:05 JST = AI本判定+台帳採点の実在cron(スケジュールが適用される状態のみ案内)。
const NEXT_RUN_JA = '次のAI実行予定: 平日16:05 JST';

export function assessAi(ai: AiDataLike | null | undefined, nowMs: number): AiMeta {
  if (!ai) {
    // データ自体が無い(接続中/取得失敗) — 実行を保証できないため次回時刻は約束しない。
    return { primary: false, freshness: 'rule_only', ageMin: null, status: null,
      models: null, unavailableReasonJa: 'AI見解が未取得(接続中または取得失敗)', nextRunJa: null };
  }
  const t = ai.asOf ? Date.parse(ai.asOf) : NaN;
  const ageMin = Number.isFinite(t) ? Math.max(0, Math.round((nowMs - t) / 60000)) : null;
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
    return { primary: false, freshness, ageMin, status: st,
      models: ai.models ?? null, unavailableReasonJa: reason,
      nextRunJa: st === 'no_cached_result' ? NEXT_RUN_JA : null };
  }
  if (!freshOk) {
    // staleは実行済み+スケジュール実在 — 次の定期実行での更新を案内できる。
    return { primary: false, freshness, ageMin, status: ai.status ?? null,
      models: ai.models ?? null, unavailableReasonJa: 'AIデータが古い(staleは主判断に使わない)',
      nextRunJa: NEXT_RUN_JA };
  }
  return { primary: true,
    freshness: ai.freshness === 'fresh' ? 'fresh' : 'stale',   // 表示badge互換(persisted=stale表示)
    ageMin, status: ai.status ?? null, models: ai.models ?? null,
    unavailableReasonJa: null, nextRunJa: NEXT_RUN_JA };
}

// ── AI優先マージ(旧CommandCenter内ロジックを移設 — 挙動は同一) ──────────────

export function mergeAiPrimary<R extends RuleLabelLike>(
  ai: AiDataLike | null | undefined,
  ruleLabels: R[],
  nowMs: number,
): { labels: Merged<R>[]; meta: AiMeta } {
  const meta = assessAi(ai, nowMs);
  const aiBySym = new Map((ai?.labels ?? []).map((l) => [l.symbol.toUpperCase(), l]));
  const labels: Merged<R>[] = ruleLabels.map((rl) => {
    const a = meta.primary ? aiBySym.get(rl.symbol.toUpperCase()) : undefined;
    if (a && a.aiFinalAction) {
      return { ...rl, action: a.aiFinalAction,
        reasonJa: a.reasonJa || rl.reasonJa,          // カード表示の合成文(従来どおり)
        aiReasonJa: a.reasonJa || null,               // AI自身の理由のみ(source追跡)
        confidence: a.confidence ?? rl.confidence,
        judgmentSource: 'ai' } as Merged<R>;
    }
    return { ...rl, judgmentSource: 'rule', aiReasonJa: null } as Merged<R>;
  });
  return { labels, meta };
}

export function aiFreshnessOf(meta: AiMeta): AiFreshness { return meta.freshness; }

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
  judgmentSource: 'ai' | 'rule';
  sourceTagEn: 'AI PRIMARY' | 'RULE TEMPORARY';
  /** RULE TEMPORARY時の正確な理由 / AI PRIMARY時はage表記。 */
  sourceDetailJa: string;
  ageJa: string | null;
  /** 主判断の理由(表示用の合成 — AI主ならAI理由、無ければルール理由)。 */
  reasonJa: string;
  /** 理由のsource(ルール理由をAI文章に見せない)。 */
  reasonSource: 'ai' | 'rule';
  confidencePct: number | null;
  ai: {
    available: boolean;
    finalAction: string | null;
    reasonJa: string | null;          // AI自身の理由のみ(欠落=null)
    reasonMissing: boolean;
    confidencePct: number | null;
    viewJa: string | null;            // ルールとの一致/注意/不同意
    viewTone: string;
    redFlags: string[];
    modelsJa: string | null;
    unavailableReasonJa: string | null;
    /** 次回実行の案内(保証できない状態と「この銘柄のAI判断なし」ではnull)。 */
    nextRunJa: string | null;
  };
  rule: {
    action: string;                   // ルールの生アクション(RULE CHECK用)
    reasonJa: string | null;
    nextConditionJa: string | null;
    disagreementJa: string | null;    // AI主判断とルールの相違点(ある時だけ)
  };
}

export function resolveAssetDecision(inp: {
  symbol: string;
  merged: MergedLabel | undefined;    // mergeAiPrimaryの出力(表示中の主判断)
  ruleLabel: RuleLabelLike | undefined;   // マージ前のルール判定
  aiLabel: AiLabelLike | undefined;
  meta: AiMeta;
  symbolHasAi: boolean;
}): AssetDecisionView {
  const src: 'ai' | 'rule' = inp.merged?.judgmentSource ?? 'rule';
  const ageJa = inp.meta.ageMin == null ? null
    : inp.meta.ageMin < 60 ? `${inp.meta.ageMin}分前`
    : inp.meta.ageMin < 1440 ? `${Math.round(inp.meta.ageMin / 60)}時間前`
    : `${Math.round(inp.meta.ageMin / 1440)}日前`;
  // RULE TEMPORARYの正確な理由(AI欄を無言で消さないための区別)。
  // AIが最新でもルール判定行が未取得(コールド)の間はマージ対象が無く
  // ルール暫定のまま — その状態を「AI未実行」と偽らない。
  const ruleTempJa = inp.meta.primary
    ? (inp.symbolHasAi
        ? (inp.merged ? null : 'ルール判定ラベル未取得(接続中)')
        : 'この銘柄のAI判断なし')
    : inp.meta.unavailableReasonJa;
  const aiReason = src === 'ai' ? (inp.merged?.aiReasonJa ?? null) : (inp.aiLabel?.reasonJa ?? null);
  const reasonJa = inp.merged?.reasonJa || inp.ruleLabel?.reasonJa || '判断根拠を取得中';
  const models = inp.meta.models?.primary
    ? `${inp.meta.models.primary}${inp.meta.models.checker ? `+${inp.meta.models.checker}` : ''}` : null;
  const view = inp.aiLabel?.aiView ?? null;
  return {
    symbol: inp.symbol,
    judgmentSource: src,
    sourceTagEn: src === 'ai' ? 'AI PRIMARY' : 'RULE TEMPORARY',
    sourceDetailJa: src === 'ai'
      ? `AIの判断${ageJa ? `・${ageJa}の実行` : ''}`
      : `ルール暫定 — ${ruleTempJa ?? 'AI見解は未実行'}`,
    ageJa,
    reasonJa,
    reasonSource: src === 'ai' && inp.merged?.aiReasonJa ? 'ai' : 'rule',
    confidencePct: inp.merged?.confidence != null ? Math.round(inp.merged.confidence * 100) : null,
    ai: {
      available: !!inp.aiLabel && inp.meta.primary,
      finalAction: inp.aiLabel?.aiFinalAction ?? null,
      reasonJa: aiReason,
      reasonMissing: !!inp.aiLabel && !inp.aiLabel.reasonJa,
      confidencePct: inp.aiLabel?.confidence != null ? Math.round(inp.aiLabel.confidence * 100) : null,
      viewJa: view ? (AI_VIEW_JA[view] ?? view) : null,
      viewTone: AI_VIEW_TONE[view ?? 'unavailable'] ?? 'var(--text-muted)',
      redFlags: inp.aiLabel?.redFlags ?? [],
      modelsJa: models,
      unavailableReasonJa: ruleTempJa,
      // 「AI自体は最新だがこの銘柄のラベルが無い」時、次回実行がこの銘柄を
      // 含む保証はない — 16:05を約束しない。
      nextRunJa: inp.meta.primary && !inp.symbolHasAi ? null : inp.meta.nextRunJa,
    },
    rule: {
      action: inp.ruleLabel?.action ?? 'HOLD',
      reasonJa: inp.ruleLabel?.reasonJa ?? null,
      nextConditionJa: inp.ruleLabel?.nextConditionJa ?? null,
      disagreementJa: src === 'ai' && inp.ruleLabel && inp.aiLabel?.aiFinalAction
        && inp.ruleLabel.action !== inp.aiLabel.aiFinalAction
        ? `AI=${inp.aiLabel.aiFinalAction} / ルール=${inp.ruleLabel.action}`
        : null,
    },
  };
}

// ARGUS V12.0.8 — Primary Stance Resolver (device-local, deterministic).
// 同じ銘柄に Session Brief=リスク / Plan=リスク確認が先 / AP=対応不要 が並ぶ矛盾
// (オーナー報告)を根治する「銘柄ごとの単一の構え」。全カードはこのチップを表示し、
// 下位セクションは詳細を説明できるが矛盾してはならない。
// Python側 argus_primary_stance.py と完全同期(ルール変更は必ず両方)。売買指示ではない。

export type PrimaryStance =
  | 'risk_review' | 'trim_consideration' | 'wait_event' | 'avoid_chase'
  | 'add_only_on_pullback' | 'small_add_allowed' | 'hold' | 'no_action' | 'unknown';

export const PRIMARY_STANCE_JA: Record<PrimaryStance, string> = {
  risk_review: 'リスク確認が先',
  trim_consideration: '一部利確を検討する局面',
  wait_event: 'イベント待ち',
  avoid_chase: '追いかけ買い注意',
  add_only_on_pullback: '買うなら押し目限定',
  small_add_allowed: '小さく買い増し可',
  hold: '保有継続',
  no_action: '対応不要',
  unknown: '判定保留',
};

export const PRIMARY_STANCE_TONE: Record<PrimaryStance, string> = {
  risk_review: 'var(--value-negative)',
  trim_consideration: 'var(--amber, #fbbf24)',
  wait_event: 'var(--event-high)',
  avoid_chase: 'var(--amber, #fbbf24)',
  add_only_on_pullback: 'var(--accent)',
  small_add_allowed: 'var(--value-positive)',
  hold: 'var(--text-sub)',
  no_action: 'var(--text-muted)',
  unknown: 'var(--text-faint)',
};

const PARTIAL_CONF_CAP = 0.55;
const BAD_FLOW = new Set(['panic_selling', 'distribution']);
const HEAVY_SD = new Set(['improving_but_heavy', 'credit_overhang', 'heavy']);
const SQUEEZE_SD = new Set(['squeeze_prone', 'squeeze_fade']);

export interface StanceInputs {
  isHeld: boolean;
  apRank?: string | null;          // 'P0'..'Ignore'
  apLabel?: string | null;         // ActionLabel
  planStance?: string | null;      // positionPlan Stance
  scenarioDominant?: string | null;
  sdCondition?: string | null;
  sdLevel?: string | null;
  flowClass?: string | null;
  eventWait?: boolean;
  riskLevel?: string | null;       // 'low'..'critical'
  dataPartial?: boolean;
  baseConfidence?: number | null;
}

export interface ResolvedStance {
  primaryStance: PrimaryStance;
  stanceJa: string;
  confidence: number;
  reasonsJa: string[];
  capNotesJa: string[];
}

export function resolvePrimaryStance(i: StanceInputs): ResolvedStance {
  const held = !!i.isHeld;
  const apRank = i.apRank ?? 'Unknown';
  const apLabel = i.apLabel ?? 'UNKNOWN';
  const plan = i.planStance ?? 'unknown';
  const dom = i.scenarioDominant ?? 'unknown';
  const sdCond = i.sdCondition ?? 'unknown';
  const sdLevel = i.sdLevel ?? 'unknown';
  const flow = i.flowClass ?? 'unknown';
  const risk = i.riskLevel ?? 'unknown';
  const partial = !!i.dataPartial;
  const eventWait = !!i.eventWait || plan === 'wait' || apLabel === 'WAIT_EVENT' || dom === 'wait_event';
  let conf = i.baseConfidence ?? 0.6;
  const reasons: string[] = [];
  const capNotes: string[] = [];

  const risky = held && (
    apRank === 'P0' || apRank === 'P1'
    || plan === 'risk_review'
    || dom === 'bearish'
    || risk === 'high' || risk === 'critical'
    || BAD_FLOW.has(flow)
  );

  let stance: PrimaryStance;
  if (risky) {
    // 保有×リスクは最優先 — 「対応不要」への降格は構造的に不可能
    if (plan === 'trim_consideration') {
      stance = 'trim_consideration';
      reasons.push('計画が一部利確検討(保有×リスク側)');
    } else {
      stance = 'risk_review';
      if (apRank === 'P0' || apRank === 'P1') reasons.push(`優先度${apRank}(保有×複合シグナル)`);
      if (plan === 'risk_review') reasons.push('計画がリスクレビュー');
      if (dom === 'bearish') reasons.push('シナリオ優勢が弱気');
      if (risk === 'high' || risk === 'critical') reasons.push(`保有リスク${risk}`);
      if (BAD_FLOW.has(flow)) reasons.push('フローが売り圧推定');
    }
  } else if (held && plan === 'trim_consideration') {
    stance = 'trim_consideration';
    reasons.push('計画が一部利確検討');
  } else if (eventWait) {
    stance = 'wait_event';
    reasons.push('重要イベント接近 — 買い増し系は通過後に再評価');
  } else if (SQUEEZE_SD.has(sdCond) || apLabel === 'AVOID_CHASE' || plan === 'avoid_chase') {
    stance = 'avoid_chase';
    reasons.push('踏み上げ/急伸圏 — 追いかけは構造的に不可');
  } else if (HEAVY_SD.has(sdCond) || sdLevel === 'heavy' || sdLevel === 'very_heavy') {
    stance = 'add_only_on_pullback';
    reasons.push('需給が重い(改善中でも上値吸収まで強気化しない)');
  } else if (plan === 'add_only_on_pullback' || apLabel === 'ADD_ONLY_ON_PULLBACK') {
    stance = 'add_only_on_pullback';
    reasons.push('計画/優先度が押し目限定');
  } else if (apLabel === 'SMALL_ADD_ALLOWED'
             && ['small_add_allowed', 'monitor', 'unknown', 'no_action'].includes(plan)) {
    stance = 'small_add_allowed';
    reasons.push('ブロック要因なし(小分け前提)');
  } else if (held) {
    stance = 'hold';
    reasons.push('保有継続(明確な悪化シグナルなし)');
  } else if ((apLabel === 'NO_ACTION' || apLabel === 'IGNORE_TODAY')
             && (plan === 'no_action' || plan === 'unknown')) {
    stance = 'no_action';
    reasons.push('非保有×シグナルなし');
  } else if (apLabel === 'UNKNOWN' && plan === 'unknown' && dom === 'unknown') {
    stance = 'unknown';
    reasons.push('判定材料不足');
  } else {
    stance = held ? 'hold' : 'no_action';
  }

  if (partial) {
    conf = Math.min(conf, PARTIAL_CONF_CAP);
    capNotes.push('部分データのため確度に上限(0.55)');
    if (stance === 'small_add_allowed') {
      stance = 'unknown';
      capNotes.push('部分データ下の買い増し可は判定保留へ降格');
    }
  }
  if (eventWait && (stance === 'small_add_allowed' || stance === 'add_only_on_pullback')) {
    stance = 'wait_event';
    capNotes.push('イベント通過まで買い増し系は保留');
  }

  return {
    primaryStance: stance,
    stanceJa: PRIMARY_STANCE_JA[stance],
    confidence: Math.round(Math.min(Math.max(conf, 0), 1) * 100) / 100,
    reasonsJa: reasons.slice(0, 4),
    capNotesJa: capNotes,
  };
}

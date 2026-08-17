// V11.18.0 — Entry / Exit Planning (device-local TS port of argus_trade_plan.py).
// 「今から入っていいか/買い増ししていいか/一部利確すべきか/持ち越していいか」に
// **計画**で答える。保有数量・比率・損益(端末内のみ)を加味して合成し、外に出ない。
// 執行語(今すぐ買え/売れ・注文)は絶対に出さない。計画であり売買指示ではない。

import { jpDisplay } from '../lib/displayName';
import { exactAuthorityEpoch } from './liveAuthority';
import type { MarketCalendarState } from '../types/marketLedger';

export type PlanType = 'entry' | 'add' | 'trim_review' | 'exit_review' | 'hold'
  | 'wait' | 'avoid_chase' | 'event_wait' | 'no_action' | 'unknown';
export type Stance = 'wait' | 'monitor' | 'add_only_on_pullback' | 'small_add_allowed'
  | 'avoid_chase' | 'hold_review' | 'trim_consideration' | 'risk_review'
  | 'no_action' | 'unknown';

export const STANCE_JA: Record<Stance, string> = {
  wait: '待ち', monitor: '監視継続', add_only_on_pullback: '買うなら押し目限定',
  small_add_allowed: '小さく買い増し可(注意付き)', avoid_chase: '追いかけ買い注意',
  hold_review: '保有点検', trim_consideration: '一部利確を検討する局面',
  risk_review: 'リスク確認が先', no_action: '対応不要', unknown: '判定保留',
};
export const STANCE_TONE: Record<Stance, string> = {
  wait: 'var(--text-muted)', monitor: 'var(--text-muted)',
  add_only_on_pullback: 'var(--accent)', small_add_allowed: 'var(--value-positive)',
  avoid_chase: 'var(--amber, #fbbf24)', hold_review: 'var(--accent)',
  trim_consideration: 'var(--amber, #fbbf24)', risk_review: 'var(--value-negative)',
  no_action: 'var(--text-faint)', unknown: 'var(--text-faint)',
};
export const PLAN_COMPLIANCE_JA = 'これは計画であり売買指示ではない。注文機能はなく、判断はオーナーが行う。';
export const PTS_WARNING_JA = 'PTS/プレは流動性が薄く、判断は通常取引時間の出来高と終値位置を確認してからです。夜間の値動きだけで追いかけないでください。';
export const SESSION_UNKNOWN_WARNING_JA = '市場セッションの正本を確認できません。通常取引時間を推測せず、確認できるまで新規・追加を待ってください。';

export type PlanningSessionState = 'open' | 'closed' | 'unknown' | 'not_applicable';
export interface PlanningSessionProjection {
  schemaVersion: 'planning-session-projection-v1';
  market: string;
  state: PlanningSessionState;
  canonicalSession: string | null;
  calendarVersion: string | null;
  observedAt: string | null;
  validUntil: string | null;
  reason: 'regular_session' | 'outside_regular_session' | 'market_closed'
    | 'contract_absent' | 'contract_invalid' | 'contract_stale'
    | 'refresh_failed' | 'not_applicable';
}

export interface PlanningSessionAuthority {
  calendar: Record<string, MarketCalendarState> | null;
  serverAsOf: string | null;
  receivedAtMs: number | null;
  availability: 'available' | 'loading' | 'refresh_failed' | 'expired';
}

// This is a projection of the server's official-calendar-first session contract,
// not another exchange clock. Browser code deliberately contains no hours, DST
// rules, holiday dates, or client-clock fallback.
const PLANNING_SESSION_CONTRACT = {
  JP: {
    market: 'JP_EQUITY', timezone: 'Asia/Tokyo', officialCalendar: 'JPX_TSE',
    open: new Set(['MORNING_SESSION', 'AFTERNOON_SESSION']),
    outsideRegular: new Set(['PRE_MARKET', 'LUNCH_BREAK', 'POST_MARKET']),
  },
  US: {
    market: 'US_EQUITY', timezone: 'America/New_York', officialCalendar: 'NYSE_NASDAQ',
    open: new Set(['REGULAR']),
    outsideRegular: new Set(['OVERNIGHT_CLOSED', 'PRE_MARKET', 'AFTER_HOURS']),
  },
} as const;
const FULL_MARKET_CLOSE_SESSIONS = new Set([
  'HOLIDAY_CLOSED', 'WEEKEND_CLOSED', 'EMERGENCY_CLOSED',
]);
const SESSION_NOT_APPLICABLE_MARKETS = new Set([
  'CRYPTO', 'FUND', 'CORE', 'MANUAL',
]);
const SESSION_SNAPSHOT_MAX_AGE_MS = 20 * 60 * 1000;
const SESSION_TRANSPORT_MAX_AGE_MS = 60 * 1000;
const PLANNING_SESSION_FIELDS = new Set([
  'schemaVersion', 'market', 'state', 'canonicalSession', 'calendarVersion',
  'observedAt', 'validUntil', 'reason',
]);
const UNKNOWN_SESSION_REASONS = new Set([
  'contract_absent', 'contract_invalid', 'contract_stale', 'refresh_failed',
]);
function unavailablePlanningSession(
  market: string,
  reason: 'contract_absent' | 'contract_invalid' | 'contract_stale'
    | 'refresh_failed' | 'not_applicable',
): PlanningSessionProjection {
  return {
    schemaVersion: 'planning-session-projection-v1', market,
    state: reason === 'not_applicable' ? 'not_applicable' : 'unknown',
    canonicalSession: null, calendarVersion: null,
    observedAt: null, validUntil: null, reason,
  };
}

/** Validate an already-projected planning session as an authority boundary.
 *
 * `PlanningSessionProjection` is a TypeScript type, not runtime proof.  This
 * guard therefore rejects extra/missing keys, incoherent state/reason pairs,
 * cross-market evidence, expired evidence, and an `open` claim without the
 * canonical session/calendar/timestamp members produced by the projector.
 */
function isCoherentPlanningSessionProjection(
  market: string,
  value: unknown,
  evaluatedAtMs: number,
): value is PlanningSessionProjection {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || !Number.isFinite(evaluatedAtMs)) return false;
  const row = value as Record<string, unknown>;
  const keys = Object.keys(row);
  if (keys.length !== PLANNING_SESSION_FIELDS.size
      || keys.some((key) => !PLANNING_SESSION_FIELDS.has(key))) return false;
  if (row.schemaVersion !== 'planning-session-projection-v1'
      || row.market !== market) return false;

  const nullEvidence = row.canonicalSession === null
    && row.calendarVersion === null && row.observedAt === null
    && row.validUntil === null;
  if (row.state === 'unknown') {
    return typeof row.reason === 'string'
      && UNKNOWN_SESSION_REASONS.has(row.reason) && nullEvidence;
  }
  if (row.state === 'not_applicable') {
    return row.reason === 'not_applicable' && nullEvidence
      && SESSION_NOT_APPLICABLE_MARKETS.has(market);
  }
  if (row.state !== 'open' && row.state !== 'closed') return false;

  const contract = PLANNING_SESSION_CONTRACT[market as 'JP' | 'US'];
  if (!contract || typeof row.canonicalSession !== 'string'
      || typeof row.calendarVersion !== 'string'
      || !row.calendarVersion.trim()
      || row.calendarVersion.trim() !== row.calendarVersion
      || typeof row.observedAt !== 'string'
      || typeof row.validUntil !== 'string') return false;
  const observedAtMs = exactAuthorityEpoch(row.observedAt);
  const validUntilMs = exactAuthorityEpoch(row.validUntil);
  if (observedAtMs == null || validUntilMs == null
      || observedAtMs > evaluatedAtMs || evaluatedAtMs >= validUntilMs
      || evaluatedAtMs - observedAtMs > SESSION_SNAPSHOT_MAX_AGE_MS
      || observedAtMs >= validUntilMs) return false;

  if (row.state === 'open') {
    return row.reason === 'regular_session'
      && contract.open.has(row.canonicalSession as never);
  }
  return (row.reason === 'outside_regular_session'
      && contract.outsideRegular.has(row.canonicalSession as never))
    || (row.reason === 'market_closed'
      && FULL_MARKET_CLOSE_SESSIONS.has(row.canonicalSession));
}

/** Reduce the canonical server calendar to the only session fact planning needs. */
export function projectPlanningSession(
  market: string,
  authority?: PlanningSessionAuthority | null,
  evaluatedAtMs = Date.now(),
): PlanningSessionProjection {
  const key = String(market || '').toUpperCase();
  const contract = PLANNING_SESSION_CONTRACT[key as 'JP' | 'US'];
  if (!contract) return unavailablePlanningSession(
    key, SESSION_NOT_APPLICABLE_MARKETS.has(key)
      ? 'not_applicable' : 'contract_invalid');
  if (!authority) return unavailablePlanningSession(key, 'contract_absent');
  if (authority.availability === 'refresh_failed') {
    return unavailablePlanningSession(key, 'refresh_failed');
  }
  if (authority.availability !== 'available') {
    return unavailablePlanningSession(key, 'contract_stale');
  }
  const serverMs = exactAuthorityEpoch(authority.serverAsOf);
  const receivedAtMs = authority.receivedAtMs;
  const timingValid = Number.isFinite(evaluatedAtMs)
    && serverMs != null && Number.isFinite(receivedAtMs)
    && receivedAtMs != null
    && serverMs <= receivedAtMs && receivedAtMs <= evaluatedAtMs
    && evaluatedAtMs - serverMs <= SESSION_SNAPSHOT_MAX_AGE_MS
    && evaluatedAtMs - receivedAtMs <= SESSION_SNAPSHOT_MAX_AGE_MS
    && receivedAtMs - serverMs <= SESSION_TRANSPORT_MAX_AGE_MS;
  if (!timingValid) return unavailablePlanningSession(key, 'contract_stale');
  const state = authority.calendar?.[key];
  if (!state) return unavailablePlanningSession(key, 'contract_absent');
  const session = typeof state.session === 'string' ? state.session : '';
  const calendarVersion = typeof state.calendarVersion === 'string'
    && state.calendarVersion.trim() ? state.calendarVersion : null;
  const validUntilMs = exactAuthorityEpoch(state.sessionValidUntil);
  const structurallyValid = state.market === contract.market
    && state.timezone === contract.timezone
    && state.officialCalendar === contract.officialCalendar
    && typeof state.isTradingDay === 'boolean'
    && state.sessionObservedAt === authority.serverAsOf
    && !!calendarVersion
    && !!session
    && validUntilMs != null;
  if (!structurallyValid) return unavailablePlanningSession(key, 'contract_invalid');
  if (validUntilMs <= evaluatedAtMs || validUntilMs <= serverMs) {
    return unavailablePlanningSession(key, 'contract_stale');
  }
  if (state.isTradingDay && contract.open.has(session)) {
    return { schemaVersion: 'planning-session-projection-v1', market: key,
      state: 'open', canonicalSession: session, calendarVersion,
      observedAt: state.sessionObservedAt, validUntil: state.sessionValidUntil,
      reason: 'regular_session' };
  }
  if ((state.isTradingDay && contract.outsideRegular.has(session))
      || (!state.isTradingDay && FULL_MARKET_CLOSE_SESSIONS.has(session))) {
    return { schemaVersion: 'planning-session-projection-v1', market: key,
      state: 'closed', canonicalSession: session, calendarVersion,
      observedAt: state.sessionObservedAt, validUntil: state.sessionValidUntil,
      reason: state.isTradingDay ? 'outside_regular_session' : 'market_closed' };
  }
  return unavailablePlanningSession(key, 'contract_invalid');
}

export interface PlanInputs {
  symbol: string; market: string; assetName: string;
  isHeld: boolean;
  sdRank?: string | null; sdCondition?: string | null; sdLevel?: string | null;
  flowClass?: string | null; scenarioDominant?: string | null;
  apCategory?: string | null;
  eventPending?: boolean; eventName?: string | null;
  regimeRiskOff?: boolean;
  weightPct?: number | null; concentrationRisk?: string | null;
  positionRiskLevel?: string | null; pnlPct?: number | null;
  priorRunupPct?: number | null;
  marketSession?: PlanningSessionProjection | null;
  missing?: string[];
  /** v11.19.0: 戦略層からの制約(Portfolio Strategyが供給・端末内)。 */
  portfolioTacticalStretched?: boolean;
  themeConcentrationHigh?: boolean;
}

export interface LocalPlan {
  symbol: string; assetName: string; isHeld: boolean;
  /** v11.19.0: 戦略上の役割(CommandCenterで付与・端末内)。 */
  strategicRole?: { roleJa: string; roleReasonJa: string; addPolicyJa: string;
    strategyFit: string };
  planType: PlanType; currentStance: Stance; currentStanceJa: string;
  summaryJa: string; whyJa: string;
  entryConditionsJa: string[]; holdConditionsJa: string[];
  trimReviewConditionsJa: string[];
  invalidationJa: string[]; nextChecksJa: string[]; whatNotToDoJa: string[];
  blockingReasons: string[];
  holdModeJa: string;
  evidenceQuality: 'strong' | 'medium' | 'weak' | 'insufficient';
  marketSession: PlanningSessionProjection;
}

export function buildPlan(i: PlanInputs): LocalPlan {
  const disp = jpDisplay(i.symbol, i.assetName);
  const sdRank = i.sdRank ?? '', sdCond = i.sdCondition ?? '', flow = i.flowClass ?? '';
  const scen = i.scenarioDominant ?? '';
  const heavy = i.sdLevel === 'heavy' || i.sdLevel === 'very_heavy';
  const squeeze = sdCond === 'squeeze_prone' || flow === 'short_covering';
  const improvingHeavy = sdCond === 'improving_but_heavy';
  const event = !!i.eventPending;
  const evName = i.eventName || '重要イベント';
  const sdBad = sdRank === 'D' || sdRank === 'E';
  const flowBad = flow === 'panic_selling' || flow === 'distribution';
  const overext = (i.priorRunupPct ?? 0) >= 15;
  const highConc = ['high', 'critical'].includes(i.concentrationRisk ?? '') || (i.weightPct ?? 0) >= 25;
  const bigGain = (i.pnlPct ?? 0) >= 20;
  const adverse = (sdBad ? 1 : 0) + (flowBad ? 1 : 0)
    + (['high', 'critical'].includes(i.positionRiskLevel ?? '') ? 1 : 0)
    + (scen === 'bearish' ? 1 : 0);
  const favorable = (['S', 'A', 'B'].includes(sdRank) && !squeeze && !heavy ? 1 : 0)
    + (flow === 'institutional_accumulation' ? 1 : 0) + (scen === 'bullish' ? 1 : 0);
  const hasSd = !!sdRank && sdRank !== 'Unknown';
  const hasFlow = !!flow && flow !== 'unknown';
  const eq = hasSd && hasFlow && scen && !(i.missing ?? []).length ? 'strong'
    : hasSd || hasFlow ? 'medium' : scen ? 'weak' : 'insufficient';
  const marketKey = String(i.market || '').toUpperCase();
  const suppliedSession = i.marketSession;
  const planningEvaluatedAtMs = Date.now();
  const unavailableReason = suppliedSession != null
    ? 'contract_invalid'
    : marketKey === 'JP' || marketKey === 'US'
      ? 'contract_absent'
      : SESSION_NOT_APPLICABLE_MARKETS.has(marketKey)
        ? 'not_applicable' : 'contract_invalid';
  const marketSession = isCoherentPlanningSessionProjection(
    marketKey, suppliedSession, planningEvaluatedAtMs)
    ? suppliedSession
    : unavailablePlanningSession(marketKey, unavailableReason);
  const sessionUnknown = marketSession.state === 'unknown';
  const sessionClosed = marketSession.state === 'closed';
  const decisionEvidenceMissing = (i.missing ?? []).length > 0;

  const blocking: string[] = [];
  const whatNot: string[] = [];
  if (sessionUnknown) { blocking.push('market_session_unknown'); whatNot.push(SESSION_UNKNOWN_WARNING_JA); }
  if (decisionEvidenceMissing) blocking.push('decision_evidence_missing');
  if (event) { blocking.push('event_pending'); whatNot.push(`${evName}の発表前に方向を決め打ちして仕込まない`); }
  if (squeeze) whatNot.push('急騰局面を追いかけない(買い戻し主導なら一巡後に失速しやすい)');
  if (improvingHeavy || heavy) whatNot.push('「改善方向」を「需給良好」と読み替えて追加しない');
  if (sdBad) blocking.push('supply_demand_bad');
  if (flowBad) blocking.push('flow_deterioration');
  if (overext) whatNot.push('高値追いしない(急伸直後の新規・追加は不利になりやすい)');
  if (highConc && i.isHeld) { blocking.push('concentration_high'); whatNot.push('比率の高い銘柄をさらに厚くしない(全体の振れが大きくなる)'); }
  if (marketSession.state === 'closed') whatNot.push(PTS_WARNING_JA);
  if (i.portfolioTacticalStretched) {
    blocking.push('portfolio_tactical_stretched');
    whatNot.push('銘柄単体の条件が良くても、ポートフォリオの短期勝負枠が大きいため新規追加より整理が先');
  }
  if (i.themeConcentrationHigh) {
    blocking.push('theme_concentration_high');
    whatNot.push('テーマ集中を予算超えで上げる追加はしない(買うなら押し目+小口のみ)');
  }

  // exit / hold (held only)
  let exitMode = 'no_exit_signal';
  if (i.isHeld) {
    if (event && (['high', 'critical'].includes(i.positionRiskLevel ?? '') || adverse >= 1)) exitMode = 'event_risk_review';
    else if (adverse >= 2 || (sdBad && flowBad)) exitMode = 'risk_reduction_review';
    else if (bigGain && (overext || flowBad || heavy)) exitMode = 'trim_review';
    else if (scen === 'bearish' || ['high', 'critical'].includes(i.positionRiskLevel ?? '')) exitMode = 'risk_reduction_review';
  }
  const holdMode = !i.isHeld ? 'unknown'
    : event ? 'hold_until_event'
      : exitMode !== 'no_exit_signal' ? 'hold_with_risk_review'
        : adverse >= 1 || heavy || improvingHeavy || squeeze ? 'hold_but_monitor' : 'hold_ok';
  const HOLD_JA: Record<string, string> = {
    hold_ok: '保有継続で問題なし', hold_but_monitor: '保有継続(監視条件付き)',
    hold_until_event: 'イベント結果まで現状維持', hold_with_risk_review: '保有前にリスク確認',
    unknown: '—',
  };

  // planType / stance ladder (Python parity)
  let planType: PlanType; let stance: Stance;
  if (eq === 'insufficient') { planType = 'unknown'; stance = 'unknown'; }
  else if (event) { planType = 'event_wait'; stance = 'wait'; }
  else if (i.isHeld && exitMode === 'trim_review') { planType = 'trim_review'; stance = 'trim_consideration'; }
  else if (i.isHeld && (exitMode === 'risk_reduction_review' || exitMode === 'event_risk_review')) { planType = 'exit_review'; stance = 'risk_review'; }
  else if (squeeze || overext || i.apCategory === 'avoid_chase') { planType = 'avoid_chase'; stance = 'avoid_chase'; }
  else if (decisionEvidenceMissing) { planType = 'unknown'; stance = 'unknown'; }
  else if (improvingHeavy || (i.isHeld && highConc)) { planType = i.isHeld ? 'add' : 'entry'; stance = 'add_only_on_pullback'; }
  else if (favorable >= 2 && adverse === 0 && (eq === 'strong' || eq === 'medium')
      && !(i.missing ?? []).length && !(i.isHeld && highConc)) {
    // 戦略制約: 短期勝負枠超過/テーマ集中高では好条件でも押し目限定に降格
    if (i.portfolioTacticalStretched || i.themeConcentrationHigh) {
      planType = i.isHeld ? 'add' : 'entry'; stance = 'add_only_on_pullback';
    } else { planType = i.isHeld ? 'add' : 'entry'; stance = 'small_add_allowed'; }
  } else if (sdBad || flowBad || adverse >= 2) { planType = 'wait'; stance = 'wait'; }
  else if (i.isHeld) { planType = 'hold'; stance = holdMode === 'hold_ok' ? 'no_action' : adverse ? 'hold_review' : 'monitor'; }
  else { planType = 'wait'; stance = 'monitor'; }

  // Missing/malformed canonical session truth may not authorize a positive
  // entry/add plan. Defensive held-position reviews remain visible.
  const positivePlanSuppressedByUnknownSession = sessionUnknown
    && (planType === 'entry' || planType === 'add');
  if (positivePlanSuppressedByUnknownSession) { planType = 'unknown'; stance = 'unknown'; }
  const positivePlanSuppressedByClosedSession = sessionClosed
    && (planType === 'entry' || planType === 'add');
  if (positivePlanSuppressedByClosedSession) {
    planType = 'wait'; stance = 'wait'; blocking.push('market_session_closed');
  }

  let summary: string; let why: string;
  if (planType === 'unknown') {
    if (positivePlanSuppressedByUnknownSession) {
      summary = `計画：判定保留。${disp}は市場セッションの正本を確認できないため、新規・追加計画を出せません。`;
      why = 'サーバーの公式カレンダー準拠セッションが欠落または不正なため、通常取引時間をブラウザで推測せず確認を待ちます。';
    } else {
      summary = `計画：判定保留。${disp}は判断材料(需給/フロー)が不足しており、計画を出せる状態ではありません。`;
      why = '証拠不足のまま計画を出すと捏造になるため、データ取得を待ちます。';
    }
  } else if (event) {
    summary = `計画：イベント待ち。${evName}前のため、${disp}の${i.isHeld ? '買い増し' : '新規'}判断は発表後の金利反応と指数の方向を確認してからです。`;
    why = `${evName}の結果次第で前提が変わるため、事前の決め打ちは計画になりません。`;
  } else if (planType === 'trim_review') {
    summary = '計画：一部利確を検討する局面です。急騰後にFlowが悪化し需給も重い場合は、利益を守る観点でポジションサイズの確認を優先してください。';
    why = '含み益が大きく、過熱/売り圧力/需給の重さが重なっているため。';
  } else if (planType === 'exit_review') {
    summary = `計画：リスク確認が先です。${disp}に悪化信号が重なっており、買い増しではなく保有リスクの点検を先に行ってください。`;
    why = '需給・フロー・シナリオの悪化が重なっている保有銘柄のため。';
  } else if (planType === 'avoid_chase') {
    summary = squeeze
      ? '計画：追いかけ買い注意。売り長で踏み上げ余地はありますが、買い戻し主導なら一巡後に失速しやすいです。新規の大口買いが確認できるまで、急騰局面では待ち。'
      : '計画：追いかけ買い注意。急伸直後で高値掴みのリスクが高い局面です。出来高を伴う押し目か、上昇主体の入れ替わりを確認してから。';
    why = '上昇の持続性(実需買いか)が未確認のため。';
  } else if (stance === 'add_only_on_pullback') {
    if (improvingHeavy) {
      summary = '計画：買うなら押し目限定。需給は改善方向ですが信用買い残はまだ重く、A判定ではありません。上昇を追うより、出来高を伴って上値の売りを吸収できるかを確認してください。';
      why = '改善方向≠需給良好。水準が重い間は追加の条件を厳しくするため。';
    } else if (i.isHeld && highConc) {
      summary = '計画：保有継続は可能ですが、買い増しよりリスク確認が先です。この銘柄の比率が高く、追加するとポートフォリオ全体の振れが大きくなります。';
      why = '銘柄集中がポートフォリオ全体のリスクを支配するため。';
    } else {
      summary = `計画：買うなら押し目限定。${disp}は追わず、出来高を伴う押し目を待つ方が安全です。`;
      why = '土台は悪くないが、追いかけは不利になりやすいため。';
    }
  } else if (stance === 'small_add_allowed') {
    summary = `計画：小さく${i.isHeld ? '買い増し' : '試し玉'}可(注意付き)。複数レイヤーが好条件ですが、一度に厚くせず小さく分割で。需給悪化・イベント接近が出たら見送りに戻します。`;
    why = '需給・フロー・シナリオが揃っているが、計画は常に撤回条件付きのため。';
  } else if (planType === 'hold') {
    summary = `計画：${HOLD_JA[holdMode]}。${holdMode === 'hold_but_monitor' ? '監視条件は下記の通りです。' : '大きな悪化信号は確認されていません。'}`;
    why = 'ベースシナリオが安定しており、悪化信号が支配的でないため。';
  } else {
    summary = `計画：待ち。${disp}は現時点で入る条件が揃っておらず、条件の成立を待つ局面です。`;
    why = '悪化信号があるか、支持材料が不足しているため。';
  }
  if (marketSession.state === 'closed'
      && (positivePlanSuppressedByClosedSession || planType === 'avoid_chase')) {
    summary += ' ' + PTS_WARNING_JA;
  }

  return {
    symbol: i.symbol.toUpperCase(), assetName: i.assetName, isHeld: i.isHeld,
    planType, currentStance: stance, currentStanceJa: STANCE_JA[stance],
    summaryJa: summary, whyJa: why,
    entryConditionsJa: [
      ...(stance === 'add_only_on_pullback' || planType === 'wait' ? ['出来高を伴う押し目が入り、翌日に安値を割らないこと'] : []),
      ...(squeeze ? ['上昇の主体が買い戻しから実需買いに入れ替わること'] : []),
      ...(event ? [`${evName}の結果と初動反応(金利・為替・指数)の確認`] : []),
      ...(stance === 'small_add_allowed' ? ['出来高を伴って前日高値を維持できるか', '小さく・分割で(全力は計画外)'] : []),
    ].slice(0, 3),
    holdConditionsJa: i.isHeld ? [
      ...(adverse ? ['戻り局面で売りが出るか'] : []),
      ...(heavy || improvingHeavy ? ['上昇日に出来高を伴うか(上値吸収)'] : []),
      ...(squeeze ? ['買い戻し一巡後に失速しないか'] : []),
      '需給・フローの次回更新',
    ].slice(0, 3) : [],
    trimReviewConditionsJa: i.isHeld && (exitMode === 'trim_review' || exitMode === 'risk_reduction_review' || exitMode === 'event_risk_review') ? [
      ...(bigGain ? ['急騰後にFlow悪化(売り抜け推定)と需給の重さが重なった場合'] : []),
      ...(sdBad || flowBad ? ['需給D/E×フロー悪化が2営業日続く場合'] : []),
      ...(event ? [`${evName}の結果が想定と逆で、初動が崩れた場合`] : []),
      ...(highConc ? ['比率の高さが地合い悪化と重なった場合'] : []),
    ].slice(0, 3) : [],
    invalidationJa: [
      ...(event ? [`${evName}の結果が想定と逆なら計画を組み直し`] : []),
      '需給D/Eへの悪化・フロー悪化継続で買い側の計画は無効',
      '出来高を伴う上値更新+需給改善(水準まで軽く)で待ち側の計画は無効',
    ].slice(0, 3),
    nextChecksJa: [
      ...(heavy || improvingHeavy ? ['上昇日に出来高を伴って高値圏で引けるか(上値吸収)'] : []),
      hasSd ? '需給(週次信用残/日次貸借残)の次回更新' : '需給データの取得',
      ...(favorable ? ['実測フローで大口買いが続いているか'] : []),
    ].slice(0, 3),
    whatNotToDoJa: whatNot.slice(0, 4),
    blockingReasons: blocking.slice(0, 4),
    holdModeJa: HOLD_JA[holdMode],
    evidenceQuality: eq,
    marketSession,
  };
}

/** Core Portfolio — 計画サマリ(どこで追加可/ブロック/利確検討/イベント待ちか)。 */
export function planPortfolioSummary(plans: LocalPlan[]): {
  summaryJa: string;
  rows: { label: string; tone: string; names: string[] }[];
} | null {
  if (!plans.length) return null;
  const pick = (pred: (p: LocalPlan) => boolean) =>
    plans.filter(pred).map((p) => jpDisplay(p.symbol, p.assetName)).slice(0, 5);
  const rows = [
    { label: '小さく追加可(注意付き)', tone: 'var(--value-positive)', names: pick((p) => p.currentStance === 'small_add_allowed') },
    { label: '押し目限定', tone: 'var(--accent)', names: pick((p) => p.currentStance === 'add_only_on_pullback') },
    { label: '追いかけ買い注意', tone: 'var(--amber, #fbbf24)', names: pick((p) => p.currentStance === 'avoid_chase') },
    { label: '利確検討/リスク確認', tone: 'var(--value-negative)', names: pick((p) => p.currentStance === 'trim_consideration' || p.currentStance === 'risk_review') },
    { label: 'イベント待ち', tone: 'var(--event-medium)', names: pick((p) => p.planType === 'event_wait') },
  ].filter((r) => r.names.length);
  const c = (s: Stance | 'event') => s === 'event'
    ? plans.filter((p) => p.planType === 'event_wait').length
    : plans.filter((p) => p.currentStance === s).length;
  return {
    summaryJa: `計画サマリ: 小さく追加可${c('small_add_allowed')}件 / 押し目限定${c('add_only_on_pullback')}件 / 追いかけ注意${c('avoid_chase')}件 / リスク確認${plans.filter((p) => ['risk_review', 'trim_consideration'].includes(p.currentStance)).length}件 / イベント待ち${c('event')}件`,
    rows,
  };
}

/** Pro Handoff / AI Review — device-local held-aware planning lines. */
export function ppHandoffTextJa(plans: LocalPlan[]): string {
  if (!plans.length) return '';
  const order: Stance[] = ['risk_review', 'trim_consideration', 'avoid_chase', 'wait',
    'add_only_on_pullback', 'small_add_allowed', 'hold_review', 'monitor', 'no_action', 'unknown'];
  const sorted = [...plans].sort((a, b) =>
    (a.isHeld === b.isHeld ? 0 : a.isHeld ? -1 : 1)
    || order.indexOf(a.currentStance) - order.indexOf(b.currentStance));
  const L = ['## Entry / Exit Planning (device-local, held-aware, 計画であり指示ではない)'];
  for (const p of sorted.slice(0, 6)) {
    L.push(`- [${p.currentStanceJa}${p.isHeld ? '・保有' : ''}] ${jpDisplay(p.symbol, p.assetName)} — ${p.summaryJa.slice(0, 70)}`);
  }
  L.push('無効化条件を必ず併読(条件が崩れた計画は捨てる)。');
  L.push(`注意: ${PLAN_COMPLIANCE_JA}`);
  return L.join('\n');
}

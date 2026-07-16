// V12.2.11 — Today Overview view model(純関数・端末内)。
// 既存レイヤー(judgment / AP / Plan / Brief / Exposure / rates / events)の
// **出力を選択・優先順位付け・重複排除・表示語彙へ変換するだけ**。
// ここで新しい投資判断・スコア・確率を生成しない。データが無い項目は
// 捏造せず落とす(比較元なしで矢印を出さない)。

import type { APItem } from './actionPriority';
import type { LocalPlan } from './positionPlan';
import type { LocalBrief } from './sessionBrief';
import type { LocalStrategy } from './portfolioStrategy';
import type { PortfolioExposure } from './positionExposure';
import { jpDisplay } from '../lib/displayName';

// ── 表示型(元データへの追跡可能性を保持) ──────────────────────────────────

export interface TodayChangeView {
  id: string;
  kind: 'stance' | 'fx' | 'rates' | 'event' | 'quiet';
  labelEn: string;                 // 左列の短い英語ラベル(USD/JPY 等)
  mainJa: string;                  // 変化の1行(149.20 → 150.10 等)
  subJa?: string | null;           // 補足1行(方向・意味)
  asOfJa?: string | null;          // 静かなメタデータ
  tone: 'up' | 'down' | 'risk' | 'neutral';
  hasBaseline: boolean;            // 比較元がある時だけ矢印を出した
}

export interface TodayExposureView {
  id: string;
  symbol: string | null;           // テーマ行はnull
  titleJa: string;                 // 7203 トヨタ / Technology集中 等
  impactEn: string;                // POSITIVE / NEGATIVE / RISK / CONCENTRATED
  severityEn: 'HIGH' | 'MEDIUM' | 'LOW';
  whyJa: string;                   // なぜ自分に関係するか(1文)
  held: boolean;
  source: 'ap' | 'risk' | 'concentration' | 'event';
}

export type ActionTiming = 'NOW' | 'AT OPEN' | 'NEXT' | 'IF';

export interface TodayActionView {
  id: string;
  timing: ActionTiming;
  actionJa: string;                // 行動(1行)
  targetJa?: string | null;        // 対象(銘柄等)
  symbol?: string | null;
  reasonJa: string;                // 理由(1文)
  conditionJa?: string | null;     // 条件(あれば1つ)
  source: 'ap' | 'plan' | 'brief';
  priorityRank?: string | null;
}

export interface TodayNextCheckView {
  whenJa: string;                  // "10:00 JST" / "7/15 21:30 JST"
  whatJa: string;                  // 確認内容(1行)
  source: 'held_condition' | 'market_open' | 'event' | 'brief' | 'routine';
}

export interface TodayOverview {
  sessionHeadingEn: string;        // OVERNIGHT / SINCE OPEN / ...
  sessionStatusJa: string;
  changes: TodayChangeView[];      // ≤4(なければquiet 1件)
  exposures: TodayExposureView[];  // ≤3
  actions: TodayActionView[];      // ≤3(なければno_action 1件)
  nextCheck: TodayNextCheckView;
}

// ── 入力(既存計算の結果のみ・新規取得なし) ─────────────────────────────────

interface RatesPoint {
  latestValue: number; previousValue: number; change: number;
  latestDate: string; status: string;
}

export interface TodayOverviewInput {
  sessionType: string;             // resolveSessionJst の結果(既存の市場時間判定)
  marketStatusJa: string;
  prevJudgment: { date: string; overall: string; posture: string } | null;
  todayOverall: string;
  todayPosture: string;
  usdJpy?: RatesPoint | null;
  us10y?: RatesPoint | null;
  nextEvent: { eventCode: string; title: string; dateJa: string; timeJa: string;
    daysUntil: number; labelJa: string } | null;
  apItems: APItem[];               // rank済み(既存rankItems出力)
  plans: LocalPlan[];
  brief: LocalBrief | null;
  exposure: PortfolioExposure;
  strategy: LocalStrategy | null;
  eventLinkedHeldSymbols: string[];  // D/D-1イベントに紐づく保有銘柄(既存判定)
}

// ── セッション見出し(既存 resolveSessionJst の結果を変換するだけ) ────────────

export function sessionHeading(sessionType: string, marketStatusJa: string): string {
  if (sessionType === 'weekend') return 'WEEKEND';
  if (sessionType === 'morning') return 'OVERNIGHT';
  if (sessionType === 'after_close') return 'SESSION CLOSE';
  if (marketStatusJa.includes('米国')) return 'US SESSION';
  return 'SINCE OPEN';
}

// ── Overnight Changes(実データのみ・最大4件) ────────────────────────────────

function fmtNum(v: number, digits: number): string {
  return v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function buildChanges(i: TodayOverviewInput): TodayChangeView[] {
  const out: TodayChangeView[] = [];
  // 1) 基本姿勢の変化(前回記録がある時だけ — 判断ログ由来の実データ)。
  //    postureはEVENT_WAIT等の内部enumのため下線を除去して表示(生enum禁止)。
  const fmtEnum = (s: string) => (s || '').replace(/_/g, ' ');
  if (i.prevJudgment) {
    const changed = i.prevJudgment.overall !== i.todayOverall
      || i.prevJudgment.posture !== i.todayPosture;
    if (changed) {
      out.push({
        id: 'chg-stance', kind: 'stance', labelEn: 'Stance',
        mainJa: `${i.prevJudgment.overall}(${fmtEnum(i.prevJudgment.posture)}) → ${i.todayOverall}(${fmtEnum(i.todayPosture)})`,
        subJa: '前回記録からの判断変化',
        asOfJa: `前回 ${i.prevJudgment.date.slice(5)}`,
        tone: 'risk', hasBaseline: true,
      });
    }
  }
  // 2) USD/JPY(FREDの実測 latest/previous — 比較元あり)。status='live'のみ
  //    表示(mock/stale等をliveのように出さない — 現行FredStatusはlive|mock)。
  const fx = i.usdJpy;
  if (fx && Number.isFinite(fx.latestValue) && Number.isFinite(fx.previousValue)
      && fx.status === 'live') {
    const up = fx.change > 0;
    out.push({
      id: 'chg-usdjpy', kind: 'fx', labelEn: 'USD/JPY',
      mainJa: `${fmtNum(fx.previousValue, 2)} → ${fmtNum(fx.latestValue, 2)}`,
      subJa: Math.abs(fx.change) < 0.005 ? '横ばい' : up ? '円安方向' : '円高方向',
      asOfJa: fx.latestDate ? `As of ${fx.latestDate}` : null,
      tone: Math.abs(fx.change) < 0.005 ? 'neutral' : up ? 'up' : 'down',
      hasBaseline: true,
    });
  }
  // 3) 米10年金利(同上・liveのみ)
  const r = i.us10y;
  if (r && Number.isFinite(r.latestValue) && Number.isFinite(r.previousValue)
      && r.status === 'live') {
    const up = r.change > 0;
    out.push({
      id: 'chg-us10y', kind: 'rates', labelEn: 'US 10Y',
      mainJa: `${fmtNum(r.previousValue, 2)}% → ${fmtNum(r.latestValue, 2)}%`,
      subJa: Math.abs(r.change) < 0.005 ? '横ばい' : up ? '金利上昇' : '金利低下',
      asOfJa: r.latestDate ? `As of ${r.latestDate}` : null,
      tone: Math.abs(r.change) < 0.005 ? 'neutral' : up ? 'risk' : 'neutral',
      hasBaseline: true,
    });
  }
  // 4) 次の高重要度イベント(方向予測ではなくリスクウィンドウ)
  if (i.nextEvent) {
    out.push({
      id: 'chg-event', kind: 'event', labelEn: 'Major Event',
      mainJa: `${i.nextEvent.eventCode} ${i.nextEvent.dateJa}${i.nextEvent.timeJa ? ` ${i.nextEvent.timeJa}` : ''}`,
      subJa: i.nextEvent.daysUntil === 0 ? '本日 — 結果確認までリスクウィンドウ'
        : `あと${i.nextEvent.daysUntil}日 — 前後は積極判断を控える時間帯`,
      asOfJa: null, tone: 'risk', hasBaseline: false,
    });
  }
  if (!out.length) {
    return [{ id: 'chg-quiet', kind: 'quiet', labelEn: 'Quiet',
      mainJa: '大きな変化なし', subJa: '前回確認時から主要指標に大きな動きはありません',
      asOfJa: null, tone: 'neutral', hasBaseline: false }];
  }
  return out.slice(0, 4);
}

// ── Your Exposure(保有への意味・最大3件) ────────────────────────────────────

function buildExposures(i: TodayOverviewInput): TodayExposureView[] {
  if (i.exposure.noHoldings) return [];
  const out: TodayExposureView[] = [];
  const seen = new Set<string>();
  const push = (v: TodayExposureView) => {
    const k = v.symbol ?? v.id;
    if (seen.has(k) || out.length >= 3) return;
    seen.add(k); out.push(v);
  };
  const riskBySym = new Map(i.exposure.risks.map((r) => [r.symbol, r]));
  const heldAp = sortedAp(i.apItems).filter((a) => a.isHeld);   // 入力順非依存
  const sortedRisks = [...i.exposure.risks].sort((a, b) => {
    const sev = { critical: 0, high: 1, medium: 2, low: 3, unknown: 4 } as Record<string, number>;
    return (sev[a.riskLevel] - sev[b.riskLevel]) || a.symbol.localeCompare(b.symbol);
  });
  // 1) 保有×P0 → 2) 保有×P1 or high/critical risk
  for (const rank of ['P0', 'P1'] as const) {
    for (const a of heldAp.filter((x) => x.priorityRank === rank)) {
      const risk = riskBySym.get(a.symbol);
      push({
        id: `exp-${a.symbol}`, symbol: a.symbol,
        titleJa: jpDisplay(a.symbol, a.assetName),
        impactEn: a.category === 'avoid_chase' ? 'CAUTION' : 'RISK',
        severityEn: rank === 'P0' || risk?.riskLevel === 'critical' ? 'HIGH' : 'MEDIUM',
        whyJa: a.whyJa, held: true, source: 'ap',
      });
    }
  }
  for (const r of sortedRisks.filter((x) => ['high', 'critical'].includes(x.riskLevel))) {
    push({
      id: `exp-${r.symbol}`, symbol: r.symbol,
      titleJa: jpDisplay(r.symbol, i.exposure.notes[r.symbol]?.name ?? r.symbol),
      impactEn: 'RISK', severityEn: r.riskLevel === 'critical' ? 'HIGH' : 'MEDIUM',
      whyJa: r.whyJa || '保有比率とリスク水準の確認が必要', held: true, source: 'risk',
    });
  }
  // 3) 保有×直近イベント対象(入力順非依存)
  for (const sym of [...i.eventLinkedHeldSymbols].sort()) {
    const a = heldAp.find((x) => x.symbol === sym);
    push({
      id: `exp-${sym}`, symbol: sym,
      titleJa: a ? jpDisplay(a.symbol, a.assetName) : sym,
      impactEn: 'EVENT', severityEn: 'MEDIUM',
      whyJa: a?.whyJa ?? '保有銘柄が直近の重要イベントの影響対象です',
      held: true, source: 'event',
    });
  }
  // 4) 集中リスク(既存判定でmaterialな時だけ)
  const s = i.strategy;
  if (s && !s.noHoldings) {
    if (['high', 'critical'].includes(s.themeRisk)) {
      push({ id: 'exp-theme', symbol: null, titleJa: 'テーマ集中',
        impactEn: 'CONCENTRATED', severityEn: s.themeRisk === 'critical' ? 'HIGH' : 'MEDIUM',
        whyJa: '同一テーマの保有比率がポートフォリオ上限に接近しています',
        held: true, source: 'concentration' });
    } else if (['high', 'critical'].includes(String(i.exposure.singleNameRisk))) {
      push({ id: 'exp-single', symbol: i.exposure.top1Symbol ?? null,
        titleJa: `${i.exposure.top1Symbol ?? ''} 集中`.trim(),
        impactEn: 'CONCENTRATED',
        severityEn: i.exposure.singleNameRisk === 'critical' ? 'HIGH' : 'MEDIUM',
        whyJa: '単一銘柄の保有比率が高く、個別要因への感応度が大きい状態です',
        held: true, source: 'concentration' });
    }
  }
  // 5) 埋め草はしない — ただし0件なら保有中の最上位AP 1件だけ(重要度が実在する時)
  if (!out.length) {
    const top = heldAp.find((a) => !['Ignore', 'Unknown'].includes(a.priorityRank));
    if (top && ['P0', 'P1', 'P2'].includes(top.priorityRank)) {
      push({ id: `exp-${top.symbol}`, symbol: top.symbol,
        titleJa: jpDisplay(top.symbol, top.assetName), impactEn: 'WATCH',
        severityEn: 'LOW', whyJa: top.whyJa, held: true, source: 'ap' });
    }
  }
  return out;
}

// ── Action Queue(統合表示・最大3件・決定論+重複排除) ───────────────────────

const ACTION_BUCKET: Record<string, string> = {
  CHECK_NOW: 'check', REVIEW_POSITION: 'check', INVESTIGATE: 'check',
  WAIT_EVENT: 'wait_event', AVOID_CHASE: 'avoid',
  ADD_ONLY_ON_PULLBACK: 'add_cond', SMALL_ADD_ALLOWED: 'add_cond',
  MONITOR: 'monitor', IGNORE_TODAY: 'none', NO_ACTION: 'none', UNKNOWN: 'none',
};
const STANCE_BUCKET: Record<string, string> = {
  risk_review: 'check', hold_review: 'check', trim_consideration: 'trim',
  avoid_chase: 'avoid', add_only_on_pullback: 'add_cond',
  small_add_allowed: 'add_cond', wait: 'wait_event', monitor: 'monitor',
  no_action: 'none', unknown: 'none',
};

// 決定論保証: 入力配列の順序に依存しない(rank→score→symbolで安定ソート)。
const RANK_ORDER = ['P0', 'P1', 'P2', 'P3', 'Watch', 'Ignore', 'Unknown'];

function sortedAp(items: APItem[]): APItem[] {
  return [...items].sort((a, b) =>
    (RANK_ORDER.indexOf(a.priorityRank) - RANK_ORDER.indexOf(b.priorityRank))
    || (b.priorityScore - a.priorityScore)
    || a.symbol.localeCompare(b.symbol));
}

function sortedPlans(plans: LocalPlan[]): LocalPlan[] {
  const st = ['risk_review', 'trim_consideration'];
  return [...plans].sort((a, b) =>
    (st.indexOf(a.currentStance) - st.indexOf(b.currentStance))
    || a.symbol.localeCompare(b.symbol));
}

function apTiming(a: APItem, sessionType: string): ActionTiming {
  if (a.actionLabel === 'WAIT_EVENT') return 'NEXT';
  if (a.actionLabel === 'AVOID_CHASE' || a.actionLabel === 'ADD_ONLY_ON_PULLBACK'
      || a.actionLabel === 'SMALL_ADD_ALLOWED') return 'IF';
  if (a.priorityRank === 'P0') return 'NOW';
  if (sessionType === 'morning') return 'AT OPEN';
  return 'NOW';
}

function buildActions(i: TodayOverviewInput): TodayActionView[] {
  const out: TodayActionView[] = [];
  const seen = new Set<string>();
  // 重複判定 = 銘柄 × 行動の意味バケット × タイミング。
  // 同一symbol・同一action・同一timingは1件に統合するが、NOWとIFのように
  // タイミングが異なる指示は別件として維持する(単純文字列一致に依存しない)。
  const push = (v: TodayActionView, bucket: string) => {
    if (out.length >= 3) return;
    const k = `${v.symbol ?? 'global'}:${bucket}:${v.timing}`;
    if (seen.has(k)) return;
    seen.add(k); out.push(v);
  };
  const one = (s: string) => {
    const cut = s.indexOf('。');
    return cut > 0 ? s.slice(0, cut + 1) : s;
  };
  const ap = sortedAp(i.apItems);
  const plans = sortedPlans(i.plans.filter((p) =>
    ['trim_consideration', 'risk_review'].includes(p.currentStance)));
  // 1) held P0 → 2) held P1 / high risk
  const heldTop = ap.filter((a) => a.isHeld
    && (a.priorityRank === 'P0' || a.priorityRank === 'P1'));
  for (const a of heldTop) {
    push({
      id: `act-${a.symbol}`, timing: apTiming(a, i.sessionType),
      actionJa: a.actionLabelJa, targetJa: jpDisplay(a.symbol, a.assetName),
      symbol: a.symbol, reasonJa: one(a.whyJa),
      conditionJa: a.checkNextJa ? one(a.checkNextJa) : null,
      source: 'ap', priorityRank: a.priorityRank,
    }, ACTION_BUCKET[a.actionLabel] ?? 'check');
  }
  // 3) held×イベント関連(WAIT_EVENT)
  for (const a of ap.filter((x) => x.isHeld && x.actionLabel === 'WAIT_EVENT')) {
    push({
      id: `act-${a.symbol}`, timing: 'NEXT',
      actionJa: 'イベント結果を見てから判断', targetJa: jpDisplay(a.symbol, a.assetName),
      symbol: a.symbol, reasonJa: one(a.whyJa), conditionJa: null,
      source: 'ap', priorityRank: a.priorityRank,
    }, 'wait_event');
  }
  // 4) 既存Action Priority最上位(保有以外も)
  for (const a of ap) {
    if (['Ignore', 'Unknown'].includes(a.priorityRank) || a.actionLabel === 'NO_ACTION') continue;
    push({
      id: `act-${a.symbol}`, timing: apTiming(a, i.sessionType),
      actionJa: a.actionLabelJa, targetJa: jpDisplay(a.symbol, a.assetName),
      symbol: a.symbol, reasonJa: one(a.whyJa),
      conditionJa: a.actionLabel === 'ADD_ONLY_ON_PULLBACK' || a.actionLabel === 'AVOID_CHASE'
        ? one(a.whatWouldChangeJa || a.checkNextJa || '') || null : null,
      source: 'ap', priorityRank: a.priorityRank,
    }, ACTION_BUCKET[a.actionLabel] ?? 'monitor');
  }
  // 5) Position Plan最上位(利確検討/リスク確認はIF条件つき)
  for (const p of plans) {
    push({
      id: `act-plan-${p.symbol}`, timing: 'IF',
      actionJa: p.currentStanceJa, targetJa: jpDisplay(p.symbol, p.assetName),
      symbol: p.symbol, reasonJa: one(p.whyJa || p.summaryJa),
      conditionJa: p.trimReviewConditionsJa[0] ?? p.invalidationJa[0] ?? null,
      source: 'plan', priorityRank: null,
    }, STANCE_BUCKET[p.currentStance] ?? 'check');
  }
  // 6) Session Briefの最重要next action(グローバル1件)
  if (i.brief && out.length < 3 && i.brief.whatNotToDoJa.length) {
    push({
      id: 'act-brief', timing: 'NOW',
      actionJa: i.brief.whatNotToDoJa[0], targetJa: null, symbol: null,
      reasonJa: one(i.brief.headlineJa), conditionJa: null,
      source: 'brief', priorityRank: null,
    }, 'brief_global');
  }
  return out;
}

// ── Next Check(必ず1件) ─────────────────────────────────────────────────────

function buildNextCheck(i: TodayOverviewInput): TodayNextCheckView {
  const one = (s: string) => {
    const cut = s.indexOf('。');
    return cut > 0 ? s.slice(0, cut + 1) : s;
  };
  // 1) 保有×P0のcritical condition
  const p0 = i.apItems.find((a) => a.isHeld && a.priorityRank === 'P0' && a.checkNextJa);
  if (p0) {
    return { whenJa: i.sessionType === 'morning' ? '09:00 JST 寄り付き後' : 'いま',
      whatJa: `${jpDisplay(p0.symbol, p0.assetName)}: ${one(p0.checkNextJa)}`,
      source: 'held_condition' };
  }
  // 2) 次の市場オープン(寄り前のみ — 東証09:00は市場の固定事実)
  if (i.sessionType === 'morning') {
    return { whenJa: '09:00 JST', whatJa: '寄り付き後の値動きと出来高を確認',
      source: 'market_open' };
  }
  // 3) 次の検証済み高重要度イベント(正確な日時があるものだけ)
  if (i.nextEvent && i.nextEvent.timeJa) {
    return { whenJa: `${i.nextEvent.dateJa} ${i.nextEvent.timeJa}`,
      whatJa: `${i.nextEvent.eventCode}発表後にリスク姿勢を再判定`,
      source: 'event' };
  }
  // 4) sessionBrief.nextChecksの最初の有効項目
  const bc = i.brief?.nextChecksJa?.[0];
  if (bc) {
    const when = i.sessionType === 'weekend' ? '次の営業日 09:00 JST'
      : i.sessionType === 'after_close' ? '翌営業日 09:00 JST' : '本日中';
    return { whenJa: when, whatJa: one(bc), source: 'brief' };
  }
  // 5) 既存の実在スケジュール: 平日16:05 = AI見解の自動実行+予測台帳の答え合わせ
  //    (市場全体の定期レビュー時刻ではない — 対象を明示する)
  return { whenJa: '平日 16:05 JST', whatJa: 'AIの定期見解と自己採点の答え合わせを確認',
    source: 'routine' };
}

// ── 本体 ────────────────────────────────────────────────────────────────────

export function buildTodayOverview(i: TodayOverviewInput): TodayOverview {
  return {
    sessionHeadingEn: sessionHeading(i.sessionType, i.marketStatusJa),
    sessionStatusJa: i.marketStatusJa,
    changes: buildChanges(i),
    exposures: buildExposures(i),
    actions: buildActions(i),
    nextCheck: buildNextCheck(i),
  };
}

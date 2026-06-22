// Derives "today's call" (the Daily Command Center hero + sidebar pill) from
// LIVE backend data: action-labels (market posture) + market-regime (axes,
// backdrop, rotations) + events (escalation). Rule-based composition only —
// NO OpenAI/Gemini. ARGUS classifies the present; it does not predict.

import type { ActionKey, CoreActionKey, RiskLevel } from '../types/action';
import type { DailyJudgment, MarketEvent, RegimeTag, EventKind } from '../types/dashboard';
import type { ActionLabelsSnapshot } from '../types/actionLabels';
import type { MarketRegimeSnapshot } from '../types/marketRegime';
import type { EventsSnapshot, CalendarEvent } from '../types/events';

// Backend rule-action strings (spaces) → frontend ActionKey (underscores).
const RULE_TO_KEY: Record<string, ActionKey> = {
  EXIT: 'EXIT', TRIM: 'TRIM', WAIT: 'WAIT',
  'WAIT FOR PULLBACK': 'WAIT_FOR_PULLBACK', 'BUY DIP': 'BUY_DIP',
  ADD: 'ADD', HOLD: 'HOLD',
};

export function mapRuleAction(action: string): ActionKey {
  return RULE_TO_KEY[action] ?? 'HOLD';
}

/** Posture (EVENT_WAIT/RISK_OFF/CAUTIOUS/MIXED/RISK_ON) → overall call + risk.
    Conservative: RISK_ON never upgrades beyond HOLD (no auto-ADD). */
export function postureToCall(posture: string | undefined): { action: ActionKey; risk: RiskLevel } {
  switch (posture) {
    case 'EVENT_WAIT': return { action: 'WAIT', risk: 'high' };
    case 'RISK_OFF':   return { action: 'WAIT', risk: 'high' };
    case 'RISK_ON':    return { action: 'HOLD', risk: 'low' };
    case 'CAUTIOUS':   return { action: 'HOLD', risk: 'med' };
    case 'MIXED':      return { action: 'HOLD', risk: 'med' };
    default:           return { action: 'WAIT', risk: 'med' };
  }
}

export type TodayPhase = 'connecting' | 'live' | 'partial' | 'mock';

export function combinePhase(...phases: TodayPhase[]): TodayPhase {
  if (phases.some((p) => p === 'connecting')) return 'connecting';
  if (phases.every((p) => p === 'live')) return 'live';
  if (phases.every((p) => p === 'mock')) return 'mock';
  return 'partial';
}

const ESC_ORDER: Record<string, number> = { D: 0, 'D-1': 1, 'D-3': 2, 'D-7': 3, 'D+1': 4, normal: 5 };

function upcomingHighImpact(ev: EventsSnapshot | null): CalendarEvent[] {
  return (ev?.events ?? [])
    .filter((e) => e.impact === 'high' && e.daysUntil >= 0)
    .slice()
    .sort((a, b) => (a.daysUntil - b.daysUntil) || ((ESC_ORDER[a.escalation] ?? 9) - (ESC_ORDER[b.escalation] ?? 9)));
}

/** Short token for the header "Next" chip (CPI / FOMC / BOJ …). */
export function shortKind(title: string): string {
  for (const k of ['FOMC', 'CPI', 'PPI', 'PCE', 'BOJ', 'GDP', 'JOLTS']) {
    if (title.includes(k)) return k;
  }
  if (/employment|payroll|nfp/i.test(title)) return 'NFP';
  if (/auction|treasury/i.test(title)) return 'Auction';
  return title.slice(0, 12);
}

function kindOf(e: CalendarEvent): EventKind {
  const t = e.title;
  if (t.includes('FOMC')) return 'FOMC';
  if (t.includes('BOJ') || t.includes('日銀')) return 'BOJ';
  if (t.includes('PCE')) return 'PCE';
  if (t.includes('CPI') || t.includes('PPI')) return 'CPI';
  if (/employment|payroll|jolts|nfp/i.test(t)) return 'NFP';
  if (e.category === 'treasury') return 'TREASURY';
  return 'CB_SPEECH';
}

function eventAtMs(e: CalendarEvent, nowMs: number): number {
  if (e.eventTimeUtc) {
    const t = Date.parse(e.eventTimeUtc);
    if (Number.isFinite(t)) return t;
  }
  if (e.eventDate) {
    const t = Date.parse(`${e.eventDate}T00:00:00+09:00`);
    if (Number.isFinite(t)) return t;
  }
  return nowMs + e.daysUntil * 86_400_000;
}

/** Live events → the Today preview's MarketEvent rows (urgent first). */
export function toMarketEvents(ev: EventsSnapshot | null, nowMs: number): MarketEvent[] {
  return (ev?.events ?? [])
    .filter((e) => e.daysUntil >= 0)
    .slice()
    .sort((a, b) => ((ESC_ORDER[a.escalation] ?? 9) - (ESC_ORDER[b.escalation] ?? 9)) || (a.daysUntil - b.daysUntil))
    .map((e) => ({
      id: e.id,
      kind: kindOf(e),
      title: e.title,
      at: eventAtMs(e, nowMs),
      impact: (e.impact === 'high' ? 'high' : e.impact === 'medium' ? 'med' : 'low') as RiskLevel,
      note: e.rationaleJa || undefined,
    }));
}

/** Compose the hero DailyJudgment from live snapshots. Null-tolerant: missing
    sources degrade to a neutral, clearly-cautious call (never fake certainty). */
export function deriveTodayJudgment(
  al: ActionLabelsSnapshot | null,
  regime: MarketRegimeSnapshot | null,
  ev: EventsSnapshot | null,
  nowMs: number,
): DailyJudgment {
  const posture = al?.marketPosture?.label ?? regime?.regime?.label;
  const call = postureToCall(posture);
  const backdrop = regime?.ratesBackdrop;

  // Risk refinement from the macro backdrop.
  let risk: RiskLevel = call.risk;
  if (backdrop?.posture === 'stress') risk = 'high';
  else if (backdrop?.posture === 'tightening' && risk === 'low') risk = 'med';

  // Regime tags (1–2) for the hero chip row.
  const tags: RegimeTag[] = [];
  if (posture === 'EVENT_WAIT') tags.push('Event Risk');
  else if (posture === 'RISK_OFF') tags.push('Risk Off');
  else if (posture === 'RISK_ON') tags.push('Risk On');
  else if (posture === 'CAUTIOUS') tags.push('Cautious');
  else if (posture === 'MIXED') tags.push('Mixed');
  if (backdrop?.posture === 'tightening' && tags.length < 2) tags.push('Rates Pressure');
  if (backdrop?.posture === 'stress' && tags.length < 2) tags.push('Liquidity Tightening');
  if (tags.length === 0) tags.push('Cautious');

  // Reasons (max 3, deduped, only real data).
  const reasons: string[] = [];
  const push = (s?: string | null) => {
    const t = (s ?? '').trim();
    if (t && !reasons.includes(t) && reasons.length < 3) reasons.push(t);
  };
  push(al?.marketPosture?.rationaleJa);
  push(backdrop?.rationaleJa);
  const nextEv = upcomingHighImpact(ev)[0];
  if (nextEv) {
    push(`${nextEv.title} が接近（${nextEv.escalation === 'normal' ? `あと${nextEv.daysUntil}日` : nextEv.escalation}）。通過後の反応を確認する。`);
  }
  push(regime?.topRotations?.[0]?.evidenceJa);
  if (reasons.length === 0) reasons.push('ライブデータ取得中のため中立的に判断。');

  // Touch / avoid from live rotation groups (inflow→touch, outflow→avoid).
  const groups = (regime?.rotationGroups ?? []).filter((g) => g.available);
  const touch: string[] = [];
  const avoid: string[] = [];
  if (posture === 'EVENT_WAIT' || posture === 'RISK_OFF') {
    touch.push('現金比率(待機資金)');
    avoid.push('新規の高ベータ買い');
  }
  for (const g of groups.slice().sort((a, b) => b.score - a.score)) {
    if (g.status === 'inflow' && touch.length < 3) touch.push(g.label);
    if (g.status === 'outflow' && avoid.length < 3 && !avoid.includes(g.label)) avoid.push(g.label);
  }
  if (touch.length === 0) touch.push('現金比率(中立維持)');
  if (avoid.length === 0) avoid.push('過度な新規エントリー');

  const nextCondition = nextEv
    ? `${nextEv.title}（${nextEv.daysUntil === 0 ? '本日' : `あと${nextEv.daysUntil}日`}）の通過後、金利・指数の反応を確認 → 再評価。`
    : 'レジーム(資金ローテーション)の変化と次の重要イベント日程を確認する。';

  return {
    date: new Date(nowMs).toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' }),
    overall: call.action,
    risk,
    regime: tags.slice(0, 2),
    summary: (regime?.regime?.summaryJa || al?.marketPosture?.rationaleJa || '現在の市場状況を取得中。').trim(),
    reasons,
    assetsToTouch: touch.slice(0, 3),
    assetsToAvoid: avoid.slice(0, 3),
    nextCondition,
    updatedAt: nowMs,
  };
}

/** Core (long-term fund) action under the current posture. Accumulation never
    stops on market mood; only the LUMP-SUM timing defers when cautious. */
export function coreActionFor(posture: string | undefined): { action: CoreActionKey; reason: string } {
  // REGIME-linked 積立 stance — NOT a per-fund price/chart judgment (ARGUS has no
  // live 基準価額/NAV for 投信). For long-term index 積立 you deliberately don't
  // time the fund's chart; you adjust contribution pace by overall posture. The
  // wording makes this explicit so it doesn't look like a failed chart read.
  if (posture === 'EVENT_WAIT' || posture === 'RISK_OFF') {
    return { action: 'DEFER_LUMP_SUM',
             reason: '地合い連動の積立方針: 積立は継続(ドルコスト平均)、一括投入のみイベント/地合い通過まで見送り。※基準価額のチャート判断ではありません。' };
  }
  return { action: 'CONTINUE',
           reason: '地合い連動の積立方針: 積立を予定通り継続(ドルコスト平均)。※個別の基準価額チャート判断ではありません。' };
}

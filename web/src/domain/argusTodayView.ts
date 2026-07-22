import type { DataQuality, SignalCode } from './actionLevel';
import { synthesizeArgusDecision, type ArgusFactor, type ArgusFinalAction,
  type ArgusMarket, type ArgusMarketDecision } from './argusEngine';
import type { MarketCalendarState } from '../types/marketLedger';

export type MarketSelectionMode = 'AUTO' | ArgusMarket;

export interface TodayEventInput {
  id: string; code: string; title: string; at: string | null;
  impact: string; lifecycle?: string; descriptionJa?: string | null;
}
export interface TodayHoldingInput {
  symbol: string; name: string; rank: number; reasonJa: string; statusJa: string;
}
export interface TodayMoveInput {
  id: string; label: string; value: number; previous?: number | null;
  suffix?: string; directionLabel?: string; asOf?: string | null;
}
export interface TodayRecommendationInput { symbol: string; labelJa: string; rank: number }
export interface TodayAttentionInput { id: string; label: string; time?: string | null; severity: number }

export interface ArgusTodayInput {
  now: Date;
  selectionMode: MarketSelectionMode;
  calendar?: Record<string, MarketCalendarState> | null;
  baseSignal: SignalCode;
  jpSignal?: SignalCode | null;
  usSignal?: SignalCode | null;
  confidence: number | null;
  dataQuality: DataQuality;
  closingSignal?: Partial<Record<ArgusMarket, SignalCode | null>>;
  ownerPolicyLimit?: SignalCode | null;
  eventHardVeto?: Partial<Record<ArgusMarket, boolean>>;
  factors?: Partial<Record<ArgusMarket, ArgusFactor[]>>;
  evidence?: Partial<Record<ArgusMarket, string[]>>;
  events?: TodayEventInput[];
  marketMoves?: TodayMoveInput[];
  positioning?: Array<{ key: string; label: string; value: string }>;
  attention?: TodayAttentionInput[];
  holdings?: TodayHoldingInput[];
  concentration?: { risk: string; topTwoPct: number | null } | null;
  recommendations?: TodayRecommendationInput[];
  totalAssetJpy?: number | null;
  review?: { result: string; quality: string } | null;
  systemStatus?: { data: string; backup: string; rule: string };
  conciseAction?: string | null;
  conciseAvoid?: string | null;
}

export interface ArgusTodayView {
  selectedMarket: ArgusMarket;
  selectionMode: MarketSelectionMode;
  sessionLamps: Array<{ key: string; label: string; active: boolean }>;
  nextEvent: TodayEventInput | null;
  comingEvents: TodayEventInput[];
  finalAction: ArgusFinalAction;
  actionScore: number;
  confidence: number | null;
  dataStatus: { code: DataQuality; label: string; tone: 'ok' | 'warn' | 'bad' };
  globalRisk: string | null;
  marketPrice: number | null;
  range: { low: number; high: number } | null;
  invalidation: number | null;
  factors: ArgusFactor[];
  permissions: { newEntry: boolean; add: boolean; hold: boolean };
  conciseAction: string | null;
  conciseAvoid: string | null;
  marketMoves: TodayMoveInput[];
  positioning: Array<{ key: string; label: string; value: string }>;
  attention: TodayAttentionInput[];
  holdingsReview: TodayHoldingInput[];
  portfolioConcentration: { risk: string; topTwoPct: number | null } | null;
  recommendations: TodayRecommendationInput[];
  fireProgress: { totalJpy: number; firstGoalPct: number; secondGoalJpy: number } | null;
  reviewSummary: { result: string; quality: string } | null;
  systemStatus: { data: string; backup: string; rule: string };
  decisions: Record<ArgusMarket, ArgusMarketDecision>;
  footerText: string;
}

const OPEN_JP = new Set(['MORNING_SESSION', 'AFTERNOON_SESSION']);
const ACTIVE_US = new Set(['PRE_MARKET', 'REGULAR']);

function sessionLabel(market: ArgusMarket, state?: MarketCalendarState): string {
  if (!state) return `${market} CLOSED`;
  if (!state.isTradingDay) return `${market} HOLIDAY`;
  const labels: Record<string, string> = market === 'JP'
    ? { PRE_OPEN: 'JP PRE', MORNING_SESSION: 'JP OPEN', LUNCH_BREAK: 'JP LUNCH',
      AFTERNOON_SESSION: 'JP OPEN', CLOSED: 'JP CLOSED', HOLIDAY_CLOSED: 'JP HOLIDAY' }
    : { PRE_MARKET: 'US PRE', REGULAR: 'US OPEN', AFTER_HOURS: 'US AFTER',
      CLOSED: 'US CLOSED', HOLIDAY_CLOSED: 'US HOLIDAY' };
  return labels[state.session] ?? `${market} CLOSED`;
}

export function selectAutoMarket(calendar?: Record<string, MarketCalendarState> | null): ArgusMarket {
  const jp = calendar?.JP, us = calendar?.US;
  if (jp && OPEN_JP.has(jp.session)) return 'JP';
  if (us && ACTIVE_US.has(us.session)) return 'US';
  if (jp?.session === 'LUNCH_BREAK') return 'JP';
  if (us?.session === 'AFTER_HOURS') return 'JP';
  if (jp?.isTradingDay && jp.session === 'PRE_OPEN') return 'JP';
  if (us?.isTradingDay && us.session === 'PRE_MARKET') return 'US';
  const jn = jp?.nextTradingDay ?? '9999-12-31';
  const un = us?.nextTradingDay ?? '9999-12-31';
  return jn <= un ? 'JP' : 'US';
}

function eventEpoch(event: TodayEventInput): number | null {
  if (!event.at) return null;
  const t = Date.parse(event.at);
  return Number.isFinite(t) ? t : null;
}

function dataStatus(code: DataQuality): ArgusTodayView['dataStatus'] {
  if (code === 'LIVE') return { code, label: '正常', tone: 'ok' };
  if (['PARTIAL', 'DELAYED', 'STALE'].includes(code)) return { code, label: '一部不足', tone: 'warn' };
  return { code, label: '要確認', tone: 'bad' };
}

export function buildArgusTodayView(input: ArgusTodayInput): ArgusTodayView {
  const selectedMarket = input.selectionMode === 'AUTO'
    ? selectAutoMarket(input.calendar) : input.selectionMode;
  const make = (market: ArgusMarket) => synthesizeArgusDecision({
    market,
    baseSignal: (market === 'JP' ? input.jpSignal : input.usSignal) ?? input.baseSignal,
    confidence: input.confidence,
    dataQuality: input.dataQuality,
    closingWindowSignal: input.closingSignal?.[market],
    ownerPolicyLimit: input.ownerPolicyLimit,
    eventHardVeto: input.eventHardVeto?.[market],
    factors: input.factors?.[market], evidence: input.evidence?.[market],
    calculatedAt: input.now.toISOString(),
  });
  const decisions = { JP: make('JP'), US: make('US') };
  const decision = decisions[selectedMarket];
  const nowMs = input.now.getTime();
  const future = [...(input.events ?? [])]
    .map((event) => ({ event, at: eventEpoch(event) }))
    .filter((x): x is { event: TodayEventInput; at: number } => x.at != null && x.at >= nowMs
      && !['RELEASED', 'RESOLVED'].includes(x.event.lifecycle ?? ''))
    .sort((a, b) => a.at - b.at || a.event.id.localeCompare(b.event.id));
  const nextEvent = future[0]?.event ?? null;
  const limit30d = nowMs + 30 * 86_400_000;
  const comingEvents = future.slice(1).filter((x) => x.at <= limit30d).slice(0, 3).map((x) => x.event);
  const permissions = {
    newEntry: decision.actionScore === 7,
    add: decision.actionScore === 7,
    hold: decision.actionScore > 1,
  };
  const eventTag = nextEvent ? `${nextEvent.code} ${formatEventTime(nextEvent.at)}` : `DATA ${dataStatus(input.dataQuality).label}`;
  return {
    selectedMarket, selectionMode: input.selectionMode,
    sessionLamps: [
      { key: 'JP', label: sessionLabel('JP', input.calendar?.JP), active: !!input.calendar?.JP?.isTradingDay && OPEN_JP.has(input.calendar.JP.session) },
      { key: 'US', label: sessionLabel('US', input.calendar?.US), active: !!input.calendar?.US?.isTradingDay && input.calendar.US.session === 'REGULAR' },
      { key: 'FX', label: 'FX 24H', active: true },
      { key: 'CRYPTO', label: 'CRYPTO 24H', active: true },
    ],
    nextEvent, comingEvents,
    finalAction: decision.finalAction, actionScore: decision.actionScore,
    confidence: decision.confidence, dataStatus: dataStatus(input.dataQuality),
    globalRisk: decision.globalRisk === 'normal' ? null : decision.globalRisk.toUpperCase(),
    marketPrice: null, range: null, invalidation: null,
    factors: decision.factors.slice(0, 5), permissions,
    conciseAction: input.conciseAction ? input.conciseAction.slice(0, 32) : null,
    conciseAvoid: input.conciseAvoid ? input.conciseAvoid.slice(0, 32) : null,
    marketMoves: (input.marketMoves ?? []).slice(0, 6),
    positioning: (input.positioning ?? []).slice(0, 5),
    attention: [...(input.attention ?? [])]
      .filter((row) => row.id !== nextEvent?.id)
      .sort((a, b) => b.severity - a.severity || a.id.localeCompare(b.id)).slice(0, 3),
    holdingsReview: dedupeHoldings(input.holdings ?? []),
    portfolioConcentration: input.concentration ?? null,
    recommendations: [...(input.recommendations ?? [])].sort((a, b) => a.rank - b.rank || a.symbol.localeCompare(b.symbol)).slice(0, 3),
    fireProgress: typeof input.totalAssetJpy === 'number' && input.totalAssetJpy >= 0
      ? { totalJpy: input.totalAssetJpy, firstGoalPct: Math.min(100, input.totalAssetJpy / 100_000_000 * 100), secondGoalJpy: 400_000_000 }
      : null,
    reviewSummary: input.review ?? null,
    systemStatus: input.systemStatus ?? { data: dataStatus(input.dataQuality).label, backup: '確認', rule: 'DETERMINISTIC' },
    decisions,
    footerText: `${selectedMarket} ${decision.finalAction} ${decision.actionScore}/7   ${eventTag}`,
  };
}

function dedupeHoldings(rows: TodayHoldingInput[]): TodayHoldingInput[] {
  const seen = new Set<string>();
  return [...rows].sort((a, b) => a.rank - b.rank || a.symbol.localeCompare(b.symbol))
    .filter((row) => { const key = row.symbol.toUpperCase(); if (seen.has(key)) return false; seen.add(key); return true; })
    .slice(0, 3);
}

export function formatEventTime(value: string | null): string {
  if (!value) return '';
  const t = Date.parse(value);
  if (!Number.isFinite(t)) return '';
  return new Date(t).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

import type { DataQuality, SignalCode } from './actionLevel';
import { synthesizeArgusDecision, type ArgusFactor, type ArgusFinalAction,
  type ArgusMarket, type ArgusMarketDecision } from './argusEngine';
import type { MarketCalendarState } from '../types/marketLedger';
import type { ChartBar, PriceZone } from '../types/chartIntelligence';

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
  status?: 'realtime' | 'delayed' | 'close' | string;
  history?: Array<{ date: string; value: number }>;
}
export interface TodayAttentionInput { id: string; label: string; time?: string | null; severity: number }
export interface TodayNewsInput {
  id: string; titleJa: string; source: string; url: string; publishedAt?: number | null;
}
export interface TodayNewsCandidate extends TodayNewsInput {
  major: boolean; relevant?: boolean; translationStatus?: string;
  tier?: string; corroboration?: string; titleOriginal?: string;
  linkedSymbols?: string[]; scope?: 'holding' | 'watchlist' | 'index' | 'global' | 'other';
}
export interface TodayProjectionInput {
  symbol: string; label: string; asOf: string | null; status: string;
  bars: ChartBar[]; zones: PriceZone[]; timeframe?: 'daily' | 'weekly';
  quoteState?: 'realtime' | 'delayed' | 'close'; sourceHistoryCount?: number;
}
export interface TodayProjection {
  symbol: string; label: string; asOf: string | null; current: number;
  history: Array<{ date: string; value: number }>;
  baseLow: number; baseHigh: number; upside: number; downside: number;
  invalidation: number; horizon: string; directionLabel: string;
  confidenceLabel: '低' | '中'; probability: null; methodLabel: string;
  timeframeLabel: string; quoteState: string; sourceHistoryCount: number;
}
export interface TodayReviewInput {
  action: string; marketLabel: string; returnPct: number | null; evaluationJa: string;
  horizon: string; decisionDate: string; outcomeDate: string | null; matured: boolean;
}
export interface TodayPositioningRow {
  key: string; label: string; value: string; detail?: string;
  tone?: 'positive' | 'negative' | 'neutral';
}

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
  indexMoves?: TodayMoveInput[];
  macroMoves?: TodayMoveInput[];
  positioning?: Partial<Record<ArgusMarket, TodayPositioningRow[]>>;
  news?: TodayNewsInput[];
  projection?: Partial<Record<ArgusMarket, TodayProjectionInput | null>>;
  attention?: TodayAttentionInput[];
  holdings?: TodayHoldingInput[];
  review?: Partial<Record<ArgusMarket, TodayReviewInput | null>>;
  systemStatus?: { data: string; backup: string; rule: string };
  conciseAction?: string | null;
  conciseAvoid?: string | null;
}

export interface ArgusTodayView {
  selectedMarket: ArgusMarket;
  selectionMode: MarketSelectionMode;
  sessionLamps: Array<{ key: string; label: string; active: boolean; tone: 'open' | 'standby' | 'closed' }>;
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
  projection: TodayProjection | null;
  factors: ArgusFactor[];
  permissions: { newEntry: boolean; add: boolean; hold: boolean };
  conciseAction: string | null;
  conciseAvoid: string | null;
  indexMoves: TodayMoveInput[];
  macroMoves: TodayMoveInput[];
  positioning: TodayPositioningRow[];
  news: TodayNewsInput[];
  attention: TodayAttentionInput[];
  holdingsReview: TodayHoldingInput[];
  reviewSummary: TodayReviewInput | null;
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
  const projection = buildTodayProjection(input.projection?.[selectedMarket] ?? null,
    decision.finalAction);
  const eventTag = nextEvent ? `${nextEvent.code} ${formatEventTime(nextEvent.at)}` : `DATA ${dataStatus(input.dataQuality).label}`;
  return {
    selectedMarket, selectionMode: input.selectionMode,
    sessionLamps: [
      { key: 'JP', label: sessionLabel('JP', input.calendar?.JP),
        active: !!input.calendar?.JP?.isTradingDay && OPEN_JP.has(input.calendar.JP.session),
        tone: input.calendar?.JP?.isTradingDay && OPEN_JP.has(input.calendar.JP.session) ? 'open'
          : input.calendar?.JP?.isTradingDay && ['PRE_OPEN', 'LUNCH_BREAK'].includes(input.calendar.JP.session) ? 'standby' : 'closed' },
      { key: 'US', label: sessionLabel('US', input.calendar?.US),
        active: !!input.calendar?.US?.isTradingDay && input.calendar.US.session === 'REGULAR',
        tone: input.calendar?.US?.isTradingDay && input.calendar.US.session === 'REGULAR' ? 'open'
          : input.calendar?.US?.isTradingDay && ['PRE_MARKET', 'AFTER_HOURS'].includes(input.calendar.US.session) ? 'standby' : 'closed' },
      { key: 'FX', label: 'FX 24H', active: true, tone: 'open' },
      { key: 'CRYPTO', label: 'CRYPTO 24H', active: true, tone: 'open' },
    ],
    nextEvent, comingEvents,
    finalAction: decision.finalAction, actionScore: decision.actionScore,
    confidence: decision.confidence, dataStatus: dataStatus(input.dataQuality),
    globalRisk: decision.globalRisk === 'normal' ? null : decision.globalRisk.toUpperCase(),
    marketPrice: projection?.current ?? null,
    range: projection ? { low: projection.baseLow, high: projection.baseHigh } : null,
    invalidation: projection?.invalidation ?? null,
    projection,
    factors: decision.factors.slice(0, 5), permissions,
    conciseAction: input.conciseAction ? input.conciseAction.slice(0, 32) : null,
    conciseAvoid: input.conciseAvoid ? input.conciseAvoid.slice(0, 32) : null,
    indexMoves: (input.indexMoves ?? input.marketMoves ?? []).slice(0, 4),
    macroMoves: (input.macroMoves ?? (input.marketMoves ?? []).slice(4)).slice(0, 3),
    positioning: (input.positioning?.[selectedMarket] ?? [])
      .filter((row) => row.value.trim() !== '—').slice(0, 5),
    news: dedupeNews(input.news ?? []),
    attention: [...(input.attention ?? [])]
      .filter((row) => row.id !== nextEvent?.id)
      .sort((a, b) => b.severity - a.severity || a.id.localeCompare(b.id)).slice(0, 3),
    holdingsReview: dedupeHoldings(input.holdings ?? []),
    reviewSummary: input.review?.[selectedMarket] ?? null,
    systemStatus: input.systemStatus ?? { data: dataStatus(input.dataQuality).label, backup: '確認', rule: 'DETERMINISTIC' },
    decisions,
    footerText: `${selectedMarket} ${decision.finalAction} ${decision.actionScore}/7   ${eventTag}`,
  };
}

/**
 * Todayの小型予測図は、Chart Intelligenceの実測終値・ATR14・確認済み価格帯だけ
 * から作る。確率校正はここでは行わず、数値確率は常にnullのままにする。
 */
export function buildTodayProjection(input: TodayProjectionInput | null,
  action: ArgusFinalAction): TodayProjection | null {
  if (!input) return null;
  const bars = input.bars.filter((bar) => Number.isFinite(bar.close) && bar.close > 0).slice(-30);
  const last = bars.at(-1);
  const atr = last?.atr14;
  if (!last || bars.length < 20 || atr == null || !Number.isFinite(atr) || atr <= 0) return null;
  const current = last.close;
  const zones = input.zones.filter((zone) => zone.status !== 'unconfirmed'
    && Number.isFinite(zone.lower) && Number.isFinite(zone.upper));
  const below = zones.filter((zone) => zone.center < current).sort((a, b) => b.center - a.center)[0];
  const above = zones.filter((zone) => zone.center > current).sort((a, b) => a.center - b.center)[0];
  const baseLow = Math.max(0.000001, current - atr);
  const baseHigh = current + atr;
  // 「上／本線／下」の表示順が逆転しないよう、近いゾーンがATR本線内にある場合は
  // 2ATR側をシナリオ端に採用する。ゾーン自体は無効化ラインに引き続き使用する。
  const downside = Math.min(below?.center ?? current, Math.max(0.000001, current - 2 * atr));
  const upside = Math.max(above?.center ?? current, current + 2 * atr);
  const invalidation = action === 'SELL' ? (above?.upper ?? current + 2 * atr)
    : (below?.lower ?? Math.max(0.000001, current - 2 * atr));
  return {
    symbol: input.symbol, label: input.label, asOf: input.asOf, current,
    history: bars.map((bar) => ({ date: bar.date, value: bar.close })),
    baseLow, baseHigh, upside, downside, invalidation,
    horizon: '5営業日',
    directionLabel: action === 'BUY' ? '上方向優勢' : action === 'SELL' ? '下方向警戒' : '本線内で待機',
    confidenceLabel: input.status === 'live' && bars.length >= 25 ? '中' : '低',
    probability: null,
    methodLabel: '実測終値 + ATR14 + 確認済み支持抵抗',
    timeframeLabel: input.timeframe === 'weekly' ? '週足' : '日足',
    quoteState: input.quoteState ?? (input.status === 'delayed' ? 'delayed' : 'close'),
    sourceHistoryCount: input.sourceHistoryCount ?? input.bars.length,
  };
}

/** 前回判断の翌1営業日だけを採点する。翌バーが無ければ0%ではなく未成熟。 */
export function buildTodayReview(bars: Array<{ date: string; close: number }>, symbolLabel: string,
  action: string, decisionDate: string): TodayReviewInput {
  const valid = bars.filter((bar) => Number.isFinite(bar.close) && bar.close > 0)
    .slice().sort((a, b) => a.date.localeCompare(b.date));
  const base = [...valid].reverse().find((bar) => bar.date <= decisionDate) ?? null;
  const outcome = base ? valid.find((bar) => bar.date > base.date) ?? null : null;
  const finalAction = ['ADD', 'BUY_DIP'].includes(action) ? 'BUY'
    : ['EXIT', 'TRIM'].includes(action) ? 'SELL' : 'WAIT';
  const returnPct = base && outcome
    ? Math.round((outcome.close - base.close) / base.close * 10_000) / 100 : null;
  let evaluationJa = '答え合わせ待ち';
  if (returnPct != null) {
    if (finalAction === 'BUY') evaluationJa = returnPct > 0 ? '上方向判断を支持' : '上方向判断を反証';
    else if (finalAction === 'SELL') evaluationJa = returnPct < 0 ? '防御判断を支持' : '防御判断を反証';
    else evaluationJa = returnPct <= -1 ? '追い買い回避は妥当'
      : returnPct >= 2 ? '上昇を取り逃した可能性' : '待機継続は妥当';
  }
  return { action: finalAction, marketLabel: symbolLabel, returnPct, evaluationJa,
    horizon: '翌1営業日', decisionDate, outcomeDate: outcome?.date ?? null, matured: !!outcome };
}

const INDEX_NEWS = /(日経|nikkei|topix|s&p|nasdaq|dow|株式市場|stock market|equity market)/i;
const GLOBAL_NEWS = /(戦争|侵攻|制裁|金融危機|銀行破綻|緊急利上げ|緊急利下げ|緊急決定|war|invasion|sanction|financial crisis|bank failure|emergency rate)/i;

/** Today用ニュースは、処理済みかつ判断変更に関係するものだけを最大3件にする。 */
export function selectTodayNews(candidates: TodayNewsCandidate[], symbols: string[]): TodayNewsInput[] {
  const universe = symbols.map((value) => value.trim().toUpperCase()).filter(Boolean);
  const seen = new Set<string>();
  return candidates.filter((item) => {
    if (!item.major || item.relevant === false || !item.titleJa.trim() || !item.source || !item.url) return false;
    if (!['translated', 'not_needed'].includes(item.translationStatus ?? '')) return false;
    if (!['official', 'corroborated'].includes(item.corroboration ?? '')) return false;
    const text = `${item.titleJa} ${item.titleOriginal ?? ''}`;
    const linked = (item.linkedSymbols ?? []).map((value) => value.toUpperCase());
    const universeMatch = linked.some((symbol) => universe.includes(symbol))
      || universe.some((symbol) => symbol.length >= 3 && text.toUpperCase().includes(symbol));
    const allowedScope = item.scope === 'holding' || item.scope === 'watchlist'
      || item.scope === 'index' || item.scope === 'global';
    if (!allowedScope && !universeMatch && !INDEX_NEWS.test(text) && !GLOBAL_NEWS.test(text)) return false;
    const key = `${item.source}:${item.titleJa}`.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).sort((a, b) => (b.publishedAt ?? 0) - (a.publishedAt ?? 0))
    .slice(0, 3).map(({ id, titleJa, source, url, publishedAt }) => ({ id, titleJa, source, url, publishedAt }));
}

function dedupeHoldings(rows: TodayHoldingInput[]): TodayHoldingInput[] {
  const seen = new Set<string>();
  return [...rows].sort((a, b) => a.rank - b.rank || a.symbol.localeCompare(b.symbol))
    .filter((row) => { const key = row.symbol.toUpperCase(); if (seen.has(key)) return false; seen.add(key); return true; })
    .slice(0, 3);
}

function dedupeNews(rows: TodayNewsInput[]): TodayNewsInput[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = `${row.source}:${row.titleJa}`.toLowerCase();
    if (!row.titleJa.trim() || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 3);
}

export function formatEventTime(value: string | null): string {
  if (!value) return '';
  const t = Date.parse(value);
  if (!Number.isFinite(t)) return '';
  return new Date(t).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

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
  symbol?: string; market?: ArgusMarket;
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
  instrumentId?: string; source?: string; availableFrom?: string | null;
  eventMarkers?: Array<{ id: string; date: string; labelJa: string; kind: string }>;
  turningPoints?: Array<{ id: string; effectiveFrom: string; status: string; direction: string; facts: string[] }>;
  calibration?: { historyCount: number; calibrationVersion: string; horizons: Record<string, TodayCalibrationInput> };
  shortSelling?: TodayShortSellingSummary | null;
  failedRally?: TodayFailedRally | null;
}
export interface TodayCalibrationInput {
  horizon: number; rawOccurrenceCount: number; episodeCount: number; effectiveSampleCount: number;
  calibrationStatus: string; probabilities: { UP: number; RANGE: number; DOWN: number } | null;
  brierScore?: number | null; confidenceInterval?: Record<string, { low: number; high: number }> | null;
  averageReactionDelay?: number | null;
  returnDistribution?: { q10: number | null; q25: number | null; median: number | null;
    q75: number | null; q90: number | null; meanMfe: number | null; meanMae: number | null };
  targetProbabilities?: { upperTargetTouch: number | null; baseRangeClose: number | null;
    lowerTargetTouch: number | null; invalidationTouch: number | null } | null;
}
export interface TodayShortSellingSummary {
  status: string; historyStart: string | null; historyCount: number; latestDate?: string;
  missingReason?: string | null; latest: null | { date: string; totalShortRatio: number;
    previousDayDifference: number | null; average5: number | null; average20: number | null;
    rollingPercentile: number | null; source: string; availableFrom: string };
}
export interface TodayFailedRally {
  state: 'NONE' | 'WATCH' | 'CONFIRMED'; facts: string[]; probability: number | null;
  metrics: Record<string, number | null>;
  backtest: { rawOccurrenceCount: number; episodeCount: number; effectiveSampleCount: number;
    calibrationStatus: string; probability: number | null; outcomes: Record<string, unknown> };
}
export interface TodayProjection {
  symbol: string; instrumentId: string; label: string; asOf: string | null; current: number;
  history: Array<{ date: string; value: number }>;
  baseLow: number; baseHigh: number; upside: number; downside: number;
  invalidation: number; support: { low: number; high: number } | null;
  resistance: { low: number; high: number } | null;
  horizon: string; horizonDays: 1 | 5 | 20; directionLabel: string;
  confidenceLabel: '低' | '中' | '高'; probability: { UP: number; RANGE: number; DOWN: number } | null;
  calibrationStatus: string; rawSampleCount: number; episodeCount: number; effectiveSampleCount: number;
  brierScore: number | null; confidenceInterval: Record<string, { low: number; high: number }> | null;
  targetProbabilities: TodayCalibrationInput['targetProbabilities']; reactionDelay: number | null;
  methodLabel: string; timeframeLabel: string; quoteState: string; sourceHistoryCount: number;
  source: string; availableFrom: string | null;
  eventMarkers: Array<{ id: string; date: string; labelJa: string; kind: string }>;
  activeTurningPoint: { id: string; date: string; direction: string; label: string } | null;
  shortSelling: TodayShortSellingSummary | null; failedRally: TodayFailedRally | null;
}
export interface TodayReviewInput {
  action: string; marketLabel: string; returnPct: number | null; evaluationJa: string;
  horizon: string; decisionDate: string; outcomeDate: string | null; matured: boolean;
  status: 'matured' | 'immature' | 'missing_price';
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
  selectedInstrument?: Partial<Record<ArgusMarket, string>>;
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
  projectionsByHorizon: Partial<Record<'1D' | '5D' | '20D', TodayProjection>>;
  selectedInstrument: { symbol: string; instrumentId: string; label: string } | null;
  shortSellingSummary: TodayShortSellingSummary | null;
  failedRallyState: TodayFailedRally | null;
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
  const projectionInput = input.projection?.[selectedMarket] ?? null;
  const projectionsByHorizon: ArgusTodayView['projectionsByHorizon'] = {};
  for (const days of [1, 5, 20] as const) {
    const built = buildTodayProjection(projectionInput, decision.finalAction, days);
    if (built) projectionsByHorizon[`${days}D` as const] = built;
  }
  const projection = projectionsByHorizon['5D'] ?? null;
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
    projection, projectionsByHorizon,
    selectedInstrument: projection ? { symbol: projection.symbol,
      instrumentId: projection.instrumentId, label: projection.label } : null,
    shortSellingSummary: projection?.shortSelling ?? null,
    failedRallyState: projection?.failedRally ?? null,
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

/** Todayの予測図は、実測OHLCVとサーバー側walk-forward校正結果だけを描く。 */
export function buildTodayProjection(input: TodayProjectionInput | null,
  action: ArgusFinalAction, horizonDays: 1 | 5 | 20 = 5): TodayProjection | null {
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
  const calibrated = input.calibration?.horizons[String(horizonDays)];
  const distribution = calibrated?.returnDistribution;
  const priceAt = (value: number | null | undefined, fallback: number) =>
    value == null || !Number.isFinite(value) ? fallback : Math.max(0.000001, current * (1 + value));
  const horizonAtr = atr * Math.sqrt(horizonDays / 5);
  const baseLow = priceAt(distribution?.q25, Math.max(0.000001, current - horizonAtr));
  const baseHigh = priceAt(distribution?.q75, current + horizonAtr);
  const downside = Math.min(below?.center ?? current,
    priceAt(distribution?.q25, Math.max(0.000001, current - 2 * horizonAtr)));
  const upside = Math.max(above?.center ?? current,
    priceAt(distribution?.q75, current + 2 * horizonAtr));
  const invalidation = action === 'SELL'
    ? priceAt(distribution?.q90, above?.upper ?? current + 2 * horizonAtr)
    : priceAt(distribution?.q10, below?.lower ?? Math.max(0.000001, current - 2 * horizonAtr));
  const activePoint = [...(input.turningPoints ?? [])].reverse()
    .find((point) => point.status === 'confirmed' || point.status === 'candidate');
  const probabilities = calibrated?.calibrationStatus === 'calibrated'
    ? calibrated.probabilities : null;
  return {
    symbol: input.symbol, instrumentId: input.instrumentId ?? input.symbol,
    label: input.label, asOf: input.asOf, current,
    history: bars.map((bar) => ({ date: bar.date, value: bar.close })),
    baseLow: Math.min(baseLow, baseHigh), baseHigh: Math.max(baseLow, baseHigh),
    upside, downside, invalidation,
    support: below ? { low: below.lower, high: below.upper } : null,
    resistance: above ? { low: above.lower, high: above.upper } : null,
    horizon: `${horizonDays}営業日`, horizonDays,
    directionLabel: probabilities
      ? (probabilities.UP > probabilities.DOWN && probabilities.UP > probabilities.RANGE ? '上方向優勢'
        : probabilities.DOWN > probabilities.UP && probabilities.DOWN > probabilities.RANGE ? '下方向警戒' : '本線内で待機')
      : action === 'BUY' ? '上方向優勢' : action === 'SELL' ? '下方向警戒' : '本線内で待機',
    confidenceLabel: probabilities && (calibrated?.effectiveSampleCount ?? 0) >= 60 ? '高'
      : input.status === 'live' && bars.length >= 25 ? '中' : '低',
    probability: probabilities,
    calibrationStatus: calibrated?.calibrationStatus ?? 'not_available',
    rawSampleCount: calibrated?.rawOccurrenceCount ?? 0,
    episodeCount: calibrated?.episodeCount ?? 0,
    effectiveSampleCount: calibrated?.effectiveSampleCount ?? 0,
    brierScore: calibrated?.brierScore ?? null,
    confidenceInterval: calibrated?.confidenceInterval ?? null,
    targetProbabilities: calibrated?.targetProbabilities ?? null,
    reactionDelay: calibrated?.averageReactionDelay ?? null,
    methodLabel: `実測OHLCV + 類似局面 + ATR14 + 支持抵抗 · ${input.calibration?.calibrationVersion ?? '未校正'}`,
    timeframeLabel: input.timeframe === 'weekly' ? '週足' : '日足',
    quoteState: input.quoteState ?? (input.status === 'delayed' ? 'delayed' : 'close'),
    sourceHistoryCount: input.sourceHistoryCount ?? input.bars.length,
    source: input.source ?? 'existing_market_data_cache',
    availableFrom: input.availableFrom ?? null,
    eventMarkers: (input.eventMarkers ?? []).filter((event) =>
      bars.some((bar) => bar.date === event.date)).slice(-4),
    activeTurningPoint: activePoint ? { id: activePoint.id, date: activePoint.effectiveFrom,
      direction: activePoint.direction, label: activePoint.facts[0] ?? 'Turning Point' } : null,
    shortSelling: input.shortSelling ?? null,
    failedRally: input.failedRally ?? null,
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
  const latestDate = valid.at(-1)?.date ?? null;
  const status: TodayReviewInput['status'] = outcome ? 'matured'
    : !base && latestDate && latestDate > decisionDate ? 'missing_price' : 'immature';
  if (status === 'missing_price') evaluationJa = '価格取得待ち';
  return { action: finalAction, marketLabel: symbolLabel, returnPct, evaluationJa,
    horizon: '翌1営業日', decisionDate, outcomeDate: outcome?.date ?? null,
    matured: !!outcome, status };
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

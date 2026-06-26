import { resolveSignal, SIGNALS, OVERRIDE_LABEL_JA, type SignalCode, type OwnerState } from './actionLevel';

// One unified per-stock card model (v10.140) — the Today page shows ONE card per
// stock that merges everything ARGUS knows about it (action level, downside cause,
// 24/7 events, flow, linked macro events) instead of scattering it across separate
// Downside / Event / News sections. Pure + deterministic; no order/broker logic.

export type AiFreshness = 'fresh' | 'stale' | 'unavailable' | 'rule_only';
export type NewsClass = 'CONFIRMED' | 'LIKELY_RELATED' | 'BACKGROUND' | 'UNCONFIRMED';

export interface TimelineItem { time: string; textJa: string; tone: 'up' | 'down' | 'flow' | 'news' | 'flat'; }
export interface CauseSlice { labelJa: string; pct: number; }
export interface NewsItem { time: string; textJa: string; cls: NewsClass; }
export interface LinkedEventTag { code: string; countdown: string; impact: string; }

export interface AssetCardModel {
  id: string;
  symbol: string;
  name: string;
  market: string;
  held: boolean;
  ownerState?: OwnerState;
  changePct: number | null;
  price: number | null;
  flowRatio: number | null;
  signalCode: SignalCode;
  signalLevel: number;
  permNewEntry: 'BLOCKED' | 'ALLOWED';
  permAdd: 'BLOCKED' | 'ALLOWED';
  permExistingJa: string;
  argusViewJa: string;          // one-line resolved view (header)
  overallJa: string | null;     // the full Japanese overall sentence (incident reasonJa)
  hasIncident: boolean;         // → embed the deep cause-attribution stack on expand
  causeOneLineJa: string | null;
  causeSlices: CauseSlice[];
  timeline: TimelineItem[];
  news: NewsItem[];
  nextJa: string;
  lastUpdate: string | null;    // HH:MM JST
  linkedEvents: LinkedEventTag[];
  aiFreshness: AiFreshness;
  judgmentSource: 'ai' | 'rule';   // 'ai' = displayed call is the GPT+Gemini loop output; 'rule' = guardrail
  autoExpand: boolean;          // held-critical / worsened / new official / cause shift
  severityRank: number;         // for sort
}

// ── inputs (loosely typed against the existing hook shapes) ──
interface LabelLike { symbol: string; action: string; reasonJa?: string; nextConditionJa?: string;
  supportingData?: { price?: number | null; changePct?: number; bigFlowRatio?: number | null; quoteDate?: string | null }; status?: string;
  judgmentSource?: 'ai' | 'rule'; }   // 'ai' = the displayed call is GPT+Gemini's; 'rule' = guardrail fallback
interface IncidentLike { symbol: string; changePct?: number | null; causeBuckets?: { cause: string; probability: number }[];
  actionOverride?: string; reasonJa?: string; nextConditionJa?: string; severity?: string; isHeld?: boolean; ownerState?: string;
  currentAction?: string; }
interface EventLike { symbol: string; market?: string; eventType: string; severity: number; detectedAt?: string | null;
  reasonJa?: string | null; recommendedPosture?: string; nameJa?: string | null; }
interface AssetLike { id: string; symbol: string; displayName: string; displayNameJa?: string; market: string; quantity?: number; }

const CAUSE_JA: Record<string, string> = {
  MARKET_WIDE_SELL_OFF: '市場全体の下げ', SECTOR_SELL_OFF: 'セクターの下げ', THEME_PROFIT_TAKING: 'テーマ利確',
  STOCK_SPECIFIC_BAD_NEWS: '個別の悪材料', FLOW_DISTRIBUTION: '大口の売り', SHORT_COVER_EXHAUSTION: '踏み上げ一巡',
  POST_RALLY_PROFIT_TAKING: '急騰後の利確', TECHNICAL_BREAKDOWN: 'テクニカル崩れ', CAUSE_UNKNOWN_DOWNSIDE: '原因未確認',
  DATA_QUALITY_LIMITED: 'データ不足', LONG_LIQUIDATION: 'ロング解消',
};
const EV_TONE: Record<string, TimelineItem['tone']> = {
  LIMIT_UP: 'up', LIMIT_UP_PROXIMITY: 'up', PRICE_SPIKE: 'up', MOMENTUM_ACCELERATION: 'up',
  LIMIT_DOWN: 'down', LIMIT_DOWN_PROXIMITY: 'down', PRICE_CRASH: 'down',
  VOLUME_ANOMALY: 'flow', FLOW_ANOMALY: 'flow', FLOW_REVERSAL: 'flow', VOLUME_ACCELERATION: 'flow',
  MARKET_MOVER: 'flat', CRYPTO_SHOCK: 'down',
};

function hhmm(iso?: string | null): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
  } catch { return ''; }
}

export interface BuildCtx {
  label?: LabelLike;
  incident?: IncidentLike | null;
  events?: EventLike[];
  linked?: LinkedEventTag[];
  aiFreshness?: AiFreshness;
  /** Direct quote for assets that have no Action Label (crypto): supplies the
      day-change % so the top-screen card shows a value, not "—". */
  quote?: { price?: number | null; changePct?: number | null };
}

export function buildAssetCard(asset: AssetLike, ctx: BuildCtx): AssetCardModel {
  const { label, incident, events = [], linked = [], aiFreshness = 'rule_only' } = ctx;
  const held = (asset.quantity ?? 0) > 0 || incident?.ownerState === 'held' || incident?.ownerState === 'protected';
  const changePct = ctx.quote?.changePct ?? label?.supportingData?.changePct ?? incident?.changePct ?? null;
  const price = ctx.quote?.price ?? label?.supportingData?.price ?? null;
  const flowRatio = label?.supportingData?.bigFlowRatio ?? null;

  // Resolve the Action Level signal (override from a downside incident can only
  // make it more defensive — same engine as the watchlist rows).
  const sig = resolveSignal(label?.action ?? incident?.currentAction ?? 'HOLD', {
    downsideOverride: incident?.actionOverride,
    dataQuality: label?.status === 'live' ? 'LIVE' : label?.status === 'mock' ? 'MOCK' : 'PARTIAL',
    materialDownside: !!incident,
    ownerState: (incident?.ownerState as OwnerState) || undefined,
  });
  const def = SIGNALS[sig.code];

  // Cause (downside buckets → slices + one-liner).
  const buckets = (incident?.causeBuckets ?? []).slice(0, 3)
    .map((b) => ({ labelJa: CAUSE_JA[b.cause] ?? b.cause, pct: Math.round((b.probability ?? 0) * 100) }));
  const causeOneLineJa = buckets.length ? `${buckets[0].labelJa}${buckets.length > 1 ? ' · ' + buckets[1].labelJa : ''}` : null;

  // Timeline: this symbol's 24/7 events + the incident, newest-last for reading.
  const tl: TimelineItem[] = events
    .slice()
    .sort((a, b) => new Date(a.detectedAt || 0).getTime() - new Date(b.detectedAt || 0).getTime())
    .map((e) => ({ time: hhmm(e.detectedAt), textJa: e.reasonJa || e.eventType, tone: EV_TONE[e.eventType] ?? 'flat' }));

  // ARGUS VIEW — one resolved line. When the call is AI-driven, lead with the AI's
  // own reasoning (the loop output); otherwise the rule label + permissions.
  const judgmentSource: 'ai' | 'rule' = label?.judgmentSource ?? 'rule';
  const permJa = `${sig.permissions.newEntry === 'BLOCKED' ? '新規禁止' : '新規可'} · ${sig.permissions.add === 'BLOCKED' ? '追加禁止' : '追加可'} · 既存は${existingJa(sig.code)}`;
  const aiReason = (judgmentSource === 'ai' && label?.reasonJa) ? label.reasonJa.slice(0, 120) : null;
  const argusViewJa = incident?.reasonJa
    ? `${causeOneLineJa ?? '原因確認中'}。${permJa}。`
    : aiReason
    ? `${aiReason}（${permJa}）`
    : `${def.labelJa}。${permJa}。`;

  // Auto-expand triggers (spec §伸縮): held + critical / EXIT-DEFEND override / unknown cause.
  const sevRank = severityRank(sig.code, incident?.severity, held);
  const autoExpand = (held && (sig.code === 'EXIT' || sig.code === 'DEFEND'))
    || incident?.actionOverride === 'EXIT_WATCH';

  const last = hhmm(label?.supportingData?.quoteDate ? undefined : (events[0]?.detectedAt)) || (tl.length ? tl[tl.length - 1].time : '');

  return {
    id: asset.id,
    symbol: asset.symbol,
    name: asset.displayNameJa || asset.displayName,
    market: asset.market,
    held,
    ownerState: incident?.ownerState as OwnerState | undefined,
    changePct,
    price,
    flowRatio,
    signalCode: sig.code,
    signalLevel: def.level,
    permNewEntry: sig.permissions.newEntry,
    permAdd: sig.permissions.add,
    permExistingJa: existingJa(sig.code),
    argusViewJa,
    overallJa: incident?.reasonJa ?? label?.reasonJa ?? null,
    hasIncident: !!incident,
    causeOneLineJa,
    causeSlices: buckets,
    timeline: tl,
    news: [],                  // per-stock news wiring is phase 2 (see report)
    nextJa: incident?.nextConditionJa || label?.nextConditionJa || '',
    lastUpdate: last || null,
    linkedEvents: linked,
    aiFreshness,
    judgmentSource,
    autoExpand,
    severityRank: sevRank,
  };
}

const EXISTING_JA: Record<SignalCode, string> = {
  EXIT: '撤退判断', DEFEND: '資金防衛', REVIEW: '再点検', PAUSE: '監視', HOLD_ONLY: '維持', PREPARE: '維持', ENTER: '維持',
};
function existingJa(code: SignalCode): string { return EXISTING_JA[code] ?? '維持'; }

// Lower signal level = more defensive = higher concern. Held + incident bumps it.
function severityRank(code: SignalCode, sev?: string, held?: boolean): number {
  let r = (8 - SIGNALS[code].level) * 10;            // EXIT(7) high … ENTER(0) low
  if (sev === 'critical') r += 8; else if (sev === 'high') r += 5; else if (sev === 'medium') r += 2;
  if (held) r += 6;
  return r;
}

export interface GroupInputs {
  assets: AssetLike[];
  labels: LabelLike[];
  incidents: IncidentLike[];
  events: EventLike[];
  linked: Record<string, LinkedEventTag[]>;   // symbol(upper) -> tags
  aiFreshness: AiFreshness;
  cryptoQuotes?: Record<string, { price?: number | null; changePct?: number | null }>;   // symbol(upper) -> quote
}
export interface AssetCardGroups {
  jpWatch: AssetCardModel[]; jpEmerging: AssetCardModel[];
  usWatch: AssetCardModel[]; usEmerging: AssetCardModel[];
  crypto: AssetCardModel[];
}

function up(s: unknown): string { return String(s ?? '').toUpperCase(); }

export function groupAssetCards(inp: GroupInputs): AssetCardGroups {
  const labelBy = new Map(inp.labels.map((l) => [up(l.symbol), l]));
  const incBy = new Map(inp.incidents.map((i) => [up(i.symbol), i]));
  const evBy = new Map<string, EventLike[]>();
  for (const e of inp.events) { const k = up(e.symbol); (evBy.get(k) ?? evBy.set(k, []).get(k)!).push(e); }

  const watched = new Set(inp.assets.map((a) => up(a.symbol)));
  const mk = (a: AssetLike) => buildAssetCard(a, {
    label: labelBy.get(up(a.symbol)), incident: incBy.get(up(a.symbol)) ?? null,
    events: evBy.get(up(a.symbol)) ?? [], linked: inp.linked[up(a.symbol)] ?? [], aiFreshness: inp.aiFreshness,
    quote: inp.cryptoQuotes?.[up(a.symbol)],
  });

  const jpWatch = sortWatchlistCards(inp.assets.filter((a) => a.market === 'JP').map(mk));
  const usWatch = sortWatchlistCards(inp.assets.filter((a) => a.market === 'US').map(mk));
  const crypto = sortWatchlistCards(inp.assets.filter((a) => a.market === 'CRYPTO').map(mk));

  // EMERGING = symbols with live activity (24/7 events) that the owner does NOT track.
  const emerge = (market: 'JP' | 'US') => sortEmergingCards(
    [...evBy.keys()]
      .filter((sym) => !watched.has(sym) && (evBy.get(sym) ?? []).some((e) => e.market === market))
      .map((sym) => {
        const evs = evBy.get(sym) ?? [];
        const nm = evs.find((e) => e.nameJa)?.nameJa ?? undefined;
        return buildAssetCard({ id: `${market.toLowerCase()}-emg-${sym}`, symbol: sym, displayName: sym, displayNameJa: nm ?? undefined, market },
          { label: labelBy.get(sym), incident: incBy.get(sym) ?? null, events: evs, linked: inp.linked[sym] ?? [], aiFreshness: inp.aiFreshness });
      }));

  return { jpWatch, jpEmerging: emerge('JP'), usWatch, usEmerging: emerge('US'), crypto };
}

// ── EMERGING sort (spec): 1 Critical/High, 2 (liquidity proxy: flow present),
//    3 new events, 4 volume/turnover accel, 5 |move|. Simplified to available data. ──
export function sortEmergingCards(cards: AssetCardModel[]): AssetCardModel[] {
  return cards.slice().sort((a, b) =>
    (b.severityRank - a.severityRank) || (Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0)));
}

// ── JAPAN WATCHLIST sort (spec): 1 held/protected, 2 REVIEW/DEFEND/EXIT,
//    3 cause-unknown, 4 latest update, 5 |change|/flow magnitude. ──
export function sortWatchlistCards(cards: AssetCardModel[]): AssetCardModel[] {
  const defensive = new Set<SignalCode>(['REVIEW', 'DEFEND', 'EXIT']);
  return cards.slice().sort((a, b) => {
    if (a.held !== b.held) return a.held ? -1 : 1;
    const ad = defensive.has(a.signalCode), bd = defensive.has(b.signalCode);
    if (ad !== bd) return ad ? -1 : 1;
    const au = a.causeOneLineJa?.includes('原因未確認') ? 1 : 0, bu = b.causeOneLineJa?.includes('原因未確認') ? 1 : 0;
    if (au !== bu) return bu - au;
    if (b.severityRank !== a.severityRank) return b.severityRank - a.severityRank;
    return Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0);
  });
}

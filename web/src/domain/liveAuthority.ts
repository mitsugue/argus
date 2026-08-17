/**
 * Frontend freshness boundary for advisory snapshots.
 *
 * A successful transport, polling timer, or retained React state never renews
 * server evidence.  Every authority-bearing hook re-evaluates the exact server
 * `asOf`, schedules local expiry, and projects stale/error data to a conservative
 * shape.  This module deliberately contains no exchange clock or calendar.
 */

export type LiveAuthorityKind = 'marketRegime' | 'actionLabels'
  | 'flowAttribution' | 'supplyDemand' | 'aiJudgment'
  | 'visibilityGuard' | 'downsideIncidents' | 'cryptoQuote'
  | 'importantEvents' | 'eventRadar' | 'actionAlerts' | 'dashboardEvents';
export type LiveAuthorityState = 'fresh' | 'expired' | 'invalid';

export const LIVE_AUTHORITY_MAX_AGE_MS: Readonly<Record<LiveAuthorityKind, number>> = Object.freeze({
  marketRegime: 60 * 60_000,
  actionLabels: 2 * 60_000,
  flowAttribution: 15 * 60_000,
  supplyDemand: 15 * 60_000,
  // The server runs this layer once per weekday.  A fixed 72h bound preserves
  // weekend display without inventing a browser-side exchange calendar.
  aiJudgment: 72 * 60 * 60_000,
  visibilityGuard: 2 * 60_000,
  downsideIncidents: 3 * 60_000,
  cryptoQuote: 90_000,
  importantEvents: 5 * 60_000,
  eventRadar: 5 * 60_000,
  actionAlerts: 2 * 60_000,
  dashboardEvents: 5 * 60_000,
});

const EXACT_ISO = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/;

export function exactAuthorityEpoch(asOf: unknown): number | null {
  if (typeof asOf !== 'string') return null;
  const match = EXACT_ISO.exec(asOf);
  if (!match) return null;
  const [, year, month, day, hour, minute, second, fraction = '', zone] = match;
  const millis = (fraction + '000').slice(0, 3);
  const localEpoch = Date.UTC(Number(year), Number(month) - 1, Number(day),
    Number(hour), Number(minute), Number(second), Number(millis));
  const exactLocal = new Date(localEpoch);
  if (exactLocal.getUTCFullYear() !== Number(year)
      || exactLocal.getUTCMonth() !== Number(month) - 1
      || exactLocal.getUTCDate() !== Number(day)
      || exactLocal.getUTCHours() !== Number(hour)
      || exactLocal.getUTCMinutes() !== Number(minute)
      || exactLocal.getUTCSeconds() !== Number(second)
      || exactLocal.getUTCMilliseconds() !== Number(millis)) return null;
  let offsetMs = 0;
  if (zone !== 'Z') {
    const sign = zone.startsWith('-') ? -1 : 1;
    const offsetHour = Number(zone.slice(1, 3));
    const offsetMinute = Number(zone.slice(4, 6));
    if (offsetHour > 23 || offsetMinute > 59) return null;
    offsetMs = sign * ((offsetHour * 60 + offsetMinute) * 60_000);
  }
  // Date.parse normalizes impossible dates on some engines.  Exact component
  // equality rejects that normalization while allowing canonical UTC offsets.
  return localEpoch - offsetMs;
}

export function liveAuthorityState(
  asOf: unknown,
  kind: LiveAuthorityKind,
  nowMs = Date.now(),
): LiveAuthorityState {
  if (!Number.isFinite(nowMs)) return 'invalid';
  const observedAtMs = exactAuthorityEpoch(asOf);
  if (observedAtMs == null || observedAtMs > nowMs) return 'invalid';
  return nowMs - observedAtMs <= LIVE_AUTHORITY_MAX_AGE_MS[kind]
    ? 'fresh' : 'expired';
}

export function liveAuthorityExpiresAt(
  asOf: unknown,
  kind: LiveAuthorityKind,
): number | null {
  const observedAtMs = exactAuthorityEpoch(asOf);
  return observedAtMs == null ? null : observedAtMs + LIVE_AUTHORITY_MAX_AGE_MS[kind];
}

export interface AuthorityTimers {
  now: () => number;
  setTimeout: (callback: () => void, delayMs: number) => unknown;
  clearTimeout: (handle: unknown) => void;
}

const SYSTEM_TIMERS: AuthorityTimers = {
  now: () => Date.now(),
  setTimeout: (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** Schedule evidence expiry from server time, never from receipt time. */
export function scheduleLiveAuthorityExpiry(
  asOf: unknown,
  kind: LiveAuthorityKind,
  onExpire: () => void,
  timers: AuthorityTimers = SYSTEM_TIMERS,
): () => void {
  const deadline = liveAuthorityExpiresAt(asOf, kind);
  const now = timers.now();
  if (deadline == null || !Number.isFinite(now) || deadline <= now) {
    onExpire();
    return () => {};
  }
  const handle = timers.setTimeout(onExpire, Math.min(deadline - now + 1, 2_147_000_000));
  return () => timers.clearTimeout(handle);
}

export type DeauthorityReason = 'snapshot_expired' | 'invalid_as_of' | 'refresh_failed';

const reasonJa = (reason: DeauthorityReason) => reason === 'refresh_failed'
  ? '更新失敗のため前回値は判断権限なし'
  : reason === 'invalid_as_of'
    ? '基準時刻が不正なため判断権限なし'
    : '前回値が期限切れのため判断権限なし';

const POSITIVE_ACTIONS = new Set([
  'BUY', 'BUY DIP', 'ADD', 'ENTER', 'PREPARE', 'GRADUAL ADD',
]);

export function deauthorizeActionSnapshot<
  L extends { action: string; confidence: number; status: string; reasonJa: string;
    supportingData?: { bigFlowRatio?: number | null; price?: number | null;
      changePct?: number; volume?: number; quoteDate?: string | null } },
  T extends { status: string; marketPosture: { label: string; rationaleJa: string }; labels: L[] },
>(snapshot: T, reason: DeauthorityReason): T {
  const note = reasonJa(reason);
  const labels = snapshot.labels.map((label) => {
    const positive = POSITIVE_ACTIONS.has(String(label.action).trim().toUpperCase());
    const rawSignal = (label as L & { signal?: {
      code?: string; level?: number; permissions?: Record<string, unknown> } }).signal;
    const signal = rawSignal ? {
      ...rawSignal,
      ...(positive ? { code: 'PAUSE', level: 4 } : {}),
      permissions: {
        ...(rawSignal.permissions ?? {}), newEntry: 'BLOCKED', add: 'BLOCKED',
      },
    } : undefined;
    return {
      ...label,
      action: positive ? 'WAIT' : label.action,
      confidence: positive ? Math.min(label.confidence, 0.25) : label.confidence,
      status: 'mock',
      reasonJa: `${note}。${label.reasonJa}`,
      supportingData: label.supportingData
        ? { ...label.supportingData, bigFlowRatio: null, price: null,
          changePct: undefined, volume: undefined, quoteDate: null }
        : label.supportingData,
      ...(signal ? { signal } : {}),
      decisionUsable: false,
      authorityStatus: reason,
    } as L;
  });
  return {
    ...snapshot,
    status: 'partial',
    marketPosture: {
      ...snapshot.marketPosture,
      label: snapshot.marketPosture.label === 'RISK_ON' ? 'MIXED' : snapshot.marketPosture.label,
      rationaleJa: `${note}。${snapshot.marketPosture.rationaleJa}`,
    },
    labels,
  } as T;
}

export function deauthorizeMarketRegime<T extends {
  status: string;
  regime: { label: string; confidence: number; summaryJa: string };
  ratesBackdrop: { posture: string; rationaleJa: string };
  rotationGroups: Array<{ status: string; available: boolean; rationaleJa: string }>;
  topRotations: unknown[];
  supportingEvidence: string[];
}>(snapshot: T, reason: DeauthorityReason): T {
  const note = reasonJa(reason);
  const defensive = snapshot.regime.label === 'RISK_OFF'
    || snapshot.regime.label === 'EVENT_WAIT' || snapshot.regime.label === 'CAUTIOUS';
  return {
    ...snapshot,
    status: 'partial',
    regime: {
      ...snapshot.regime,
      label: defensive ? snapshot.regime.label : 'MIXED',
      confidence: Math.min(snapshot.regime.confidence, 0.25),
      summaryJa: `${note}。${snapshot.regime.summaryJa}`,
    },
    ratesBackdrop: {
      ...snapshot.ratesBackdrop,
      posture: snapshot.ratesBackdrop.posture === 'supportive'
        ? 'neutral' : snapshot.ratesBackdrop.posture,
      rationaleJa: `${note}。${snapshot.ratesBackdrop.rationaleJa}`,
    },
    rotationGroups: snapshot.rotationGroups.map((group) => ({
      ...group,
      status: group.status === 'outflow' ? 'outflow' : 'neutral',
      available: false,
      rationaleJa: `${note}。${group.rationaleJa}`,
    })),
    topRotations: [],
    supportingEvidence: [note, ...snapshot.supportingEvidence].slice(0, 12),
    decisionUsable: false,
    authorityStatus: reason,
  } as T;
}

const DEFENSIVE_FLOW = new Set([
  'profit_taking', 'distribution', 'panic_selling',
  'rotation_out', 'event_driven_selling',
]);

export function deauthorizeFlowRecords<T extends {
  flowClass: string; flowClassJa: string; direction: string; confidence: number;
  actionImplication: string; actionImplicationJa: string; ownerReadableWhyJa: string;
}>(records: T[], reason: DeauthorityReason): T[] {
  const note = reasonJa(reason);
  return records.map((record) => {
    if (DEFENSIVE_FLOW.has(record.flowClass)) {
      return { ...record, confidence: Math.min(record.confidence, 0.3),
        ownerReadableWhyJa: `${note}。防御的な再確認用: ${record.ownerReadableWhyJa}`,
        decisionUsable: false, authorityStatus: reason } as T;
    }
    return {
      ...record,
      flowClass: 'unknown', flowClassJa: '証拠期限切れ(判定保留)',
      direction: 'unknown', confidence: Math.min(record.confidence, 0.15),
      actionImplication: 'no_action', actionImplicationJa: '対応保留',
      ownerReadableWhyJa: note,
      decisionUsable: false, authorityStatus: reason,
    } as T;
  });
}

export function deauthorizeSupplySignals<T extends {
  supplyDemandRank: string; rankJa: string; supplyDemandLevel?: string;
  condition: string; conditionJa: string; direction: string; confidence: number;
  ownerReadableWhyJa: string; actionImplication: string; actionImplicationJa: string;
  directness: string; directnessJa: string;
}>(signals: T[], reason: DeauthorityReason): T[] {
  const note = reasonJa(reason);
  return signals.map((signal) => {
    const defensive = signal.supplyDemandRank === 'D' || signal.supplyDemandRank === 'E'
      || signal.supplyDemandLevel === 'heavy' || signal.supplyDemandLevel === 'very_heavy'
      || signal.direction === 'worsening' || signal.condition === 'credit_overhang'
      || signal.condition === 'distribution_risk';
    if (defensive) {
      return { ...signal, confidence: Math.min(signal.confidence, 0.3),
        ownerReadableWhyJa: `${note}。防御的な再確認用: ${signal.ownerReadableWhyJa}`,
        directness: 'stale_context', directnessJa: '期限切れ・再確認専用',
        decisionUsable: false, authorityStatus: reason } as T;
    }
    return {
      ...signal,
      supplyDemandRank: 'Unknown', rankJa: '不明', supplyDemandLevel: 'unknown',
      condition: 'unknown', conditionJa: '証拠期限切れ(判定保留)', direction: 'unknown',
      confidence: Math.min(signal.confidence, 0.15),
      ownerReadableWhyJa: note, actionImplication: 'no_action', actionImplicationJa: '対応保留',
      directness: 'stale_context', directnessJa: '期限切れ・再確認専用',
      decisionUsable: false, authorityStatus: reason,
    } as T;
  });
}

export function deauthorizeAIJudgment<T extends {
  status: string; summaryJa: string; freshness?: string; ageMin?: number | null;
}>(snapshot: T, reason: DeauthorityReason): T {
  const note = reasonJa(reason);
  return {
    ...snapshot,
    status: snapshot.status === 'disabled' || snapshot.status === 'no_cached_result'
      ? snapshot.status : 'partial',
    freshness: 'stale',
    summaryJa: `${note}。${snapshot.summaryJa}`,
    decisionUsable: false,
    authorityStatus: reason,
  } as T;
}

export function deauthorizeVisibilityGuard<T extends {
  visibilityLevel: string; blockedActions: string[]; warnings: Array<{ code: string; messageJa: string }>;
  limitations: string[]; coverageLineJa: string; confidenceCap: number | null;
  reasonCodes: string[];
}>(guard: T, reason: DeauthorityReason): T {
  const note = reasonJa(reason);
  return {
    ...guard,
    visibilityLevel: 'minimal',
    blockedActions: ['ENTER', 'ADD'],
    warnings: [{ code: 'VISIBILITY_AUTHORITY_UNAVAILABLE', messageJa: note },
      ...guard.warnings].slice(0, 12),
    limitations: [note, ...guard.limitations].slice(0, 12),
    coverageLineJa: `検知範囲を確認できません。${note}。`,
    confidenceCap: guard.confidenceCap == null ? 0.25 : Math.min(guard.confidenceCap, 0.25),
    reasonCodes: ['VISIBILITY_AUTHORITY_UNAVAILABLE', ...guard.reasonCodes].slice(0, 12),
    decisionUsable: false,
    authorityStatus: reason,
  } as T;
}

export function deauthorizeDownsideSnapshot<T extends {
  status: string; globalRegime: string; jpIntradayOverlay: string; holderRiskOverlay: string;
  overlay: { globalRegime: string; jpIntradayOverlay: string; holderRiskOverlay: string;
    displayJa: string; reasonJa: string; flags: string[] };
  incidents: Array<{ severity: string; isHeld: boolean; status: string; reasonJa: string }>;
  dataLimitations: string[]; noteJa: string;
}>(snapshot: T, reason: DeauthorityReason): T {
  const note = reasonJa(reason);
  const defensiveReview = snapshot.incidents.some((incident) => incident.isHeld
    || incident.severity === 'high' || incident.severity === 'critical');
  return {
    ...snapshot,
    status: 'partial',
    globalRegime: 'UNKNOWN',
    // Unknown downside state cannot prove NORMAL/NONE.  Keep the entire
    // command boundary conservative even when the expired snapshot was empty.
    jpIntradayOverlay: 'CAUTION',
    holderRiskOverlay: 'REVIEW_REQUIRED',
    overlay: {
      ...snapshot.overlay,
      globalRegime: 'UNKNOWN',
      jpIntradayOverlay: 'CAUTION',
      holderRiskOverlay: 'REVIEW_REQUIRED',
      displayJa: defensiveReview ? '保有リスクは再確認' : '下落リスク情報を再確認',
      reasonJa: note,
      flags: defensiveReview
        ? ['STALE_DEFENSIVE_REVIEW_ONLY'] : ['DOWNSIDE_AUTHORITY_UNAVAILABLE'],
    },
    incidents: snapshot.incidents.map((incident) => ({
      ...incident, status: 'partial', reasonJa: `${note}。防御的な再確認用: ${incident.reasonJa}`,
      decisionUsable: false, authorityStatus: reason,
    })),
    dataLimitations: [note, ...snapshot.dataLimitations].slice(0, 12),
    noteJa: `${note}。${snapshot.noteJa}`,
    decisionUsable: false,
    authorityStatus: reason,
  } as T;
}

export function deauthorizeImportantEvents<T extends {
  status: string; events: object[];
}>(snapshot: T, reason: DeauthorityReason): T {
  return {
    ...snapshot,
    status: 'partial',
    events: snapshot.events.map((event) => ({ ...event,
      decisionUsable: false, authorityStatus: reason })) as T['events'],
    decisionUsable: false,
    authorityStatus: reason,
  } as T;
}

export function deauthorizeEventRadar<T extends {
  status: string;
  sources: Array<{ status: string }>;
  events: Array<{ status: string }>;
}>(snapshot: T, reason: DeauthorityReason): T {
  return {
    ...snapshot,
    status: 'partial',
    sources: snapshot.sources.map((source) => ({ ...source, status: 'error' })),
    events: snapshot.events.map((event) => ({ ...event, status: 'mock',
      decisionUsable: false, authorityStatus: reason })),
    decisionUsable: false,
    authorityStatus: reason,
  } as T;
}

const POSITIVE_ALERT_ACTIONS = new Set(['BUY_DIP', 'ADD', 'ENTER', 'BUY']);

export function deauthorizeActionAlerts<T extends {
  action: string; confidence: string; risk: string; reason: string;
}>(cards: T[], reason: DeauthorityReason): Array<T & {
  authorityRole: 'EVIDENCE_ONLY'; finalDecisionAuthorityActive: false;
}> {
  const note = reasonJa(reason);
  return cards.map((card) => {
    const positive = POSITIVE_ALERT_ACTIONS.has(card.action);
    return {
      ...card,
      action: positive ? 'WAIT' : card.action,
      confidence: positive ? 'low' : card.confidence,
      risk: positive ? 'high' : card.risk,
      reason: `${note}。${card.reason}`,
      decisionUsable: false,
      authorityStatus: reason,
      authorityRole: 'EVIDENCE_ONLY',
      finalDecisionAuthorityActive: false,
    } as T & { authorityRole: 'EVIDENCE_ONLY'; finalDecisionAuthorityActive: false };
  });
}

export function cryptoQuoteDecisionUsable(quote: {
  source?: string; status?: string; realtimeEvidence?: boolean;
  sourceTimeStatus?: string; sourceTimestamp?: unknown;
}, nowMs = Date.now()): boolean {
  return quote.source === 'coingecko'
    && quote.status === 'live'
    && quote.realtimeEvidence === true
    && quote.sourceTimeStatus === 'PRESENT'
    && liveAuthorityState(quote.sourceTimestamp, 'cryptoQuote', nowMs) === 'fresh';
}

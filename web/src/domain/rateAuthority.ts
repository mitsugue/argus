import { exactAuthorityEpoch } from './liveAuthority';

/** Canonical Market Truth rate rows use a 20 minute exact-source window and a
 * seven day bounded daily fallback.  Receipt/transport success never extends
 * either source deadline. */
const FRESH_RATE_MAX_AGE_MS = 20 * 60_000;
const DELAYED_RATE_MAX_AGE_MS = 7 * 24 * 60 * 60_000;

const EXACT_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export interface CanonicalRatePoint {
  latestValue?: number | null;
  previousValue?: number | null;
  change?: number | null;
  changeBp?: number | null;
  latestDate?: unknown;
  sourceTimestamp?: unknown;
  observedAt?: unknown;
  receivedAt?: unknown;
  knownAt?: unknown;
  source?: unknown;
  selectedProvider?: unknown;
  status?: unknown;
  freshness?: unknown;
  completeness?: unknown;
}

export function exactRateDate(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const match = EXACT_DATE.exec(value);
  if (!match) return null;
  const [, year, month, day] = match;
  const epoch = Date.UTC(Number(year), Number(month) - 1, Number(day));
  const parsed = new Date(epoch);
  return parsed.getUTCFullYear() === Number(year)
    && parsed.getUTCMonth() === Number(month) - 1
    && parsed.getUTCDate() === Number(day) ? value : null;
}

function canonicalRateTimes(point: CanonicalRatePoint) {
  const observedAt = exactAuthorityEpoch(point.observedAt);
  const receivedAt = exactAuthorityEpoch(point.receivedAt);
  const knownAt = exactAuthorityEpoch(point.knownAt);
  const latestDate = exactRateDate(point.latestDate);
  if (observedAt == null || receivedAt == null || knownAt == null || latestDate == null) {
    return null;
  }
  if (observedAt > receivedAt || receivedAt > knownAt) return null;
  // The backend derives latestDate from the canonical observedAt.  Requiring
  // the same UTC date rejects a separately forged old/future/display date.
  if (new Date(observedAt).toISOString().slice(0, 10) !== latestDate) return null;
  return { observedAt, receivedAt, knownAt };
}

export function ratePointDecisionExpiresAt(point: CanonicalRatePoint): number | null {
  if (typeof point.latestValue !== 'number' || !Number.isFinite(point.latestValue)) return null;
  if (typeof point.source !== 'string' || !point.source
      || typeof point.selectedProvider !== 'string' || !point.selectedProvider) return null;
  if (point.completeness !== 'COMPLETE') return null;
  const times = canonicalRateTimes(point);
  if (!times) return null;
  if (point.status === 'live' && point.freshness === 'FRESH') {
    return times.observedAt + FRESH_RATE_MAX_AGE_MS;
  }
  if (point.status === 'delayed' && point.freshness === 'DELAYED') {
    return times.observedAt + DELAYED_RATE_MAX_AGE_MS;
  }
  return null;
}

export function ratePointDecisionUsable(
  point: CanonicalRatePoint | null | undefined,
  nowMs = Date.now(),
): boolean {
  if (!point || !Number.isFinite(nowMs)) return false;
  const deadline = ratePointDecisionExpiresAt(point);
  const knownAt = exactAuthorityEpoch(point.knownAt);
  return deadline != null && knownAt != null && knownAt <= nowMs && nowMs <= deadline;
}

export function deauthorizeRatePoint<T extends CanonicalRatePoint>(point: T): T {
  return {
    ...point,
    latestValue: null,
    previousValue: null,
    change: null,
    changeBp: null,
    status: 'unavailable',
    decisionUsable: false,
  } as T;
}

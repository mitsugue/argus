import type { ChartIntelligencePayload } from '../types/chartIntelligence';
import type { VerifiedSnapshot } from './verifiedSnapshot';

export type SnapshotFreshness =
  | 'fresh'
  | 'revalidating'
  | 'stale_usable'
  | 'expired'
  | 'unavailable';

const OPEN_MAX_AGE_MS = 75 * 60_000; // 30m natural tick + bounded delay
const CLOSED_MAX_AGE_MS = 5 * 24 * 60 * 60_000; // weekend/holiday continuity

function marketIsClosed(payload: ChartIntelligencePayload) {
  const calendar = payload.marketCalendar;
  if (!calendar) return false;
  if (calendar.isTradingDay === false) return true;
  return /CLOSED|HOLIDAY|WEEKEND|AFTER|PRE|LUNCH/i.test(calendar.session ?? '');
}

export function snapshotFreshness(
  snapshot: VerifiedSnapshot<ChartIntelligencePayload> | null,
  now = Date.now(), revalidating = false,
): SnapshotFreshness {
  if (!snapshot) return 'unavailable';
  const asOf = Date.parse(snapshot.asOf);
  if (!Number.isFinite(asOf) || snapshot.quality === 'stale') return 'expired';
  const age = Math.max(0, now - asOf);
  const maxAge = marketIsClosed(snapshot.payload) ? CLOSED_MAX_AGE_MS : OPEN_MAX_AGE_MS;
  if (age <= maxAge) {
    return revalidating ? 'revalidating' : 'fresh';
  }
  if (age <= CLOSED_MAX_AGE_MS) return 'stale_usable';
  return 'expired';
}

export function formatSnapshotStatus(
  state: import('./verifiedSnapshot').SnapshotViewState,
  snapshot: VerifiedSnapshot<ChartIntelligencePayload> | null,
) {
  if (!snapshot) return state === 'ERROR_WITHOUT_CACHE'
    ? 'データを取得できません' : '初回データを準備中';
  const time = new Intl.DateTimeFormat('ja-JP', {
    timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit',
    hour12: false,
  }).format(new Date(snapshot.asOf));
  if (state === 'CACHE_READY_REVALIDATING') return `前回 ${time} JST · 更新中`;
  if (state === 'ERROR_WITH_CACHE') return `前回 ${time} JST · 更新要確認`;
  if (state === 'STALE_FALLBACK') return '前回データ · 要更新';
  return `更新済 ${time} JST`;
}

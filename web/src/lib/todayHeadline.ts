import type { ChartBar, PriceZone } from '../types/chartIntelligence';
import type { TodayProjectionInput } from '../domain/argusTodayView';

// Compact Today bootstrap served by /api/argus/today-headline. Every value is
// derived server-side from the canonical verified snapshots; this module only
// validates shape/semantics and maps entries into existing domain inputs. It
// never computes market facts and never becomes a second decision authority.
export const TODAY_HEADLINE_SCHEMA = 'argus-today-headline-v1';
export const HEADLINE_INSTRUMENTS = ['1321', '1306', 'SPY', 'QQQ'] as const;
export type HeadlineInstrument = typeof HEADLINE_INSTRUMENTS[number];

export interface TodayHeadlineEntry {
  status: 'ready' | 'unavailable';
  instrument: string;
  reason?: string;
  market?: 'JP' | 'US';
  parentSnapshotId?: string;
  parentPayloadHash?: string;
  verificationStatus?: string;
  methodVersion?: string;
  quality?: string;
  asOf?: string;
  generatedAt?: string;
  displayNameJa?: string;
  instrumentMetadata?: Record<string, unknown> & {
    instrumentId?: string; source?: string; availableFrom?: string;
    assetType?: string; proxyFor?: string; licenseStatus?: string;
  };
  periodEnd?: string;
  payloadStatus?: string;
  quoteState?: TodayProjectionInput['quoteState'];
  marketCalendar?: Record<string, unknown>;
  bars?: ChartBar[];
  zones?: PriceZone[];
  turningPoints?: TodayProjectionInput['turningPoints'];
  eventMarkers?: TodayProjectionInput['eventMarkers'];
  calibration?: TodayProjectionInput['calibration'];
  shortSelling?: TodayProjectionInput['shortSelling'];
  failedRally?: TodayProjectionInput['failedRally'];
  historyCoverage?: { start?: string | null; end?: string | null;
    count?: number | null };
  relativeStrengthSummary?: { nikkeiSp500Change20Pct?: number } | null;
  headlineHash?: string;
}

export interface TodayHeadlineDocument {
  schemaVersion: string;
  generatedAt: string;
  automaticAiCalls: number;
  readyCount: number;
  instrumentCount: number;
  headlineSetId: string;
  instruments: Record<string, TodayHeadlineEntry>;
}

export type HeadlineValidation =
  | { ok: true; document: TodayHeadlineDocument }
  | { ok: false; reason: string };

function validEntry(entry: TodayHeadlineEntry): string | null {
  if (entry.status === 'unavailable') {
    return typeof entry.reason === 'string' && entry.reason
      ? null : 'unavailable_without_reason';
  }
  if (entry.status !== 'ready') return 'unknown_status';
  if (!/^vs-[0-9a-f]{32}$/.test(entry.parentSnapshotId ?? '')) {
    return 'parent_snapshot_id_invalid';
  }
  if (entry.verificationStatus !== 'verified') return 'parent_unverified';
  const bars = entry.bars ?? [];
  if (!Array.isArray(bars) || bars.length < 5) return 'bars_insufficient';
  let prior = '';
  for (const bar of bars) {
    if (typeof bar.date !== 'string' || bar.date <= prior) return 'bars_unordered';
    if (![bar.open, bar.high, bar.low, bar.close]
      .every((value) => Number.isFinite(value) && (value as number) > 0)) {
      return 'bars_invalid_price';
    }
    prior = bar.date;
  }
  const generated = Date.parse(entry.generatedAt ?? '');
  if (!Number.isFinite(generated) || generated > Date.now() + 5 * 60_000) {
    return 'timestamp_invalid';
  }
  const horizons = entry.calibration?.horizons ?? {};
  for (const horizon of Object.values(horizons)) {
    for (const candidate of [horizon?.directionProbabilities,
      horizon?.referenceDirectionProbabilities, horizon?.probabilities]) {
      if (candidate == null) continue;
      const values = [candidate.UP, candidate.RANGE, candidate.DOWN];
      if (!values.every((value) => Number.isFinite(value)
          && value >= 0 && value <= 100)) {
        return 'probability_out_of_range';
      }
      const total = values.reduce((sum, value) => sum + value, 0);
      if (total < 95 || total > 105) return 'probability_sum_invalid';
    }
  }
  return null;
}

export function validateTodayHeadline(candidate: unknown): HeadlineValidation {
  if (!candidate || typeof candidate !== 'object') {
    return { ok: false, reason: 'malformed' };
  }
  const document = candidate as TodayHeadlineDocument;
  if (document.schemaVersion !== TODAY_HEADLINE_SCHEMA) {
    return { ok: false, reason: 'schema_incompatible' };
  }
  if (document.automaticAiCalls !== 0) return { ok: false, reason: 'ai_call_forbidden' };
  if (!document.headlineSetId || typeof document.headlineSetId !== 'string') {
    return { ok: false, reason: 'set_id_missing' };
  }
  const instruments = document.instruments ?? {};
  for (const symbol of HEADLINE_INSTRUMENTS) {
    const entry = instruments[symbol];
    if (!entry) return { ok: false, reason: `instrument_missing_${symbol}` };
    const problem = validEntry(entry);
    if (problem) return { ok: false, reason: `${symbol}:${problem}` };
  }
  return { ok: true, document };
}

/** Map a ready headline entry to the exact projection input the Today domain
 *  already consumes — one shared derivation, no duplicated semantics. */
export function headlineProjectionInput(
  entry: TodayHeadlineEntry | undefined,
): TodayProjectionInput | null {
  if (!entry || entry.status !== 'ready') return null;
  const metadata = entry.instrumentMetadata ?? {};
  return {
    symbol: entry.instrument,
    label: entry.displayNameJa ?? entry.instrument,
    asOf: entry.periodEnd ?? null,
    status: entry.payloadStatus ?? 'complete',
    authorityState: 'current',
    timeframe: 'daily',
    quoteState: entry.quoteState ?? 'CLOSE',
    // The compact headline ships only 31 bars for drawing; the calibration
    // behind it consumed the full history. HISTORY must report the latter —
    // historyCoverage.count is the full-corpus bar count from the engine.
    sourceHistoryCount: entry.historyCoverage?.count ?? entry.bars?.length ?? 0,
    instrumentId: metadata.instrumentId as string | undefined,
    source: (metadata.source as string | undefined) ?? 'existing_market_data_cache',
    availableFrom: metadata.availableFrom as string | undefined,
    assetType: metadata.assetType as string | undefined,
    proxyFor: entry.instrument === '1321'
      ? ((metadata.proxyFor as string | undefined) ?? 'Nikkei 225')
      : metadata.proxyFor as string | undefined,
    licenseStatus: entry.instrument === '1321'
      ? ((metadata.licenseStatus as string | undefined) ?? 'license_unverified')
      : ((metadata.licenseStatus as string | undefined) ?? 'not_applicable'),
    bars: entry.bars ?? [],
    zones: entry.zones ?? [],
    eventMarkers: entry.eventMarkers,
    turningPoints: entry.turningPoints,
    calibration: entry.calibration,
    shortSelling: entry.shortSelling ?? null,
    failedRally: entry.failedRally ?? null,
    historyStart: entry.historyCoverage?.start ?? null,
    historyEnd: entry.historyCoverage?.end ?? null,
  };
}

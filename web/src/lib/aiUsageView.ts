export interface UsageTotals {
  records: number; providerCalls: number; unknownProviderCallCount: number;
  knownEstimatedCostUsd: number; unknownCostRecords: number;
  inputTokens: number; outputTokens: number; cachedInputTokens: number;
  unknownTokenRecords: Record<string, number>; outcomes: Record<string, number>;
  errorClasses: Record<string, number>; knownDurationMs: number; unknownDurationRecords: number;
  retryRecords: number; unknownAttemptRecords: number;
}
export interface UsageGroup extends UsageTotals {
  feature: string; provider: string; requestedModel: string | null; returnedModel: string | null;
}
export interface UsageView {
  schemaVersion: 'argus-owner-usage-view-v1'; scope: 'OWNER_PRIVATE';
  generatedAt: string; monthUtc: string; timeBasis: 'UTC'; status: string;
  rows: UsageGroup[]; totals: UsageTotals | null; throughSequence: number | null;
  nextOffset: number | null; groupCount?: number; firstRecordedAt?: string | null; lastRecordedAt?: string | null;
  remoteRecoveryVerified: boolean;
  state: { status: string | null; pendingReceipts: number | null; lastSavedAt: string | null; lastErrorClass: string | null };
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const count = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
const time = (v: unknown) => typeof v === 'string' && Number.isFinite(Date.parse(v));
const text = (v: unknown) => typeof v === 'string' && v.length > 0 && v.length <= 160;
const nullableText = (v: unknown) => v === null || text(v);
function totals(v: unknown): v is UsageTotals {
  if (!object(v) || !['records','providerCalls','unknownProviderCallCount','unknownCostRecords',
    'inputTokens','outputTokens','cachedInputTokens','knownDurationMs','unknownDurationRecords',
    'retryRecords','unknownAttemptRecords'].every(k => count(v[k]))
    || typeof v.knownEstimatedCostUsd !== 'number' || !Number.isFinite(v.knownEstimatedCostUsd) || v.knownEstimatedCostUsd < 0) return false;
  if (!['unknownTokenRecords','outcomes','errorClasses'].every(k => object(v[k])
    && Object.entries(v[k]).length <= 100 && Object.entries(v[k]).every(([name, value]) => text(name) && count(value)))) return false;
  const records = v.records as number;
  return ['providerCalls','unknownProviderCallCount','unknownCostRecords','unknownDurationRecords','retryRecords','unknownAttemptRecords']
    .every(k => Number(v[k]) <= records)
    && Number(v.providerCalls) + Number(v.unknownProviderCallCount) <= records
    && Object.values(v.outcomes as Record<string, number>).reduce((a,b)=>a+b,0) === records
    && (!records || ['inputTokens','outputTokens','cachedInputTokens'].every(k => count((v.unknownTokenRecords as Record<string,unknown>)[k])))
    && Object.values(v.unknownTokenRecords as Record<string, number>).every(n => n <= records);
}
export function validUsageView(v: unknown, month: string): v is UsageView {
  if (!object(v) || v.schemaVersion !== 'argus-owner-usage-view-v1' || v.scope !== 'OWNER_PRIVATE'
    || v.monthUtc !== month || v.timeBasis !== 'UTC' || !time(v.generatedAt)
    || !['AVAILABLE','NOT_RECORDED','NOT_CONFIGURED','UNAVAILABLE'].includes(String(v.status))
    || v.providerResponseIsContentAcceptance !== false || v.addToLegacyTotal !== false
    || v.coverage !== 'committed_sdk_receipts_only' || v.historyBeforeFirstReceiptReconstructed !== false
    || typeof v.remoteRecoveryVerified !== 'boolean' || !object(v.state)
    || !nullableText(v.state.status) || !(v.state.pendingReceipts === null || count(v.state.pendingReceipts))
    || !(v.state.lastSavedAt === null || time(v.state.lastSavedAt)) || !nullableText(v.state.lastErrorClass)
    || !Array.isArray(v.rows) || v.rows.length > 50) return false;
  if (v.status !== 'AVAILABLE') return v.totals === null && v.rows.length === 0 && v.nextOffset === null;
  return totals(v.totals) && count(v.throughSequence) && count(v.groupCount)
    && (v.nextOffset === null || count(v.nextOffset))
    && (v.firstRecordedAt === null || time(v.firstRecordedAt)) && (v.lastRecordedAt === null || time(v.lastRecordedAt))
    && v.rows.every(r => object(r) && totals(r) && text(r.feature) && text(r.provider)
      && nullableText(r.requestedModel) && nullableText(r.returnedModel));
}
export function usageCount(value: number, unknown: number, records: number): string {
  if (records > 0 && unknown === records) return '未取得';
  return value.toLocaleString('ja-JP') + (unknown ? `（${unknown}件は未取得）` : '');
}
export function usageCost(value: UsageTotals): string {
  if (value.records > 0 && value.unknownCostRecords === value.records) return '未取得';
  return '$' + value.knownEstimatedCostUsd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
    + (value.unknownCostRecords ? `＋未取得${value.unknownCostRecords}件` : '');
}

export interface MarketBriefProvenance {
  scope: 'published_metadata_snapshot'; eventId: string | null; revision: number | null;
  publishedAt: string | null; receivedAt: string | null; observedAt: string | null;
  url: string | null; sourceLabel: string | null;
  sourceResponseSha256?: string; sourceRowSha256?: string;
}
export interface MarketBriefFact {
  provenance?: MarketBriefProvenance;
  text: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  source: string;
  verification: 'VERIFIED' | 'CORROBORATED' | 'UNCONFIRMED';
}

export interface MarketBrief {
  calculationSnapshots?: Record<string, { marketInternals?: unknown }>;
  unifiedSummary?: {
    schemaVersion: 'argus-unified-brief-v1'; contextId: string; actionAuthority: false;
    ownerContextAvailable: boolean; historyStatus: 'PROCESS_MEMORY_ONLY' | 'LOCAL_DURABLE';
    sections: Record<'view' | 'reasons' | 'changes' | 'impact' | 'next' | 'invalidation',
      { textJa: string; evidenceIds: string[]; kind: 'FACT' | 'INFERENCE' | 'UNKNOWN' }>;
  } | null;
  unifiedContext?: { contextId: string; facts: Array<MarketBriefFact & { evidenceId: string }>;
    previousFacts: Array<MarketBriefFact & { evidenceId: string }>; previousAt: string | null };
  analysisHistory?: { status: string; recordId?: string; remoteRecoveryVerified: boolean };
  unifiedStatus?: string;
  generationWorker?: { status: string; lastAttemptAt?: string | null; lastCompletedAt?: string | null; errorClass?: string | null };
  lastSuccessfulAiAt?: string | null;
  aiDiagnostics?: { requestedModel: string | null; returnedModel: string | null; completedAt: string | null };
  schemaVersion: string;
  generatedAt: string;
  hasCritical?: boolean;
  now: string;
  why: string;
  next: string;
  aiText: { nowJa: string; whyJa: string; nextJa: string } | null;
  aiModel: string | null;
  chips: { chart: string; news: string; nextEvent: string; mainRisk: string };
  facts: MarketBriefFact[];
  noteJa: string;
  sdaAuthority: false;
  status?: string;
}

const sections = ['view', 'reasons', 'changes', 'impact', 'next', 'invalidation'] as const;
const object = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown, limit = 1000): value is string => typeof value === 'string' && value.length <= limit;
const instant = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value));
const provenance = (value: unknown) => {
  if (!object(value) || value.scope !== 'published_metadata_snapshot'
    || !(value.eventId === null || (typeof value.eventId === 'string' && /^[a-zA-Z0-9_.:-]{1,160}$/.test(value.eventId)))
    || !(value.revision === null || (Number.isSafeInteger(value.revision) && value.revision >= 0))
    || !(value.sourceLabel === null || text(value.sourceLabel, 160))
    || !['publishedAt', 'receivedAt', 'observedAt'].every(key => value[key] === null || instant(value[key]))) return false;
  if (!['sourceResponseSha256','sourceRowSha256'].every(key => value[key] === undefined
    || (typeof value[key] === 'string' && /^[a-f0-9]{64}$/.test(value[key])))) return false;
  if (value.url === null) return true;
  if (!text(value.url, 2048)) return false;
  try { const url = new URL(value.url); return url.protocol === 'https:' && !!url.hostname && !url.username && !url.password; }
  catch { return false; }
};
const fact = (value: unknown): value is MarketBriefFact => object(value)
  && text(value.text, 500) && text(value.source, 100)
  && (value.provenance === undefined || provenance(value.provenance))
  && ['P0', 'P1', 'P2', 'P3'].includes(value.priority)
  && ['VERIFIED', 'CORROBORATED', 'UNCONFIRMED'].includes(value.verification);

// Reject incomplete responses before they can replace the last readable view.
export function validMarketBrief(value: unknown): value is MarketBrief {
  if (!object(value) || value.schemaVersion !== 'argus-market-brief-v1'
    || value.sdaAuthority !== false || value.status === 'unavailable'
    || !instant(value.generatedAt) || !['now', 'why', 'next'].every(key => text(value[key]))
    || !object(value.chips) || !['chart', 'news', 'nextEvent', 'mainRisk'].every(key => text(value.chips[key]))
    || !Array.isArray(value.facts) || value.facts.length > 24 || !value.facts.every(fact)) return false;
  if (value.aiText != null && (!object(value.aiText)
    || !['nowJa', 'whyJa', 'nextJa'].every(key => text(value.aiText[key], 240)))) return false;
  if (value.aiModel != null && !text(value.aiModel, 100)) return false;
  if (value.lastSuccessfulAiAt != null && !instant(value.lastSuccessfulAiAt)) return false;
  if (value.generationWorker != null && (!object(value.generationWorker)
    || !['NOT_RUN', 'RUNNING', 'GENERATED', 'AWAITING_AI', 'INVALID_RESPONSE', 'UNAVAILABLE', 'FAILED'].includes(value.generationWorker.status)
    || !['lastAttemptAt', 'lastCompletedAt'].every(key => value.generationWorker[key] == null || instant(value.generationWorker[key]))
    || (value.generationWorker.errorClass != null && !text(value.generationWorker.errorClass, 100)))) return false;
  if (value.aiDiagnostics != null && (!object(value.aiDiagnostics)
    || !['requestedModel', 'returnedModel'].every(key => value.aiDiagnostics[key] == null || text(value.aiDiagnostics[key], 100))
    || (value.aiDiagnostics.completedAt != null && !instant(value.aiDiagnostics.completedAt)))) return false;
  const summary = value.unifiedSummary;
  if (summary == null) return value.unifiedStatus !== 'GENERATED';
  const context = value.unifiedContext;
  if (value.unifiedStatus !== 'GENERATED' || !object(summary) || !object(context)
    || summary.schemaVersion !== 'argus-unified-brief-v1' || summary.actionAuthority !== false
    || summary.ownerContextAvailable !== false || !['PROCESS_MEMORY_ONLY', 'LOCAL_DURABLE'].includes(summary.historyStatus)
    || typeof context.contextId !== 'string' || !/^[a-f0-9]{64}$/.test(context.contextId)
    || summary.contextId !== context.contextId || !object(summary.sections)
    || Object.keys(summary.sections).length !== sections.length) return false;
  for (const rows of [context.facts, context.previousFacts]) {
    if (!Array.isArray(rows) || rows.length > 24 || !rows.every(row => object(row) && typeof row.evidenceId === 'string'
      && /^brief-fact-[a-f0-9]{64}$/.test(row.evidenceId) && fact(row))
      || new Set(rows.map(row => row.evidenceId)).size !== rows.length) return false;
  }
  return sections.every(key => {
    const row = summary.sections[key];
    if (!object(row) || !text(row.textJa, 240) || !row.textJa.trim()
      || !['FACT', 'INFERENCE', 'UNKNOWN'].includes(row.kind)
      || !Array.isArray(row.evidenceIds) || row.evidenceIds.length > 6
      || new Set(row.evidenceIds).size !== row.evidenceIds.length
      || (row.kind !== 'UNKNOWN' && row.evidenceIds.length === 0)) return false;
    const allowed = key === 'changes' ? [...context.previousFacts, ...context.facts] : context.facts;
    if (!row.evidenceIds.every((id: unknown) => typeof id === 'string'
      && allowed.some((ref: any) => ref.evidenceId === id))) return false;
    if (key === 'impact' && row.kind !== 'UNKNOWN') return false;
    if (key === 'changes' && !context.previousFacts.length && row.kind !== 'UNKNOWN') return false;
    if (row.kind === 'FACT' && (['view', 'impact', 'next', 'invalidation'].includes(key)
      || row.evidenceIds.some((id: string) => allowed.find((ref: any) => ref.evidenceId === id)?.verification !== 'VERIFIED'))) return false;
    return true;
  });
}

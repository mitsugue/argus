import { validMarketBrief, type MarketBrief } from './marketBrief';
import { validJapanMarketComparison } from './japanMarketComparison';

const sections = ['view', 'reasons', 'changes', 'impact', 'next', 'invalidation'];
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
export const editorialEvidenceLabels: Record<string, string> = {
  news: 'いま注目するニュース', events: '次に備える予定', supply: '需給の変化',
  currency: '為替と円のポジション', horizons: '期間ごとの見通し', market: '市場の中で起きていること',
};
export const editorialElementLabel = (id: string): string | null => {
  const match = /^evidence-(news|events|supply|currency|horizons|market)-[0-2]$/.exec(id);
  return match ? editorialEvidenceLabels[match[1]] : null;
};

export function hasEditorialIntent(brief: MarketBrief | null): boolean {
  const plan = brief?.presentationPlan; const catalog = brief?.presentationCatalog;
  if (!brief || brief.unifiedStatus !== 'GENERATED' || !brief.unifiedSummary || !plan || !catalog
    || brief.presentationStatus !== 'GENERATED' || plan.schemaVersion !== 'argus-presentation-intent-v1'
    || plan.actionAuthority !== false || !hash(plan.planId) || !hash(plan.inventoryId)
    || plan.contextId !== brief.unifiedContext?.contextId || catalog.contextId !== plan.contextId
    || catalog.inventoryId !== plan.inventoryId || plan.surface !== 'today' || catalog.surface !== plan.surface
    || plan.subject !== 'N225' || catalog.subject !== plan.subject || plan.horizonSessions !== 5
    || catalog.horizonSessions !== plan.horizonSessions || typeof plan.intentJa !== 'string' || plan.intentJa.length > 160
    || !Array.isArray(plan.elements) || !Array.isArray(catalog.elements) || plan.elements.length > 32
    || plan.elements.length !== catalog.elements.length
    || !catalog.elements.every(row => row && typeof row.id === 'string')
    || !plan.elements.every(row => row && typeof row.id === 'string')) return false;
  const known = new Map(catalog.elements.map(row => [row.id, row]));
  const seen = new Set<string>(); let primary = 0; let nonurgent = false;
  for (const row of plan.elements) {
    const source = known.get(row.id);
    if (!source || seen.has(row.id) || !hash(source.payloadId)
      || typeof row.purposeJa !== 'string' || !row.purposeJa.trim() || row.purposeJa.length > 160
      || !['lead', 'support', 'detail'].includes(row.placement) || !['primary', 'normal', 'quiet'].includes(row.emphasis)
      || (source.mandatory && row.placement === 'detail')
      || (source.urgent && (nonurgent || row.placement !== 'lead' || row.emphasis === 'quiet'))
      || (!sections.includes(row.id) && row.id !== 'nikkei-comparison' && !editorialElementLabel(row.id))) return false;
    if (editorialElementLabel(row.id)) {
      const caption = row.caption;
      const facts = brief.unifiedContext?.facts ?? [];
      if (!caption || typeof caption.textJa !== 'string' || !caption.textJa.trim() || caption.textJa.length > 180
        || (row.emphasis === 'primary' && caption.textJa.length > 80)
        || !['FACT', 'INFERENCE', 'UNKNOWN'].includes(caption.kind)
        || !Array.isArray(source.evidenceIds) || !source.evidenceIds.length || source.evidenceIds.length > 24
        || new Set(source.evidenceIds).size !== source.evidenceIds.length
        || !source.evidenceIds.every(id => facts.some(f => f.evidenceId === id))
        || !Array.isArray(caption.evidenceIds) || !caption.evidenceIds.length || caption.evidenceIds.length > 6
        || new Set(caption.evidenceIds).size !== caption.evidenceIds.length
        || !caption.evidenceIds.every(id => source.evidenceIds.includes(id))
        || (caption.kind === 'FACT' && caption.evidenceIds.some(id => facts.find(f => f.evidenceId === id)?.verification !== 'VERIFIED'))) return false;
    }
    if (!source.urgent && row.id !== 'view') nonurgent = true;
    seen.add(row.id); if (row.emphasis === 'primary') primary++;
    if (row.id === 'nikkei-comparison' && !validJapanMarketComparison(brief.calculationSnapshots?.['5']?.comparison, 5)) return false;
  }
  return primary === 1 && sections.every(key => seen.has(key));
}

export function editorialEdition(brief: MarketBrief | null): MarketBrief | null {
  if (hasEditorialIntent(brief)) return brief;
  const previous = brief?.retainedPresentation;
  return previous && validMarketBrief(previous) && hasEditorialIntent(previous) ? previous : null;
}

export function retainEditorialEdition(current: MarketBrief, previous: MarketBrief | null): MarketBrief {
  if (editorialEdition(current)) return current;
  const retained = editorialEdition(previous);
  return retained ? { ...current, retainedPresentation: retained } : current;
}

// Public history is read-only. Restore the whole edition, never its prose alone.
export async function readRecentEditorialEdition(base: string, signal: AbortSignal): Promise<MarketBrief | null> {
  const read = async (query: string) => {
    const response = await fetch(`${base}/api/argus/market-brief?${query}`,
      { cache: 'no-store', signal, headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error('history_unavailable');
    return response.json();
  };
  const page = await read('history=1');
  if (page.scope !== 'PUBLIC_MARKET' || page.actionAuthority !== false || !Array.isArray(page.rows)
    || page.rows.length > 20 || !page.rows.every((row: { recordId?: unknown }) => row && hash(row.recordId))) return null;
  for (const row of page.rows.slice(0, 3)) {
    const value = await read(`historyId=${encodeURIComponent(row.recordId)}`);
    const record = value.record;
    if (value.scope !== 'PUBLIC_MARKET' || value.readOnly !== true || record?.recordId !== row.recordId
      || !validMarketBrief(record.brief) || !record.calculations || Array.isArray(record.calculations)
      || typeof record.calculations !== 'object') continue;
    const candidate: MarketBrief = { ...record.brief, calculationSnapshots: record.calculations,
      analysisHistory: { status: 'LOCAL_DURABLE', recordId: record.recordId, remoteRecoveryVerified: false } };
    if (hasEditorialIntent(candidate)) return candidate;
  }
  return null;
}

export function editorialCoversNews(brief: MarketBrief | null,
  event: { eventId: string; revision?: number; processedAt?: string }): boolean {
  brief = editorialEdition(brief);
  if (!Number.isFinite(Date.parse(event.processedAt ?? '')) || !Number.isFinite(Date.parse(brief?.generatedAt ?? ''))) return false;
  if (!hasEditorialIntent(brief) || !event.processedAt
    || Date.parse(event.processedAt) > Date.parse(brief!.generatedAt)) return false;
  const cited = new Set(brief!.presentationPlan!.elements
    .filter(row => row.id.startsWith('evidence-news-') && row.placement !== 'detail')
    .flatMap(row => row.caption?.evidenceIds ?? []));
  return brief!.unifiedContext!.facts.some(f => cited.has(f.evidenceId) && f.source === 'trusted_mail'
    && f.priority === 'P0' && f.provenance?.eventId === event.eventId
    && f.provenance?.revision != null && f.provenance.revision === event.revision);
}

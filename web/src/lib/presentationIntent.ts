import { validMarketBrief, type MarketBrief } from './marketBrief';
import { validJapanMarketComparison } from './japanMarketComparison';

const sections = ['view', 'reasons', 'changes', 'impact', 'next', 'invalidation'];
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);

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
      || (!sections.includes(row.id) && row.id !== 'nikkei-comparison')) return false;
    if (!source.urgent) nonurgent = true;
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

/** Presentation order only; never changes analysis or trading authority. */
export const NEWS_IMPORTANCE_JA: Record<string, string> = { CRITICAL: '重大', HIGH: '重要', WATCH: '注視', INFO: '参考' };
const priority: Record<string, number> = { CRITICAL: 2, HIGH: 1 };
interface MaterialItem {
  eventId: string; severity: string; sourceReceivedAt?: string | null;
  revision?: number; processedAt?: string; staleness?: string;
}
const instant = (value?: string | null) => {
  const parsed = Date.parse(value ?? '');
  return Number.isFinite(parsed) ? parsed : 0;
};
export function orderMaterialNews<T extends MaterialItem>(events: readonly T[]): T[] {
  const unique = new Map<string, T>();
  for (const event of events) {
    const prior = unique.get(event.eventId);
    // A revision replaces the same article. Different article IDs, including
    // follow-ups and corrections with identical titles, must remain separate.
    if (!prior || (event.revision ?? 0) > (prior.revision ?? 0)
      || ((event.revision ?? 0) === (prior.revision ?? 0)
        && instant(event.processedAt) > instant(prior.processedAt))) unique.set(event.eventId, event);
  }
  return [...unique.values()]
    .filter(event => priority[event.severity] && event.staleness?.toUpperCase() !== 'STALE')
    .sort((a, b) => priority[b.severity] - priority[a.severity]
      || instant(b.sourceReceivedAt) - instant(a.sourceReceivedAt)
      || a.eventId.localeCompare(b.eventId));
}

/** Group only the backend's identified episode; preserve every source article. */
export function groupNewsEpisodes<T extends MaterialItem & {
  eventMemory?: { episodeId?: string } | null;
}>(events: readonly T[]): Array<{ lead: T; related: T[] }> {
  const groups = new Map<string, T[]>();
  for (const event of events) {
    const key = event.eventMemory?.episodeId || event.eventId;
    const rows = groups.get(key) ?? [];
    const previous = rows.findIndex(row => row.eventId === event.eventId);
    if (previous < 0) rows.push(event);
    else if ((event.revision ?? 0) >= (rows[previous].revision ?? 0)) rows[previous] = event;
    groups.set(key, rows);
  }
  return [...groups.values()].map(rows => {
    rows.sort((a, b) => (priority[b.severity] ?? 0) - (priority[a.severity] ?? 0)
      || instant(b.sourceReceivedAt) - instant(a.sourceReceivedAt)
      || a.eventId.localeCompare(b.eventId));
    return { lead: rows[0], related: rows.slice(1) };
  });
}

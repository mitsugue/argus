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

/** Fold repeated deliveries without claiming that their article bodies match. */
export function groupRepeatedNewsHeadlines<T extends MaterialItem & {
  headlineJa: string; source: string; eventMemory?: { episodeId?: string } | null;
}>(events: readonly T[]): Array<{ lead: T; previous: T[] }> {
  const revisions = new Map<string, T>();
  for (const row of events) {
    const prior = revisions.get(row.eventId);
    if (!prior || (row.revision ?? 0) > (prior.revision ?? 0)
      || ((row.revision ?? 0) === (prior.revision ?? 0)
        && instant(row.processedAt) > instant(prior.processedAt))) revisions.set(row.eventId, row);
  }
  const groups = new Map<string, T[]>();
  for (const row of revisions.values()) {
    const at = instant(row.sourceReceivedAt);
    const day = at ? new Date(at + 9 * 3600_000).toISOString().slice(0, 10) : null;
    const headline = row.headlineJa.normalize('NFKC').replace(/\s+/g, ' ').trim();
    const episode = row.eventMemory?.episodeId;
    // A headline alone is not event identity. Require the identified episode,
    // publisher, and same Japanese receipt day; all older deliveries stay openable.
    const key = episode && row.source && headline && day
      ? JSON.stringify([episode, row.source, headline, day]) : row.eventId;
    const rows = groups.get(key) ?? [];
    rows.push(row); groups.set(key, rows);
  }
  return [...groups.values()].map(rows => {
    rows.sort((a, b) => instant(b.sourceReceivedAt) - instant(a.sourceReceivedAt)
      || instant(b.processedAt) - instant(a.processedAt) || a.eventId.localeCompare(b.eventId));
    return { lead: rows[0], previous: rows.slice(1) };
  });
}
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

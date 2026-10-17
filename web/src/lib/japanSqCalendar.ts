export interface JapanSqEvent {
  eventId: string; title: string; kind: 'MAJOR_SQ' | 'MONTHLY_SQ';
  sqDate: string; lastTradingDate: string; stage: 'TODAY' | 'LAST_TRADING_DAY' | 'EVENT_WEEK' | 'UPCOMING';
  calendarStatus: 'VERIFIED' | 'UNAVAILABLE_OR_CONFLICT'; tradingSessionsUntil: number | null;
  sourceRef: string; sourceSha256: string; knownAt: string; summary: string;
  directionalSignal: null; requiresAiResult: false;
}
export interface JapanSqCalendar {
  schemaVersion: 'jp-market-sq-calendar-v1'; asOf: string; rangeStart: string; rangeEnd: string;
  status: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE'; events: JapanSqEvent[]; gaps: string[];
  dependsOnAi: false; actionAuthority: false; automaticAiCalls: 0;
  lastSuccessfulAcquisitionAt: string | null;
}
const date = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
  && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
const instant = (v: unknown): v is string => typeof v === 'string'
  && /(Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
export function validJapanSqCalendar(value: unknown): value is JapanSqCalendar {
  if (!value || typeof value !== 'object') return false;
  const d = value as JapanSqCalendar;
  if (d.schemaVersion !== 'jp-market-sq-calendar-v1' || !instant(d.asOf)
    || !date(d.rangeStart) || !date(d.rangeEnd) || d.rangeEnd < d.rangeStart
    || !['AVAILABLE', 'PARTIAL', 'UNAVAILABLE'].includes(d.status)
    || d.dependsOnAi !== false || d.actionAuthority !== false || d.automaticAiCalls !== 0
    || !Array.isArray(d.events) || d.events.length > 4 || !Array.isArray(d.gaps)
    || d.gaps.some(v => typeof v !== 'string')
    || (d.lastSuccessfulAcquisitionAt !== null && !instant(d.lastSuccessfulAcquisitionAt))) return false;
  const ids = new Set<string>();
  return d.events.every(e => {
    if (!e || !/^jp-monthly-sq-\d{4}-\d{2}$/.test(e.eventId) || ids.has(e.eventId)
      || !['MONTHLY_SQ', 'MAJOR_SQ'].includes(e.kind) || typeof e.title !== 'string'
      || !date(e.sqDate) || !date(e.lastTradingDate) || e.lastTradingDate >= e.sqDate
      || e.sqDate < d.rangeStart || e.sqDate > d.rangeEnd
      || !['TODAY', 'LAST_TRADING_DAY', 'EVENT_WEEK', 'UPCOMING'].includes(e.stage)
      || !['VERIFIED', 'UNAVAILABLE_OR_CONFLICT'].includes(e.calendarStatus)
      || (e.tradingSessionsUntil !== null && (!Number.isInteger(e.tradingSessionsUntil) || e.tradingSessionsUntil < 0))
      || !instant(e.knownAt) || typeof e.summary !== 'string' || typeof e.sourceSha256 !== 'string'
      || !/^[a-f0-9]{64}$/.test(e.sourceSha256) || e.directionalSignal !== null || e.requiresAiResult !== false) return false;
    try { const url = new URL(e.sourceRef); if (url.protocol !== 'https:' || url.hostname !== 'www.jpx.co.jp') return false; }
    catch { return false; }
    ids.add(e.eventId); return true;
  });
}
export function sqCalendarIsCurrent(data: JapanSqCalendar | null, now: number): boolean {
  if (!data) return false;
  const age = now - Date.parse(data.asOf);
  return age >= -60_000 && age < 180_000
    && new Date(now + 9 * 3600_000).toISOString().slice(0, 10) === data.rangeStart;
}

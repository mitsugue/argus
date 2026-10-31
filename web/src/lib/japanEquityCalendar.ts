// Events an index ETF holder needs, each with what it means (owner 2026-10-02).
export interface EquityCalendarEvent {
  eventId: string; kind: string; at: string; dateOnly: boolean; date: string; daysUntil: number;
  titleJa: string; importance: 'high' | 'medium' | 'low'; whatJa: string; soWhatJa: string; watchJa: string;
  pastTendencyJa?: string | null;
  market?: 'JP'|'US'; sourceTimezone?: string; sourceFromDate?: string; sourceToDate?: string; rangeEndAt?: string;
  certainty?: 'COMPANY_SCHEDULE'|'PROVIDER_ESTIMATE'; receivedAt?: string;
  source: string; actionAuthority: false;
}
export interface EquityCalendar {
  schemaVersion: 'jp-equity-event-calendar-v1'; asOf: string; status: 'AVAILABLE' | 'PARTIAL';
  rangeStart: string; rangeEnd: string; gaps: string[]; events: EquityCalendarEvent[];
  dependsOnAi: false; automaticAiCalls: 0; actionAuthority: false;
}

const text = (v: unknown, max = 400) => typeof v === 'string' && v.length > 0 && v.length <= max;
const day = (v: unknown) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v);

function validCorporate(e: Record<string, unknown>): boolean {
  const zone = e.market === 'JP' ? 'Asia/Tokyo' : e.market === 'US' ? 'America/New_York' : '';
  const calendarDay = (v: unknown): v is string => typeof v === 'string' && day(v)
    && Number.isFinite(Date.parse(v+'T00:00:00Z')) && new Date(v+'T00:00:00Z').toISOString().slice(0,10) === v;
  if (!zone || e.sourceTimezone !== zone || e.dateOnly !== true
    || !calendarDay(e.sourceFromDate) || !calendarDay(e.sourceToDate) || e.date !== e.sourceFromDate
    || e.sourceFromDate > e.sourceToDate || (Date.parse(e.sourceToDate)-Date.parse(e.sourceFromDate))/86400000 > 7
    || typeof e.at !== 'string' || typeof e.rangeEndAt !== 'string'
    || !/(Z|[+-]\d{2}:\d{2})$/.test(e.at) || !/(Z|[+-]\d{2}:\d{2})$/.test(e.rangeEndAt)
    || typeof e.receivedAt !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(e.receivedAt)
    || !Number.isFinite(Date.parse(e.receivedAt))) return false;
  if (e.certainty === 'COMPANY_SCHEDULE') {
    if (e.market !== 'JP' || e.sourceFromDate !== e.sourceToDate || e.source !== 'J-Quants 決算発表予定日') return false;
  } else if (e.certainty !== 'PROVIDER_ESTIMATE' || e.source !== 'Yahoo Finance') return false;
  const first = Date.parse(e.at), last = Date.parse(e.rangeEndAt);
  if (!Number.isFinite(first) || !Number.isFinite(last) || first > last) return false;
  try {
    const nativeDay = (at: number) => new Intl.DateTimeFormat('sv-SE',{timeZone:zone}).format(new Date(at));
    const nativeClock = (at: number) => new Intl.DateTimeFormat('en-GB',{
      timeZone:zone,hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',
    }).format(new Date(at));
    return nativeDay(first) === e.sourceFromDate && nativeDay(last) === e.sourceToDate
      && nativeClock(first) === '00:00:00' && nativeClock(last) === '23:59:59';
  } catch { return false; }
}

export function validEquityCalendar(value: unknown): value is EquityCalendar {
  if (!value || typeof value !== 'object') return false;
  const c = value as Record<string, unknown>;
  if (c.schemaVersion !== 'jp-equity-event-calendar-v1' || c.actionAuthority !== false || c.automaticAiCalls !== 0
    || !['AVAILABLE', 'PARTIAL'].includes(String(c.status)) || !Array.isArray(c.events) || c.events.length > 200
    || !Array.isArray(c.gaps) || !c.gaps.every(g => text(g, 120))) return false;
  return c.events.every((raw) => {
    if (!raw || typeof raw !== 'object') return false;
    const e = raw as Record<string, unknown>;
    return text(e.eventId, 120) && text(e.kind, 40) && text(e.at, 40) && day(e.date) && typeof e.dateOnly === 'boolean'
      && Number.isInteger(e.daysUntil) && text(e.titleJa, 120) && ['high', 'medium', 'low'].includes(String(e.importance))
      && text(e.whatJa) && text(e.soWhatJa) && text(e.watchJa) && e.actionAuthority === false
      && (e.kind !== 'CORPORATE_EARNINGS' || validCorporate(e));
  });
}

const WEEKDAY = ['日', '月', '火', '水', '木', '金', '土'];
/** "10/23(金) 8:30" or "12/29(火)" in Japan time. */
export function equityEventWhen(event: EquityCalendarEvent): string {
  if (event.kind==='CORPORATE_EARNINGS' && event.sourceFromDate && event.sourceToDate) {
    const short=(day:string)=>day.slice(5).replace('-','/');
    return short(event.sourceFromDate)+(event.sourceFromDate!==event.sourceToDate?'〜'+short(event.sourceToDate):'')+(event.market==='US'?' 米国':'');
  }
  const [y, m, d] = event.date.split('-').map(Number);
  const weekday = WEEKDAY[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  const time = event.dateOnly ? '' : ` ${Number(event.at.slice(11, 13))}:${event.at.slice(14, 16)}`;
  return `${m}/${d}(${weekday})${time}`;
}

export function equityEventDistance(event: EquityCalendarEvent, now = Date.now()): string {
  if (!event.dateOnly && Number.isFinite(Date.parse(event.at)) && Date.parse(event.at) <= now) return '発表済み';
  return event.daysUntil <= 0 ? '今日' : event.daysUntil === 1 ? '明日' : `${event.daysUntil}日後`;
}

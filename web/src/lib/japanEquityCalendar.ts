// Events an index ETF holder needs, each with what it means (owner 2026-10-02).
export interface EquityCalendarEvent {
  eventId: string; kind: string; at: string; dateOnly: boolean; date: string; daysUntil: number;
  titleJa: string; importance: 'high' | 'medium' | 'low'; whatJa: string; soWhatJa: string; watchJa: string;
  pastTendencyJa?: string | null;
  source: string; actionAuthority: false;
}
export interface EquityCalendar {
  schemaVersion: 'jp-equity-event-calendar-v1'; asOf: string; status: 'AVAILABLE' | 'PARTIAL';
  rangeStart: string; rangeEnd: string; gaps: string[]; events: EquityCalendarEvent[];
  dependsOnAi: false; automaticAiCalls: 0; actionAuthority: false;
}

const text = (v: unknown, max = 400) => typeof v === 'string' && v.length > 0 && v.length <= max;
const day = (v: unknown) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v);

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
      && text(e.whatJa) && text(e.soWhatJa) && text(e.watchJa) && e.actionAuthority === false;
  });
}

const WEEKDAY = ['日', '月', '火', '水', '木', '金', '土'];
/** "10/23(金) 8:30" or "12/29(火)" in Japan time. */
export function equityEventWhen(event: EquityCalendarEvent): string {
  const [y, m, d] = event.date.split('-').map(Number);
  const weekday = WEEKDAY[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  const time = event.dateOnly ? '' : ` ${Number(event.at.slice(11, 13))}:${event.at.slice(14, 16)}`;
  return `${m}/${d}(${weekday})${time}`;
}

export function equityEventDistance(event: EquityCalendarEvent, now = Date.now()): string {
  if (!event.dateOnly && Number.isFinite(Date.parse(event.at)) && Date.parse(event.at) <= now) return '発表済み';
  return event.daysUntil <= 0 ? '今日' : event.daysUntil === 1 ? '明日' : `${event.daysUntil}日後`;
}

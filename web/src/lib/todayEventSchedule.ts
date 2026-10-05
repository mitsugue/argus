import { deriveDashboardEventDisplayState, type DashboardEvent } from './dashboardEventState';
import type { ImportantEvent } from '../hooks/useImportantEvents';
import type { EquityCalendarEvent } from './japanEquityCalendar';
import { eventTitleJa } from '../domain/eventTitleJa';

export type TodayScheduledEvent =
  | { kind:'dashboard'; key:string; day:string; at:number; released:boolean; event:DashboardEvent }
  | { kind:'legacy'; key:string; day:string; at:number; released:boolean; event:ImportantEvent }
  | { kind:'equity'; key:string; day:string; at:number; released:boolean; event:EquityCalendarEvent };
const jpDay = (v?:string|null) => v && Number.isFinite(Date.parse(v))
  ? new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo'}).format(new Date(v)) : '';
const dayOnly = (v?:string|null) => v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : '';
const identity = (code:string,day:string,title:string) => `${code.includes('SQ')?'SQ':code}:${day}:${code==='AUCTION'?eventTitleJa(code,title):''}`;
const RELEASED = new Set(['RELEASED','REACTION_PENDING','REACTION_CONFIRMED','RESOLVED']);
/** One occurrence per date. A later occurrence of the same indicator stays visible. */
export function todayEventSchedule(dashboard:DashboardEvent[],legacy:ImportantEvent[],equity:EquityCalendarEvent[],now=Date.now()):TodayScheduledEvent[] {
  const rows:TodayScheduledEvent[] = [], seen=new Set<string>();
  const today=jpDay(new Date(now).toISOString());
  const end=jpDay(new Date(now+45*86400000).toISOString());
  const add=(row:TodayScheduledEvent) => {
    if (row.day && !row.released && (row.day<today || row.day>end)) return;
    if (row.released && row.day && row.at<now-7*86400000) return;
    if(seen.has(row.key)) return;
    seen.add(row.key);rows.push(row);
  };
  for(const event of dashboard) {
    const day=jpDay(event.eventTimeUtc)||dayOnly(event.eventDate);
    const at=event.eventTimeUtc?Date.parse(event.eventTimeUtc):Date.parse(`${day}T23:59:59+09:00`);
    // The feed's canonical state, rather than a frontend clock, owns release status.
    add({kind:'dashboard',event,day,at,key:day?identity(event.eventCode,day,event.title):event.eventId,
      released:deriveDashboardEventDisplayState(event).released});
  }
  for(const event of legacy) {
    const jstIso=event.jstTime && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(event.jstTime)
      ? `${event.jstTime.slice(0,10)}T${event.jstTime.slice(11,16)}:00+09:00` : null;
    const timestamp=event.eventTimeUtc||jstIso;
    const day=jpDay(timestamp)||dayOnly(event.date);
    const at=timestamp?Date.parse(timestamp):Date.parse(`${day}T23:59:59+09:00`);
    add({kind:'legacy',event,day,at,key:day?identity(event.eventCode,day,event.title):event.eventId,released:RELEASED.has(event.lifecycle??'')});
  }
  for(const event of equity) {
    const at=Date.parse(event.at.length===10?`${event.date}T23:59:59+09:00`:event.at);
    add({kind:'equity',event,day:event.date,at,key:identity(event.kind,event.date,event.titleJa),released:false});
  }
  return rows.sort((a,b)=>Number(a.released)-Number(b.released)
    || (a.released?b.at-a.at:a.at-b.at) || a.key.localeCompare(b.key));
}

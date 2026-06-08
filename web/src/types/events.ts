// Mirrors the backend /api/argus/events shape. Phase 1 = schedule/risk timing
// only (no forecast/actual/consensus). Kept in sync by convention.

export type EventStatus = 'live' | 'mock';
export type SnapshotStatus = 'live' | 'partial' | 'mock';
export type EventImpact = 'high' | 'medium' | 'low';
export type EventCategory = 'central_bank' | 'inflation' | 'jobs' | 'growth' | 'treasury';
export type Escalation = 'D-7' | 'D-3' | 'D-1' | 'D' | 'D+1' | 'normal';

export interface CalendarEvent {
  id: string;
  title: string;
  category: EventCategory;
  country: string;            // 'US' | 'JP' | ...
  source: string;
  impact: EventImpact;
  eventTimeUtc: string | null;
  eventDate: string | null;   // YYYY-MM-DD
  localTimeJst: string | null;
  daysUntil: number;
  escalation: Escalation;
  rationaleJa: string;
  linkedAssets: string[];
  status: EventStatus;
}

export interface EventSource {
  name: string;
  status: 'live' | 'partial' | 'mock' | 'error';
  lastUpdated: string | null;
}

export interface EventsSnapshot {
  status: SnapshotStatus;
  asOf: string | null;
  timezone: string;
  sources: EventSource[];
  events: CalendarEvent[];
}

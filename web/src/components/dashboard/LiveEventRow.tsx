import React from 'react';
import type { CalendarEvent, EventImpact, Escalation } from '../../types/events';

const IMPACT_COLOR: Record<EventImpact, string> = {
  high: 'var(--risk-high)',
  medium: 'var(--risk-med)',
  low: 'var(--risk-low)',
};

// Escalation chip color — hotter as the event nears (D today = red).
const ESC_COLOR: Record<Escalation, string> = {
  D: 'var(--red)',
  'D-1': 'var(--amber)',
  'D-3': 'var(--amber)',
  'D-7': 'var(--blue)',
  'D+1': 'var(--cyan)',
  normal: 'var(--text-muted)',
};

const CATEGORY_LABEL: Record<string, string> = {
  central_bank: 'Central bank',
  inflation: 'Inflation',
  jobs: 'Jobs',
  growth: 'Growth',
  treasury: 'Treasury',
};

function whenLabel(e: CalendarEvent): string {
  const d = e.daysUntil;
  const rel = d === 0 ? 'Today' : d === 1 ? 'Tomorrow' : d === -1 ? 'Yesterday' : d < 0 ? `${-d}d ago` : `in ${d}d`;
  // Prefer the exact JST time when known, else the date.
  const stamp = e.localTimeJst ?? e.eventDate ?? '';
  return stamp ? `${rel} · ${stamp}` : rel;
}

export const LiveEventRow: React.FC<{ event: CalendarEvent }> = ({ event }) => {
  const isMock = event.status === 'mock';
  return (
    <div className={`levent${isMock ? ' levent--mock' : ''}`}>
      <div className="levent__head">
        <span
          className="levent__esc"
          style={{ ['--esc-color' as string]: ESC_COLOR[event.escalation] }}
        >
          {event.escalation}
        </span>
        <span className="levent__title">{event.title}</span>
        <span className="levent__impact">
          <span className="levent__impact-dot" style={{ background: IMPACT_COLOR[event.impact] }} />
          {event.impact}
        </span>
      </div>

      <div className="levent__meta">
        <span className="levent__country">{event.country}</span>
        <span className="levent__dot">·</span>
        <span>{CATEGORY_LABEL[event.category] ?? event.category}</span>
        <span className="levent__dot">·</span>
        <span>{whenLabel(event)}</span>
        <span className="levent__dot">·</span>
        <span className="levent__source">{event.source}</span>
        {isMock && <span className="levent__mock-badge">mock</span>}
      </div>

      <div className="levent__rationale">{event.rationaleJa}</div>

      {event.linkedAssets.length > 0 && (
        <div className="levent__assets">
          {event.linkedAssets.map((a) => (
            <span className="levent__asset" key={a}>{a}</span>
          ))}
        </div>
      )}
    </div>
  );
};

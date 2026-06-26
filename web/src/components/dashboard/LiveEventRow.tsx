import React from 'react';
import type { CalendarEvent } from '../../types/events';
import { IMPACT_TOKEN, IMPACT_ICON, IMPACT_JA, COUNTDOWN_JA, CATEGORY_JA, whenJa } from '../../lib/eventLabels';

// Unified with the top-page IMPORTANT EVENTS card (v10.162): JP impact (重大/大/中/小)
// + event-impact color, JP proximity, JP category — same vocabulary, top page = baseline.

export const LiveEventRow: React.FC<{ event: CalendarEvent }> = ({ event }) => {
  const isMock = event.status === 'mock';
  const stamp = event.localTimeJst ?? event.eventDate ?? '';
  const escJa = COUNTDOWN_JA[event.escalation] ?? event.escalation;
  return (
    <div className={`levent${isMock ? ' levent--mock' : ''}`}>
      <div className="levent__head">
        {escJa && (
          <span className="levent__esc" style={{ ['--esc-color' as string]: IMPACT_TOKEN[event.impact] ?? 'var(--text-muted)' }}>
            {escJa}
          </span>
        )}
        <span className="levent__title">{event.title}</span>
        <span className="levent__impact" style={{ color: IMPACT_TOKEN[event.impact] ?? 'var(--text-muted)' }}>
          {IMPACT_ICON[event.impact] ?? '·'} 影響:{IMPACT_JA[event.impact] ?? event.impact}
        </span>
      </div>

      <div className="levent__meta">
        <span className="levent__country">{event.country}</span>
        <span className="levent__dot">·</span>
        <span>{CATEGORY_JA[event.category] ?? event.category}</span>
        <span className="levent__dot">·</span>
        <span>{whenJa(event.daysUntil, stamp)}</span>
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

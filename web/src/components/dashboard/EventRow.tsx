import React from 'react';
import type { MarketEvent } from '../../types/dashboard';
import type { RiskLevel } from '../../types/action';

interface Props {
  event: MarketEvent;
}

const IMPACT_COLOR: Record<RiskLevel, string> = {
  low:     'var(--risk-low)',
  med:     'var(--risk-med)',
  high:    'var(--risk-high)',
  extreme: 'var(--risk-extreme)',
};

const IMPACT_LABEL: Record<RiskLevel, string> = {
  low: 'low',
  med: 'medium',
  high: 'high',
  extreme: 'extreme',
};

function formatWhen(at: number): string {
  const diff = at - Date.now();
  const days = Math.round(diff / 86_400_000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days < 0) return `${-days}d ago`;
  return `in ${days}d`;
}

export const EventRow: React.FC<Props> = ({ event }) => {
  return (
    <div className="event-row">
      <span className="event-row__when">{formatWhen(event.at)}</span>
      <span className="event-row__title">{event.title}</span>
      <span className="event-row__kind">{event.kind}</span>
      <span className="event-row__impact">
        <span
          className="event-row__impact-dot"
          style={{ background: IMPACT_COLOR[event.impact] }}
        />
        {IMPACT_LABEL[event.impact]}
      </span>
      {event.note && <span className="event-row__note">{event.note}</span>}
    </div>
  );
};

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
  low: 'low', med: 'medium', high: 'high', extreme: 'extreme',
};

function formatWhen(at: number): string {
  const diff = at - Date.now();
  const days = Math.round(diff / 86_400_000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days < 0) return `${-days}d ago`;
  return `in ${days}d`;
}

// Today-page event row — no kind chip, no body note. Just when / title /
// impact dot. The full event detail and the D-7..D+1 escalation policy
// live on the Event Radar page.
export const CompactEventRow: React.FC<Props> = ({ event }) => {
  return (
    <div className="event-row">
      <span className="event-row__when">{formatWhen(event.at)}</span>
      <span className="event-row__title">{event.title}</span>
      <span />
      <span className="event-row__impact">
        <span className="event-row__impact-dot" style={{ background: IMPACT_COLOR[event.impact] }} />
        {IMPACT_LABEL[event.impact]}
      </span>
    </div>
  );
};

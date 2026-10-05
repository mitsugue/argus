import React from 'react';

/** All event sources share the same impact label, placement and color. */
export function EventImpactBadge({ impact }: { impact: string }) {
  const level = ['critical', 'high', 'medium', 'low'].includes(impact) ? impact : 'low';
  return <span className="event-impact-badge" data-impact={level}>
    影響 {level === 'critical' ? '特大' : level === 'high' ? '大' : level === 'medium' ? '中' : '小'}
  </span>;
}

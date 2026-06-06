import React from 'react';
import type { RiskLevel } from '../../types/action';

interface Props {
  level: RiskLevel;
}

const COLORS: Record<RiskLevel, string> = {
  low:     'var(--risk-low)',
  med:     'var(--risk-med)',
  high:    'var(--risk-high)',
  extreme: 'var(--risk-extreme)',
};

export const RiskIndicator: React.FC<Props> = ({ level }) => (
  <span className="risk">
    <span
      className="risk__dot"
      style={{ ['--risk-fg' as string]: COLORS[level] }}
    />
    <span className="risk__label">{level === 'med' ? 'Medium' : level}</span>
  </span>
);

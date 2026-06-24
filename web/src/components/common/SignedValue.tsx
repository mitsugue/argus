import React from 'react';
import { getNumericTone, getMetricTone, formatSigned, TONE_VAR } from '../../lib/numericTone';

// Shared signed/colored number (v10.124). One place for sign + tone + a11y so
// up/down/profit/loss are consistent everywhere — and a "positive number" is NOT
// green when the metric is semantically adverse (pass metricId, e.g. "vix").

interface Props {
  value: number | null | undefined;
  digits?: number;
  suffix?: string;       // e.g. "%", "¥"
  metricId?: string;     // when set, uses metric polarity (vix → adverse-red on a rise)
  epsilon?: number;
  arrow?: boolean;       // show ▲/▼ (a11y: not color-only)
}

export const SignedValue: React.FC<Props> = ({ value, digits = 2, suffix = '', metricId, epsilon = 0, arrow = true }) => {
  const tone = metricId ? getMetricTone(metricId, value, epsilon) : getNumericTone(value, epsilon);
  const glyph = arrow && (tone === 'positive' ? '▲ ' : tone === 'negative' ? '▼ ' : '');
  const label = tone === 'positive' ? 'up' : tone === 'negative' ? 'down' : tone === 'unavailable' ? 'unavailable' : 'unchanged';
  return (
    <span style={{ color: TONE_VAR[tone] }} aria-label={`${label} ${formatSigned(value, digits, suffix)}`}>
      {glyph}{formatSigned(value, digits, suffix)}
    </span>
  );
};

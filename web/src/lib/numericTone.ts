// Numeric color semantics (v10.119). One source of truth so up/down/profit/loss/
// inflow/outflow are coloured consistently — AND so a "positive number" is not
// blindly green when it is semantically adverse (rising VIX, widening HY OAS…).

export type NumericTone = 'positive' | 'negative' | 'neutral' | 'unavailable';

export const TONE_VAR: Record<NumericTone, string> = {
  positive: 'var(--value-positive)',
  negative: 'var(--value-negative)',
  neutral: 'var(--value-neutral)',
  unavailable: 'var(--value-unavailable)',
};

/** Sign-based tone for price/return/P&L/flow. NaN/null → unavailable; |v|<=eps → neutral. */
export function getNumericTone(value: number | null | undefined, epsilon = 0): NumericTone {
  if (value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value))) {
    return 'unavailable';
  }
  let v = value as number;
  if (Object.is(v, -0)) v = 0;       // normalize negative zero
  if (Math.abs(v) <= epsilon) return 'neutral';
  return v > 0 ? 'positive' : 'negative';
}

/** Signed display string: explicit +/− for non-zero, never "-0.00". */
export function formatSigned(value: number | null | undefined, digits = 2, suffix = ''): string {
  if (value === null || value === undefined || Number.isNaN(value as number)) return '—';
  let v = value as number;
  if (Object.is(v, -0) || Math.abs(v) < Math.pow(10, -digits) / 2) v = 0;
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  return `${sign}${Math.abs(v).toFixed(digits)}${suffix}`;
}

// §10 — a positive number is not always good. Metric polarity metadata.
export type MetricPolarity = 'higher_is_better' | 'higher_is_worse' | 'lower_is_better' | 'direction_only' | 'contextual';

export const METRIC_POLARITY: Record<string, MetricPolarity> = {
  price: 'higher_is_better', return: 'higher_is_better', pnl: 'higher_is_better',
  flow: 'higher_is_better', changePct: 'higher_is_better', allocationDelta: 'direction_only',
  vix: 'higher_is_worse', hyOas: 'higher_is_worse', drawdown: 'higher_is_worse',
  riskScore: 'higher_is_worse', borrowCost: 'higher_is_worse', volatility: 'higher_is_worse',
  us10y: 'contextual', us2y: 'contextual', real10y: 'contextual', usdjpy: 'direction_only',
};

/** Tone for a metric's CHANGE, respecting polarity (rising VIX → negative/red). */
export function getMetricTone(metricId: string, change: number | null | undefined, epsilon = 0): NumericTone {
  const base = getNumericTone(change, epsilon);
  if (base === 'unavailable' || base === 'neutral') return base;
  const pol = METRIC_POLARITY[metricId] ?? 'higher_is_better';
  if (pol === 'direction_only' || pol === 'contextual') return 'neutral';
  const adverse = pol === 'higher_is_worse' || pol === 'lower_is_better';
  if (!adverse) return base;
  return base === 'positive' ? 'negative' : 'positive';   // invert for adverse metrics
}

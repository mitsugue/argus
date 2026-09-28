import React from 'react';
import './TriangleStepLoader.css';

/** Three points breathing around one orbit; halos trail a fraction behind.
 *  Label-driven and polite to assistive tech; motion stops under
 *  prefers-reduced-motion. The wrapper itself never animates. */
export const TriangleStepLoader: React.FC<{
  label?: string; compact?: boolean;
}> = ({ label = '更新中', compact = false }) => (
  <span className={`triangle-step-loader${compact ? ' is-compact' : ''}`}
    role="status" aria-live="polite" aria-label={label || '更新中'}>
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle className="triangle-step-loader__halo halo-1" cx="12" cy="7.3" r="3.1" />
      <circle className="triangle-step-loader__halo halo-2" cx="16.07" cy="14.35" r="3.1" />
      <circle className="triangle-step-loader__halo halo-3" cx="7.93" cy="14.35" r="3.1" />
      <circle className="triangle-step-loader__dot dot-1" cx="12" cy="7.3" r="2.1" />
      <circle className="triangle-step-loader__dot dot-2" cx="16.07" cy="14.35" r="2.1" />
      <circle className="triangle-step-loader__dot dot-3" cx="7.93" cy="14.35" r="2.1" />
    </svg>
    {label && <span className="triangle-step-loader__label">{label}</span>}
  </span>
);

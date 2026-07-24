import React from 'react';
import './TriangleStepLoader.css';

export const TriangleStepLoader: React.FC<{
  label?: string; compact?: boolean;
}> = ({ label = '更新中', compact = false }) => (
  <span className={`triangle-step-loader${compact ? ' is-compact' : ''}`}
    role="status" aria-live="polite">
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle className="triangle-step-loader__dot dot-1" cx="12" cy="7.3" r="2.2" />
      <circle className="triangle-step-loader__dot dot-2" cx="16.1" cy="14.35" r="2.2" />
      <circle className="triangle-step-loader__dot dot-3" cx="7.9" cy="14.35" r="2.2" />
    </svg>
    {label && <span className="triangle-step-loader__label">{label}</span>}
  </span>
);

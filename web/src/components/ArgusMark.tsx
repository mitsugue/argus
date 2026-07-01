import React from 'react';

// A.R.G.U.S. monogram (v10.192) — "eye in a triangle". ARGUS is the hundred-eyed
// giant of myth (the all-seeing watchman), so the mark is a single eye held inside
// an A-triangle: minimal, flat, one accent. The triangle + eye outline follow
// currentColor (so the mark tracks the brand text), the iris uses the cyan accent.
export const ArgusMark: React.FC<{ size?: number; className?: string }> = ({ size = 22, className }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 48 48"
    className={className}
    fill="none"
    role="img"
    aria-label="A.R.G.U.S."
  >
    <path d="M24 6 L6 40 L42 40 Z" stroke="currentColor" strokeWidth="2.6" strokeLinejoin="round" />
    <path d="M14.5 30 Q24 22 33.5 30 Q24 38 14.5 30 Z" stroke="currentColor" strokeWidth="2" fill="none" />
    <circle cx="24" cy="30" r="4" fill="var(--cyan, #22D3EE)" />
  </svg>
);

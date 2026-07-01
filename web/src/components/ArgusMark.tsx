import React from 'react';
import './ArgusMark.css';
// (build marker) v11.0.4 Pages redeploy — prior deploy failed at the deploy step on a
// Pages concurrency conflict from rapid version bumps; build itself was green.

// A.R.G.U.S. monogram (v10.192) — "eye in a triangle". ARGUS is the hundred-eyed
// watchman, so the mark is a single eye held inside an A-triangle. v10.194: the eye
// IS the system-health beacon — the iris takes the health color and glows/pulses, so
// the mark itself becomes the status light (the old separate green dot is retired).
export type MarkStatus = 'ok' | 'warning' | 'stopped' | 'off';

const STATUS_COLOR: Record<MarkStatus, string> = {
  ok: 'var(--green, #34d399)',
  warning: 'var(--amber, #fbbf24)',
  stopped: 'var(--red, #ef4444)',
  off: '#5f6b78',
};

export const ArgusMark: React.FC<{
  size?: number;
  className?: string;
  /** System-health status — colors + pulses the iris. Omit for the static cyan mark. */
  status?: MarkStatus;
}> = ({ size = 22, className, status }) => {
  const iris = status ? STATUS_COLOR[status] : 'var(--cyan, #22D3EE)';
  const live = !!status && status !== 'off';   // ok / warning / stopped → the eye is awake
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      className={`argus-mark${live ? ' argus-mark--live' : ''}${className ? ` ${className}` : ''}`}
      style={{ ['--iris' as string]: iris }}
      fill="none"
      role="img"
      aria-label="A.R.G.U.S. Pro"
    >
      <path d="M24 6 L6 40 L42 40 Z" stroke="currentColor" strokeWidth="2.6" strokeLinejoin="round" />
      <path d="M14.5 30 Q24 22 33.5 30 Q24 38 14.5 30 Z" stroke="currentColor" strokeWidth="2" fill="none" />
      {/* radiating pulse ring — "the eye is watching" */}
      {live && <circle className="argus-mark__pulse" cx="24" cy="30" r="4" fill="none" stroke={iris} strokeWidth="2" />}
      {/* soft blurred bloom that breathes in the health color (sits behind the crisp iris) */}
      <circle className="argus-mark__glow" cx="24" cy="30" r="4" fill={iris} />
      {/* crisp iris core with a layered halo */}
      <circle className="argus-mark__iris" cx="24" cy="30" r="4" fill={iris} />
      {/* tiny catch-light so the eye reads as glass, not a flat dot */}
      <circle className="argus-mark__glint" cx="22.4" cy="28.4" r="1" fill="#ffffff" opacity="0.9" />
    </svg>
  );
};

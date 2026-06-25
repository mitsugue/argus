import React from 'react';
import { SIGNALS, SIGNAL_ORDER, type SignalCode } from '../../domain/actionLevel';
import './SignalGauge.css';

// Small inline 7-light signal gauge (red caution → green clear). The current
// segment is lit (bright + glow); the rest stay dim but tinted so the 1-7 stage
// reads at a glance. Mirrors the top command gauge (v10.131), sized down for
// per-stock cards (replaces the "ACTION 4/7" text).
export const SignalGauge: React.FC<{ code: SignalCode; className?: string }> = ({ code, className }) => (
  <span className={`sg${className ? ' ' + className : ''}`} role="img"
        aria-label={`アクション ${SIGNALS[code].level}/7(左=注意・右=良好)`}>
    {SIGNAL_ORDER.map((c) => (
      <span key={c}
        className={`sg-seg${c === code ? ' sg-seg--on' : ''}`}
        style={{ ['--seg' as string]: `var(${SIGNALS[c].token})` }}
        title={`${SIGNALS[c].level}. ${SIGNALS[c].labelJa}`} />
    ))}
  </span>
);

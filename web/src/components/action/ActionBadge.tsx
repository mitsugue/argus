import React from 'react';
import { actionDef } from '../../domain/actions';
import type { ActionKey, CoreActionKey } from '../../types/action';
import './ActionBadge.css';

interface Props {
  action: ActionKey | CoreActionKey;
  size?: 'sm' | 'md' | 'lg';
  showEn?: boolean;
}

// One badge = one decision, rendered with the color/icon/JP-label defined
// in domain/actions.ts. Components must use this — never re-render an
// action label with their own hex.
export const ActionBadge: React.FC<Props> = ({ action, size = 'md', showEn = false }) => {
  const def = actionDef(action);
  if (!def) return null;
  const style: React.CSSProperties = {
    // Local-scoped CSS vars so a single .action-badge rule can color any badge.
    ['--abg-fg' as string]: `var(${def.cssVar})`,
    ['--abg-bg' as string]: `var(${def.bgVar})`,
  };
  return (
    <span
      className={`action-badge action-badge--${size}`}
      style={style}
      role="img"
      aria-label={`${def.en} — ${def.jp}`}
    >
      <span className="action-badge__icon" aria-hidden>{def.icon}</span>
      <span className="action-badge__jp">{def.jp}</span>
      {showEn && <span className="action-badge__en">{def.en}</span>}
    </span>
  );
};

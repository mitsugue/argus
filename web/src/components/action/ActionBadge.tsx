import React from 'react';
import { actionDef, actionLabelJa } from '../../domain/actions';
import type { ActionKey, CoreActionKey } from '../../types/action';
import './ActionBadge.css';

interface PillProps {
  action: ActionKey | CoreActionKey;
  size?: 'sm' | 'md' | 'lg';
}

// Compact action pill — used in action cards, watchlist rows, event lists.
// Calm: subtle wash background + small dot + label. No icon glyphs.
export const ActionPill: React.FC<PillProps> = ({ action, size = 'md' }) => {
  const def = actionDef(action);
  if (!def) return null;
  const style: React.CSSProperties = {
    ['--abg-fg' as string]: `var(${def.cssVar})`,
    ['--abg-bg' as string]: `var(${def.bgVar})`,
  };
  const cls = size === 'md' ? 'action-pill' : `action-pill action-pill--${size}`;
  return (
    <span className={cls} style={style} aria-label={def.longLabel} title={def.longLabel}>
      {actionLabelJa(def.key)}
    </span>
  );
};

interface HeroProps {
  action: ActionKey | CoreActionKey;
}

// Hero rendering — large flat type for the Daily Command Center primary
// judgment. No pill background — let the typography carry it.
export const ActionHero: React.FC<HeroProps> = ({ action }) => {
  const def = actionDef(action);
  if (!def) return null;
  const style: React.CSSProperties = {
    ['--abg-fg' as string]: `var(${def.cssVar})`,
  };
  return (
    <span className="action-hero" style={style} title={def.longLabel}>
      {actionLabelJa(def.key)}
    </span>
  );
};

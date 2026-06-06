// Action label design system — single source of truth. Every component
// that renders an action label must read from here; hardcoded colors are
// a code smell.

import type { ActionKey, CoreActionKey } from '../types/action';

export interface ActionDef {
  key: ActionKey | CoreActionKey;
  label: string;       // short display label (used in pills)
  longLabel: string;   // for hero-card rendering
  cssVar: string;      // foreground color CSS variable
  bgVar: string;       // soft wash background CSS variable
  tone: 'urgent' | 'caution' | 'neutral' | 'patient' | 'opportunity' | 'positive' | 'idle';
}

// Tactical actions — used for everything except the core long-term portfolio.
export const ACTIONS: Record<ActionKey, ActionDef> = {
  EXIT: {
    key: 'EXIT',
    label: 'Exit',
    longLabel: 'EXIT',
    cssVar: '--action-exit',
    bgVar: '--action-exit-bg',
    tone: 'urgent',
  },
  TRIM: {
    key: 'TRIM',
    label: 'Trim',
    longLabel: 'TRIM',
    cssVar: '--action-trim',
    bgVar: '--action-trim-bg',
    tone: 'caution',
  },
  WAIT: {
    key: 'WAIT',
    label: 'Wait',
    longLabel: 'WAIT',
    cssVar: '--action-wait',
    bgVar: '--action-wait-bg',
    tone: 'neutral',
  },
  WAIT_FOR_PULLBACK: {
    key: 'WAIT_FOR_PULLBACK',
    label: 'Wait for Pullback',
    longLabel: 'WAIT FOR PULLBACK',
    cssVar: '--action-pullback',
    bgVar: '--action-pullback-bg',
    tone: 'patient',
  },
  BUY_DIP: {
    key: 'BUY_DIP',
    label: 'Buy Dip',
    longLabel: 'BUY DIP',
    cssVar: '--action-dip',
    bgVar: '--action-dip-bg',
    tone: 'opportunity',
  },
  ADD: {
    key: 'ADD',
    label: 'Add',
    longLabel: 'ADD',
    cssVar: '--action-add',
    bgVar: '--action-add-bg',
    tone: 'positive',
  },
  HOLD: {
    key: 'HOLD',
    label: 'Hold',
    longLabel: 'HOLD',
    cssVar: '--action-hold',
    bgVar: '--action-hold-bg',
    tone: 'idle',
  },
};

// Core (long-term index) portfolio — quieter vocabulary. Index funds
// should not appear next to tactical-action labels.
export const CORE_ACTIONS: Record<CoreActionKey, ActionDef> = {
  CONTINUE: {
    key: 'CONTINUE',
    label: 'Continue',
    longLabel: 'CONTINUE',
    cssVar: '--action-add',
    bgVar: '--action-add-bg',
    tone: 'positive',
  },
  GRADUAL_ADD: {
    key: 'GRADUAL_ADD',
    label: 'Gradual Add',
    longLabel: 'GRADUAL ADD',
    cssVar: '--action-dip',
    bgVar: '--action-dip-bg',
    tone: 'opportunity',
  },
  DEFER_LUMP_SUM: {
    key: 'DEFER_LUMP_SUM',
    label: 'Defer Lump Sum',
    longLabel: 'DEFER LUMP SUM',
    cssVar: '--action-wait',
    bgVar: '--action-wait-bg',
    tone: 'neutral',
  },
  NO_SELL_ACTION: {
    key: 'NO_SELL_ACTION',
    label: 'No Sell Action',
    longLabel: 'NO SELL ACTION',
    cssVar: '--action-hold',
    bgVar: '--action-hold-bg',
    tone: 'idle',
  },
};

// Display order — urgent / caution on the left, positive on the right.
// Used by any UI that needs to render the full label list (legend, AI
// Review sheet, future filter chips).
export const ACTION_ORDER: ActionKey[] = [
  'EXIT',
  'TRIM',
  'WAIT_FOR_PULLBACK',
  'WAIT',
  'HOLD',
  'BUY_DIP',
  'ADD',
];

export const CORE_ACTION_ORDER: CoreActionKey[] = [
  'CONTINUE',
  'GRADUAL_ADD',
  'DEFER_LUMP_SUM',
  'NO_SELL_ACTION',
];

export function actionDef(key: ActionKey | CoreActionKey): ActionDef {
  return (
    (ACTIONS as Record<string, ActionDef>)[key] ??
    (CORE_ACTIONS as Record<string, ActionDef>)[key]
  );
}

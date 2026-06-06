// Action label design system — the single source of truth for every place
// the app shows an action label (color, icon, Japanese text). Components
// must NEVER hardcode a color or icon for these labels — read from here.

import type { ActionKey, CoreActionKey } from '../types/action';

export interface ActionDef {
  key: ActionKey | CoreActionKey;
  en: string;            // canonical English
  jp: string;            // short Japanese label (3–6 chars)
  icon: string;          // single-glyph icon (matches command-center mono aesthetic)
  cssVar: string;        // CSS custom property name for the foreground color
  bgVar: string;         // CSS custom property name for the wash background
  semantic:
    | 'urgent'
    | 'secure'
    | 'neutral'
    | 'patient'
    | 'opportunity'
    | 'positive'
    | 'idle';
}

// ── Tactical actions — used everywhere except the core portfolio ─────────
export const ACTIONS: Record<ActionKey, ActionDef> = {
  ESCAPE: {
    key: 'ESCAPE',
    en: 'ESCAPE',
    jp: '逃げる',
    icon: '⏏',
    cssVar: '--action-escape',
    bgVar: '--action-escape-bg',
    semantic: 'urgent',
  },
  TAKE_PARTIAL_PROFIT: {
    key: 'TAKE_PARTIAL_PROFIT',
    en: 'PARTIAL',
    jp: '一部利確',
    icon: '◐',
    cssVar: '--action-partial',
    bgVar: '--action-partial-bg',
    semantic: 'secure',
  },
  WAIT: {
    key: 'WAIT',
    en: 'WAIT',
    jp: '見送る',
    icon: '‖',
    cssVar: '--action-wait',
    bgVar: '--action-wait-bg',
    semantic: 'neutral',
  },
  PULL_BACK: {
    key: 'PULL_BACK',
    en: 'PULL BACK',
    jp: '引きつける',
    icon: '⌖',
    cssVar: '--action-pullback',
    bgVar: '--action-pullback-bg',
    semantic: 'patient',
  },
  BUY_THE_DIP: {
    key: 'BUY_THE_DIP',
    en: 'DIP',
    jp: '拾う',
    icon: '▽',
    cssVar: '--action-dip',
    bgVar: '--action-dip-bg',
    semantic: 'opportunity',
  },
  ADD: {
    key: 'ADD',
    en: 'ADD',
    jp: '追加する',
    icon: '△',
    cssVar: '--action-add',
    bgVar: '--action-add-bg',
    semantic: 'positive',
  },
  DO_NOTHING: {
    key: 'DO_NOTHING',
    en: 'HOLD',
    jp: '何もしない',
    icon: '○',
    cssVar: '--action-idle',
    bgVar: '--action-idle-bg',
    semantic: 'idle',
  },
};

// Display order on a 7-cell legend — urgent on the left, positive on the right.
export const ACTION_ORDER: ActionKey[] = [
  'ESCAPE',
  'TAKE_PARTIAL_PROFIT',
  'PULL_BACK',
  'WAIT',
  'DO_NOTHING',
  'BUY_THE_DIP',
  'ADD',
];

// ── Core portfolio actions — index funds get their own calm vocabulary ──
export const CORE_ACTIONS: Record<CoreActionKey, ActionDef> = {
  ACCUMULATE_CONTINUE: {
    key: 'ACCUMULATE_CONTINUE',
    en: 'CONTINUE',
    jp: '積立継続',
    icon: '∞',
    cssVar: '--action-add',
    bgVar: '--action-add-bg',
    semantic: 'positive',
  },
  WAIT_LUMP_SUM: {
    key: 'WAIT_LUMP_SUM',
    en: 'HOLD LUMP',
    jp: '一括待機',
    icon: '‖',
    cssVar: '--action-wait',
    bgVar: '--action-wait-bg',
    semantic: 'neutral',
  },
  ADD_GRADUALLY: {
    key: 'ADD_GRADUALLY',
    en: 'GRADUAL',
    jp: '段階追加',
    icon: '▽',
    cssVar: '--action-dip',
    bgVar: '--action-dip-bg',
    semantic: 'opportunity',
  },
  NO_SELL_NEEDED: {
    key: 'NO_SELL_NEEDED',
    en: 'STEADY',
    jp: '売却不要',
    icon: '○',
    cssVar: '--action-idle',
    bgVar: '--action-idle-bg',
    semantic: 'idle',
  },
};

export const CORE_ACTION_ORDER: CoreActionKey[] = [
  'ACCUMULATE_CONTINUE',
  'ADD_GRADUALLY',
  'WAIT_LUMP_SUM',
  'NO_SELL_NEEDED',
];

export function actionDef(key: ActionKey | CoreActionKey): ActionDef {
  return (ACTIONS as Record<string, ActionDef>)[key] ?? (CORE_ACTIONS as Record<string, ActionDef>)[key];
}

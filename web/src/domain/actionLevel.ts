// ACTION LEVEL — canonical source of truth (action-level-v1, v10.119).
//
// WHY: the word HOLD was read by the owner as "keeping is safe / new entry is OK".
// That ambiguity caused optimistic new position-taking. The Action Level system
// makes the permission EXPLICIT and separate from the signal word: every signal
// carries new-entry / add / existing-position permissions. HOLD is never shown
// alone — it becomes HOLD ONLY (entry + add BLOCKED).
//
// Action Level is NOT market regime and NOT confidence. Decision-support only —
// EXIT never sends an order or decides quantity.

export type SignalCode = 'ENTER' | 'PREPARE' | 'HOLD_ONLY' | 'PAUSE' | 'REVIEW' | 'DEFEND' | 'EXIT';
export type EntryPerm = 'ALLOWED' | 'BLOCKED';
export type ExistingPerm = 'MAINTAIN' | 'MONITOR' | 'REASSESS' | 'REDUCE_RISK' | 'EXIT';
export type DataQuality = 'LIVE' | 'PARTIAL' | 'DELAYED' | 'STALE' | 'MOCK' | 'UNKNOWN' | 'UNAVAILABLE';
export type OwnerState = 'none' | 'watch' | 'active' | 'held' | 'protected';

export const SIGNAL_SCHEMA_VERSION = 'action-level-v1';

export interface SignalDef {
  code: SignalCode;
  level: number;          // 1 (EXIT) … 7 (ENTER)
  labelEn: string;
  labelJa: string;
  token: string;          // css var for the signal color
  permissions: { newEntry: EntryPerm; add: EntryPerm; existingPosition: ExistingPerm };
  riskBudgetRequired?: boolean;
  waitForTrigger?: boolean;
  exitPreparation?: boolean;
}

// Ordered most-defensive (1) → least-defensive (7). The 7-segment bar reads
// EXIT | DEFEND | REVIEW | PAUSE | HOLD ONLY | PREPARE | ENTER.
export const SIGNALS: Record<SignalCode, SignalDef> = {
  EXIT: { code: 'EXIT', level: 1, labelEn: 'EXIT', labelJa: '撤退', token: '--signal-exit',
    permissions: { newEntry: 'BLOCKED', add: 'BLOCKED', existingPosition: 'EXIT' } },
  DEFEND: { code: 'DEFEND', level: 2, labelEn: 'DEFEND', labelJa: '防御', token: '--signal-defend',
    permissions: { newEntry: 'BLOCKED', add: 'BLOCKED', existingPosition: 'REDUCE_RISK' }, exitPreparation: true },
  REVIEW: { code: 'REVIEW', level: 3, labelEn: 'REVIEW', labelJa: '再点検', token: '--signal-review',
    permissions: { newEntry: 'BLOCKED', add: 'BLOCKED', existingPosition: 'REASSESS' } },
  PAUSE: { code: 'PAUSE', level: 4, labelEn: 'PAUSE', labelJa: '保留', token: '--signal-pause',
    permissions: { newEntry: 'BLOCKED', add: 'BLOCKED', existingPosition: 'MONITOR' } },
  HOLD_ONLY: { code: 'HOLD_ONLY', level: 5, labelEn: 'HOLD ONLY', labelJa: '保有のみ', token: '--signal-hold-only',
    permissions: { newEntry: 'BLOCKED', add: 'BLOCKED', existingPosition: 'MAINTAIN' } },
  PREPARE: { code: 'PREPARE', level: 6, labelEn: 'PREPARE', labelJa: '準備', token: '--signal-prepare',
    permissions: { newEntry: 'BLOCKED', add: 'BLOCKED', existingPosition: 'MAINTAIN' }, waitForTrigger: true },
  ENTER: { code: 'ENTER', level: 7, labelEn: 'ENTER', labelJa: 'エントリー可', token: '--signal-enter',
    permissions: { newEntry: 'ALLOWED', add: 'ALLOWED', existingPosition: 'MAINTAIN' }, riskBudgetRequired: true },
};

export const SIGNAL_ORDER: SignalCode[] = ['EXIT', 'DEFEND', 'REVIEW', 'PAUSE', 'HOLD_ONLY', 'PREPARE', 'ENTER'];

// Legacy tactical action → base signal (§4). BUY_DIP is conditional (resolved below).
const LEGACY_MAP: Record<string, SignalCode> = {
  EXIT: 'EXIT', TRIM: 'DEFEND', WAIT: 'PAUSE', HOLD: 'HOLD_ONLY',
  WAIT_FOR_PULLBACK: 'PREPARE', ADD: 'ENTER',
  // core/fund
  CONTINUE: 'HOLD_ONLY', GRADUAL_ADD: 'ENTER', DEFER_LUMP_SUM: 'PAUSE', NO_SELL_ACTION: 'HOLD_ONLY',
};

// Downside override → signal (§4). These can only make the posture MORE defensive.
const OVERRIDE_MAP: Record<string, SignalCode> = {
  REVIEW_REQUIRED: 'REVIEW', DO_NOT_ADD: 'REVIEW', TRIM_WATCH: 'DEFEND',
  EXIT_WATCH: 'DEFEND', HOLD_CAUTION: 'HOLD_ONLY', WAIT: 'PAUSE',
};

export interface ResolveCtx {
  downsideOverride?: string | null;
  dataQuality?: DataQuality;
  materialDownside?: boolean;
  gatesPass?: boolean;          // for BUY_DIP → ENTER only when all gates pass
  exitConfirmed?: boolean;      // EXIT_WATCH → EXIT only when the rule confirms exit
  ownerState?: OwnerState;
}

export interface ResolvedSignal extends SignalDef {
  legacyAction: string;
  schemaVersion: string;
  dataQuality: DataQuality;
  ownerState: OwnerState;
  mappingReason: string;
}

const MORE_DEFENSIVE = (a: SignalCode, b: SignalCode): SignalCode =>
  SIGNALS[a].level <= SIGNALS[b].level ? a : b;

export function resolveSignal(legacyAction: string, ctx: ResolveCtx = {}): ResolvedSignal {
  const dq = ctx.dataQuality ?? 'LIVE';
  let reason = 'legacy map';
  let code: SignalCode;

  if (legacyAction === 'BUY_DIP') {
    // ENTER only when data is fresh, no downside override, and gates pass.
    const ok = !!ctx.gatesPass && !ctx.downsideOverride
      && !['STALE', 'MOCK', 'UNKNOWN', 'UNAVAILABLE'].includes(dq);
    code = ok ? 'ENTER' : 'PREPARE';
    reason = ok ? 'BUY_DIP gates passed → ENTER' : 'BUY_DIP gates not met → PREPARE';
  } else {
    code = LEGACY_MAP[legacyAction] ?? 'PAUSE';
  }

  // Downside override — never less defensive than the base.
  if (ctx.downsideOverride) {
    let ov = OVERRIDE_MAP[ctx.downsideOverride] ?? 'REVIEW';
    if (ctx.downsideOverride === 'EXIT_WATCH' && ctx.exitConfirmed) ov = 'EXIT';
    code = MORE_DEFENSIVE(code, ov);
    reason = `downside override ${ctx.downsideOverride}`;
  }

  // Data-quality gates (§6).
  if (code === 'ENTER' && (dq === 'STALE' || dq === 'MOCK')) {
    code = 'PREPARE';
    reason = `${dq} data cannot ENTER → PREPARE`;
  }
  if (ctx.materialDownside && ['PARTIAL', 'STALE', 'UNKNOWN', 'UNAVAILABLE'].includes(dq)) {
    code = MORE_DEFENSIVE(code, 'REVIEW');
    reason = `material downside + ${dq} → at least REVIEW`;
  }

  return {
    ...SIGNALS[code], legacyAction, schemaVersion: SIGNAL_SCHEMA_VERSION,
    dataQuality: dq, ownerState: ctx.ownerState ?? 'none', mappingReason: reason,
  };
}

// Position-aware instruction text (§5). Minimal flag only — no amounts.
export function positionInstruction(sig: SignalDef, ownerState: OwnerState, locale: 'en' | 'ja' = 'en'): string {
  const held = ownerState === 'held' || ownerState === 'protected' || ownerState === 'active';
  const ja = locale === 'ja';
  const ex = sig.permissions.existingPosition;
  if (!held) {
    if (sig.permissions.newEntry === 'ALLOWED') return ja ? '新規エントリー可(リスク予算内)' : 'New entry permitted (within risk budget)';
    return ja ? '新規エントリーは見送り' : 'Stay out — no new entry';
  }
  const map: Record<ExistingPerm, [string, string]> = {
    MAINTAIN: ['Maintain only — do not add', '維持のみ・買い増し禁止'],
    MONITOR: ['Monitor — no new action', '監視・新規アクションなし'],
    REASSESS: ['Reassess this position now', '直ちに再点検'],
    REDUCE_RISK: ['Prepare to reduce risk', 'リスク縮小の準備'],
    EXIT: ['Exit posture (you decide size)', '撤退の構え(数量はご自身で)'],
  };
  return map[ex][ja ? 1 : 0];
}

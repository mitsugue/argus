// ARGUS V11.4.1 — canonical dashboard event display-state helper (pure).
// The backend already re-resolves the authoritative `state` from the real release
// clock; this derives the UI display flags from that state so the top card renders
// consistently (post shows facts first; released-pending never shows pre as primary).

export type DashboardEventState =
  | 'pre' | 'imminent' | 'released_pending_result'
  | 'post_result' | 'post_answer_checked' | 'stale' | 'not_scoreable';

export interface DashboardEventCaos {
  preScenarioJa?: string; summaryJa?: string; marketPricingJa?: string;
  whatWouldSurpriseJa?: string; assetsToWatch?: string[];
  answerCheckJa?: string; verdict?: string; verdictJa?: string;
  marketReactionJa?: string; impactCommentJa?: string; whatChangedJa?: string;
  limitationsJa?: string[];
}
export interface DashboardEventOfficial {
  available?: boolean; headlineJa?: string; metrics?: Record<string, unknown>;
  source?: string | null; sourceUrl?: string | null; releasedAt?: string | null;
  limitationsJa?: string[];
}
export interface DashboardEventReaction {
  us10yMoveBp?: number | null; usdJpyMovePct?: number | null;
  spyMovePct?: number | null; qqqMovePct?: number | null; iwmMovePct?: number | null;
  vixMovePct?: number | null; goldMovePct?: number | null; btcMovePct?: number | null;
  window?: string | null; riskTone?: string | null; marketConfirmed?: boolean;
  summaryJa?: string; limitationsJa?: string[];
}
export interface DashboardEvent {
  displayEventId: string; eventId: string; eventCode: string; title: string;
  eventTimeUtc?: string | null; eventDate?: string | null;
  importance: 'critical' | 'high' | 'medium' | 'low';
  state: DashboardEventState; stateLabelJa: string; stateTone: string;
  officialResult: DashboardEventOfficial;
  caos: DashboardEventCaos;
  marketReaction?: DashboardEventReaction;
  display: {
    primaryLineJa: string; secondaryLineJa: string;
    showActualFirst: boolean; showPreProminently: boolean; showPreAsHistorical: boolean;
    showPendingResult: boolean; showImpact: boolean; showAnswerCheck: boolean;
    showDuplicateCaosBelow: boolean;
  };
  dedupeKey: string;
  sourceState?: Record<string, unknown>;
}
export interface DashboardEventsResponse {
  schemaVersion: string; asOf: string; items: DashboardEvent[];
  dedupe: { mergedCount: number; hiddenDuplicateCount: number; detailsJa: string[] };
  status: Record<string, unknown>;
}

const BADGE_JA: Record<DashboardEventState, string> = {
  pre: '発表前', imminent: 'まもなく',
  released_pending_result: '発表済み・公式結果取得中',
  post_result: '発表済み・結果反映済み', post_answer_checked: '答え合わせ済み',
  stale: '更新遅延', not_scoreable: '採点不可',
};
const TONE: Record<DashboardEventState, string> = {
  pre: 'pre', imminent: 'pre', released_pending_result: 'pending',
  post_result: 'post', post_answer_checked: 'checked', stale: 'warning', not_scoreable: 'neutral',
};

export interface DashboardEventDisplayState {
  mode: DashboardEventState;
  badgeJa: string;
  tone: string;
  // v11.5: the owner-facing header stamp. Once an event has printed we show a
  // clear boxed "発表済" (released) stamp — never the confusing "答え合わせ済み".
  stampJa: string;
  stampBoxed: boolean;
  released: boolean;
  showActualFirst: boolean;
  showPreProminently: boolean;
  showPreAsHistorical: boolean;
  showPendingResult: boolean;
  showImpact: boolean;
  showAnswerCheck: boolean;
}

// Header stamp per state: released states read "発表済" prominently so it's obvious
// at a glance whether the event has printed; the finer sub-status stays in the body.
const STAMP: Record<DashboardEventState, { ja: string; boxed: boolean }> = {
  pre: { ja: '発表前', boxed: false },
  imminent: { ja: 'まもなく', boxed: false },
  released_pending_result: { ja: '発表済', boxed: true },
  post_result: { ja: '発表済', boxed: true },
  post_answer_checked: { ja: '発表済', boxed: true },
  stale: { ja: '更新遅延', boxed: false },
  not_scoreable: { ja: '発表済', boxed: true },
};

/** Derive UI display flags from an event summary's authoritative state. `now` is
 *  accepted for API symmetry/future use; the backend has already re-resolved state. */
export function deriveDashboardEventDisplayState(
  summary: Pick<DashboardEvent, 'state' | 'officialResult' | 'caos'>,
  _now?: string,
): DashboardEventDisplayState {
  const state = summary.state;
  const released = state === 'released_pending_result' || state === 'post_result'
    || state === 'post_answer_checked' || state === 'stale';
  const post = state === 'post_result' || state === 'post_answer_checked';
  const actualAvail = !!summary.officialResult?.available;
  const stamp = STAMP[state] ?? { ja: BADGE_JA[state] ?? state, boxed: false };
  return {
    mode: state,
    badgeJa: BADGE_JA[state] ?? state,
    tone: TONE[state] ?? 'neutral',
    stampJa: stamp.ja,
    stampBoxed: stamp.boxed,
    released,
    showActualFirst: post,
    showPreProminently: state === 'pre' || state === 'imminent',
    showPreAsHistorical: released,
    showPendingResult: state === 'released_pending_result' || state === 'stale',
    showImpact: post && actualAvail && !!(summary.caos?.impactCommentJa || '').trim(),
    showAnswerCheck: state === 'post_answer_checked',
  };
}

/** Canonical de-dup key mirroring the backend (eventCode + date). Used by the lower
 *  C.A.O.S. area to avoid repeating an event already shown in the top card. */
export function dashboardDedupeKey(eventCode?: string | null, eventDate?: string | null,
                                   eventTimeUtc?: string | null): string {
  const code = (eventCode || '').toUpperCase();
  if (code && code !== 'OTHER' && eventDate) return `${code}:${String(eventDate).slice(0, 10)}`;
  if (code && code !== 'OTHER' && eventTimeUtc) return `${code}:${String(eventTimeUtc).slice(0, 10)}`;
  return `CODE:${code}`;
}

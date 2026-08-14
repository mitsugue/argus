// Recovery Phase A: queue mutations moved to the authenticated operational
// boundary. The static browser deliberately has no admin credential, so these
// compatibility functions degrade to a local no-op until an owner-authenticated
// browser architecture exists.

export type ExplainRequestStatus =
  | 'queued' | 'already_queued' | 'cached_available' | 'rate_limited' | 'invalid';

export interface ExplainRequestResult {
  ok: boolean;
  status: ExplainRequestStatus;
  symbol: string;
  market: string;
  messageJa?: string;
  nextRunHintJa?: string;
}

/** Enqueue an AI-explanation investigation for a mover. Never triggers AI. */
export async function requestExplanation(
  symbol: string, market: string,
  context: 'cause-stack' | 'mover-card' | 'downside-card' | string,
): Promise<ExplainRequestResult | null> {
  void symbol; void market; void context;
  return null;
}

// ── V11.5.4 investigate-now: immediate bounded source sweep (server-side; no LLM) ──
export interface SweepItem {
  title: string;
  /** v11.7.0: Japanese-first display title (never raw English as primary). */
  displayTitleJa?: string; url?: string; publishedAt?: string; snippet?: string;
  sourceFamily?: string; sourceTier?: string; truePublisher?: string;
  freshness?: string; ageHours?: number | null; weakSignal?: boolean;
}

export interface InvestigateNowResult {
  ok: boolean;
  status: 'completed' | 'partial' | 'rate_limited' | 'blocked' | 'error';
  symbol: string;
  market: string;
  elapsedMs?: number;
  nextCheckAt?: string;
  sweep?: {
    searchedSources: string[];
    freshItems: SweepItem[];
    officialItems: SweepItem[];
    professionalItems: SweepItem[];
    publicTextItems: SweepItem[];
    blockedSources: { source: string; reason: string; title?: string }[];
    alternativeSourcesChecked: string[];
    notFoundJa: string[];
  };
  moverCauseUpdated?: boolean;
  bestCurrentLeadJa?: string;
  messageJa?: string;
  aiExplanation?: { status: string; messageJa?: string };
}

/** 念押しボタン: run the immediate source sweep now. Longer timeout — the server
 *  walks official→professional→discovery→article probe within its own 12s budget. */
export async function investigateNow(
  symbol: string, market: string, context: string,
): Promise<InvestigateNowResult | null> {
  void symbol; void market; void context;
  return null;
}

export interface TranslationRequestItem {
  titleOriginal: string;
  source?: string;
  publishedAt?: string;
}

export interface TranslationRequestResult {
  ok: boolean;
  queued: number;
  alreadyTranslated: number;
  alreadyQueued: number;
  rateLimited: boolean;
  queueRemaining?: number;
  nextRunHintJa?: string;
}

/** Enqueue on-screen English news titles for translation. Never triggers translation. */
export async function requestTranslation(
  context: string, symbol: string, market: string, items: TranslationRequestItem[],
): Promise<TranslationRequestResult | null> {
  void context; void symbol; void market; void items;
  return null;
}

// ── auto-queue de-dupe: only POST once per (context|symbol) per session ──
const _translationQueued = new Set<string>();
const _explainQueued = new Set<string>();

export function markTranslationQueued(key: string): boolean {
  if (_translationQueued.has(key)) return false;
  _translationQueued.add(key);
  return true;
}
export function markExplainQueued(key: string): boolean {
  if (_explainQueued.has(key)) return false;
  _explainQueued.add(key);
  return true;
}

/** Debounced auto-queue of visible pending English titles (once per key/session). */
export function autoQueueTranslations(
  key: string, context: string, symbol: string, market: string,
  items: TranslationRequestItem[],
): void {
  if (!items.length) return;
  if (!markTranslationQueued(key)) return;
  void requestTranslation(context, symbol, market, items);
}

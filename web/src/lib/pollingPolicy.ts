// Polling cadence policy (owner request 2026-10-06).
//
// An app switch preserves the mounted screen and does not start a new read.
// Initial acquisition and the existing visible-page cadence still run; a
// manual full reload starts all acquisitions again. Hidden interval ticks
// skip work. Initial mounts in a hidden document resume once when visible.
// Constants are milliseconds; the "was" values document the pre-policy cadence.

/** Watchlist quotes, top-page action labels and the active-event feed (was 15s). */
export const WATCHLIST_VISIBLE_MS = 120_000;

/** Fail-closed visibility guard and crypto quotes (was 30s). */
export const GUARD_VISIBLE_MS = 300_000;

/** Calendar-like state: SQ calendar, market regime, rates, downside incidents (was 60s). */
export const CALENDAR_VISIBLE_MS = 300_000;

/**
 * Slow intelligence feeds: important/dashboard events, decision evidence,
 * event radar, macro analysis, sector heatmap (was 2 min); AI judgment, news
 * intelligence, market shock, supply/demand, flow attribution and the JP
 * market comparison (was 5 min). The JP cached close display has a bounded
 * faster cadence around the close; it does not trigger provider/AI work.
 */
export const FEED_VISIBLE_MS = 600_000;

/** Market ledger stale window (unchanged: 15 min). */
export const LEDGER_STALE_MS = 15 * 60 * 1000;

/** Fund NAV is a daily figure (unchanged: 6h). */
export const FUND_NAV_VISIBLE_MS = 6 * 60 * 60_000;

/** Market news while a covered market session is open (unchanged: 60 min). */
export const MARKET_NEWS_OPEN_INTERVAL_MS = 60 * 60_000;

/** Market news while every covered market is closed (unchanged: 120 min). */
export const MARKET_NEWS_CLOSED_INTERVAL_MS = 120 * 60_000;

/** True only when a document exists and is currently visible to the user. */
export const isPageVisible = (): boolean =>
  typeof document !== 'undefined' && document.visibilityState === 'visible';

/** Resume only an initial acquisition deferred by a hidden document.
 * Ordinary app switches never trigger all readers together. Existing interval
 * schedulers and local freshness/expiry checks remain independent.
 */
export function subscribeInitialVisibleRead(read: () => void): () => void {
  if (typeof document === 'undefined' || isPageVisible()) return () => {};
  const visible = () => {
    if (!isPageVisible()) return;
    document.removeEventListener('visibilitychange', visible);
    read();
  };
  document.addEventListener('visibilitychange', visible);
  return () => document.removeEventListener('visibilitychange', visible);
}

/** Pause periodic acquisition in the background; start a full interval on return.
 * This also prevents suspended, overdue timers from forming a resume burst.
 */
export function scheduleVisibleInterval(read: () => void, intervalMs: number | (() => number)): () => void {
  let timer: number | null = null;
  let generation = 0;
  let stopped = false;
  const pause = () => {
    generation += 1;
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  };
  const visible = () => {
    pause();
    if (stopped || !isPageVisible()) return;
    const startedGeneration = generation;
    timer = window.setInterval(() => {
      if (stopped || generation !== startedGeneration || !isPageVisible()) return;
      read();
      if (typeof intervalMs === 'function') visible();
    }, typeof intervalMs === 'function' ? intervalMs() : intervalMs);
  };
  visible();
  document.addEventListener('visibilitychange', visible);
  return () => { stopped = true; pause(); document.removeEventListener('visibilitychange', visible); };
}

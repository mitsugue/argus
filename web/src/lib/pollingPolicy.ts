// Polling cadence policy (owner-approved 2026-09-28).
//
// The app is opened a few times a day. Every polling hook therefore refreshes
// once when the page becomes visible and then keeps only a relaxed cadence
// while it stays visible. Interval ticks skip all work while the document is
// hidden, so idle or background tabs never consume backend or provider quota.
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
 * market comparison (was 5 min).
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

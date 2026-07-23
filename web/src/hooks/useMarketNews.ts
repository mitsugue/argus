import { useEffect, useState } from 'react';

// Market News feed (news-v2, v10.12) — Finnhub general headlines with
// market-moving keywords flagged.  This is the broad-headline lane, distinct
// from the existing official-disclosure/TDnet 15-minute lane.  It polls hourly
// while either JP or US cash trading can be active, and every two hours outside
// those windows.  GET only; it does not trigger the Research/LLM pipeline.

export interface MarketNewsItem {
  headline: string;
  /** Auto-translated headline (Gemini flash, v10.14) — absent on failure. */
  headlineJa?: string;
  /** v11.5.1: Japanese-first display title (never raw English) + status. */
  displayTitleJa?: string;
  titleOriginal?: string;
  translationStatus?: 'translated' | 'not_needed' | 'pending' | 'failed';
  source: string;
  url: string;
  datetime: number | null;   // unix seconds
  major: boolean;
  /** market/finance-relevant (v10.169) — noise (sports/unrelated) is false. */
  relevant?: boolean;
  /** source-trust tier (v10.169). */
  tier?: 'wire' | 'aggregator' | 'official';
  /** corroboration level (v10.170): official | corroborated (>=2 indep families) | single. */
  corroboration?: 'official' | 'corroborated' | 'single';
  /** Public instrument identifiers inferred from the headline; never owner holdings. */
  linkedSymbols?: string[];
}

export interface MarketNews {
  status: 'live' | 'unavailable' | 'missing_key';
  asOf: string;
  items: MarketNewsItem[];
  noteJa: string;
  lastSuccessfulPollAt?: string | null;
  fetchedCount?: number;
  stale?: boolean;
  nextPollAt?: string | null;
}

export const MARKET_NEWS_OPEN_INTERVAL_MS = 60 * 60_000;
export const MARKET_NEWS_CLOSED_INTERVAL_MS = 120 * 60_000;

export function marketNewsRefreshInterval(now = new Date()): number {
  const clock = (timeZone: string) => {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(now);
    const read = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
    return { weekday: read('weekday'), minutes: Number(read('hour')) * 60 + Number(read('minute')) };
  };
  const jp = clock('Asia/Tokyo');
  const us = clock('America/New_York');
  // Holidays and early closes are still enforced by the canonical backend
  // calendar.  These broad windows only choose a conservative client GET rate.
  const jpWindow = !['Sat', 'Sun'].includes(jp.weekday) && jp.minutes >= 8 * 60 && jp.minutes <= 16 * 60;
  const usWindow = !['Sat', 'Sun'].includes(us.weekday) && us.minutes >= 4 * 60 && us.minutes <= 20 * 60;
  return jpWindow || usWindow ? MARKET_NEWS_OPEN_INTERVAL_MS : MARKET_NEWS_CLOSED_INTERVAL_MS;
}

interface State {
  data: MarketNews | null;
  loading: boolean;
  lastChecked: string | null;
  failureClass: string | null;
}

export function useMarketNews(): State {
  const [state, setState] = useState<State>({
    data: null, loading: true, lastChecked: null, failureClass: null,
  });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: null, loading: false, lastChecked: new Date().toISOString(),
        failureClass: 'backend_not_configured' });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/market-news';
    let cancelled = false;

    async function fetchOnce() {
      if (cancelled || document.hidden) return;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 8_000);
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok || cancelled) {
          if (!cancelled) setState((s) => ({ ...s, loading: false,
            lastChecked: new Date().toISOString(), failureClass: `http_${r.status}` }));
          return;
        }
        const data = (await r.json()) as MarketNews;
        if (!cancelled) setState({ data, loading: false,
          lastChecked: new Date().toISOString(),
          failureClass: data.status === 'live' ? null : data.status });
      } catch (error) {
        clearTimeout(timer);
        if (!cancelled) setState((s) => ({ ...s, loading: false,
          lastChecked: new Date().toISOString(),
          failureClass: error instanceof DOMException && error.name === 'AbortError'
            ? 'timeout' : 'network_error' }));
      }
    }

    void fetchOnce();
    let t = window.setTimeout(function poll() {
      void fetchOnce();
      t = window.setTimeout(poll, marketNewsRefreshInterval());
    }, marketNewsRefreshInterval());
    const onVisible = () => { if (!document.hidden) void fetchOnce(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      clearTimeout(t);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  return state;
}

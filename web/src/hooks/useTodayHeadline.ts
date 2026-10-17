import { FEED_VISIBLE_MS, scheduleVisibleInterval, subscribeInitialVisibleRead } from '../lib/pollingPolicy';
import { useEffect, useState } from 'react';
import { sessionViewCheckpoint } from '../lib/sessionViewCheckpoint';
import { readDrawingState, writeDrawingState } from '../lib/verifiedSnapshot';
import {
  TodayHeadlineDocument, validateTodayHeadline,
} from '../lib/todayHeadline';

// SWR delivery for the compact Today bootstrap: cached headline renders
// immediately, one small network revalidation follows. A failed revalidation
// keeps the cached document with an explicit stale flag — never a blank UI.
const RESUME_KEY = 'today-headline';
const CACHE_KEY = 'argus.todayHeadline.cache.v1';
const REQUEST_TIMEOUT_MS = 15_000;

export interface TodayHeadlineState {
  status: 'loading' | 'data' | 'unavailable' | 'error';
  document: TodayHeadlineDocument | null;
  stale: boolean;
  reason: string | null;
}

interface CacheRecord {
  document: TodayHeadlineDocument;
  storedAt: string;
}

let memory: CacheRecord | null = null;
let inflight: Promise<CacheRecord | null> | null = null;

function baseUrl() {
  return (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)
    ?.replace(/\/$/, '') ?? null;
}

async function fetchHeadline(etag: string | null): Promise<CacheRecord | null> {
  const base = baseUrl();
  if (!base) throw new Error('backend_url_missing');
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort('timeout'), REQUEST_TIMEOUT_MS);
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (etag) headers['If-None-Match'] = `"${etag}"`;
    const response = await fetch(`${base}/api/argus/today-headline`, {
      method: 'GET', cache: 'no-store', headers, signal: controller.signal,
    });
    if (response.status === 304) return null;
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const validation = validateTodayHeadline(await response.json());
    if (!validation.ok) throw new Error(`headline_${validation.reason}`);
    return { document: validation.document, storedAt: new Date().toISOString() };
  } finally {
    window.clearTimeout(timer);
  }
}

export function useTodayHeadline(): TodayHeadlineState {
  const saved = sessionViewCheckpoint.restoredValue(RESUME_KEY) as { cache: CacheRecord | null; state: TodayHeadlineState } | undefined;
  const restored = !!saved && ['data','error','unavailable'].includes(saved.state?.status)
    && (saved.state.document === null || validateTodayHeadline(saved.state.document).ok)
    && (saved.cache === null || validateTodayHeadline(saved.cache?.document).ok && Number.isFinite(Date.parse(saved.cache.storedAt)));
  if (!memory && restored) memory = saved.cache;
  const [state, setState] = useState<TodayHeadlineState>(() => restored ? { ...saved.state, stale: !!saved.state.document } : (memory
    ? { status: 'data', document: memory.document, stale: restored, reason: null }
    : { status: 'loading', document: null, stale: false, reason: null }));

  useEffect(() => {
    let cancelled = false;
    const publish = (next: TodayHeadlineState) => {
      if (!cancelled) {
        setState(next);
        if (sessionViewCheckpoint.keep(RESUME_KEY, { cache: memory, state: next })) void sessionViewCheckpoint.flush();
      }
    };
    const revalidate = async (cached: CacheRecord | null) => {
      if (document.visibilityState !== 'visible') return;
      if (!inflight) {
        inflight = fetchHeadline(cached?.document.headlineSetId ?? null)
          .finally(() => { inflight = null; });
      }
      try {
        const fresh = await inflight;
        if (fresh) {
          memory = fresh;
          publish({ status: 'data', document: fresh.document, stale: false, reason: null });
          void writeDrawingState(CACHE_KEY, fresh);
        } else if (cached) {
          memory = cached;
          publish({ status: 'data', document: cached.document, stale: false, reason: null });
        }
      } catch (error) {
        const reason = error instanceof Error ? error.message : 'fetch_failed';
        if (cached) {
          publish({ status: 'data', document: cached.document, stale: true, reason });
        } else {
          publish({ status: 'error', document: null, stale: false, reason });
        }
      }
    };
    void (async () => {
      let cached = memory;
      if (!cached) {
        const stored = await readDrawingState<CacheRecord | null>(CACHE_KEY, null);
        const validation = stored ? validateTodayHeadline(stored.document) : null;
        if (validation?.ok) {
          cached = { document: validation.document, storedAt: stored!.storedAt };
          memory = cached;
          publish({ status: 'data', document: cached.document, stale: true, reason: 'revalidating' });
        }
      }
      if (!restored) await revalidate(cached);
    })();
    const onVisible = () => {
      if (document.visibilityState === 'visible') void revalidate(memory);
    };
    const stopInitialOnVisible = subscribeInitialVisibleRead(onVisible, restored);
    const timer = scheduleVisibleInterval(onVisible, FEED_VISIBLE_MS);
    return () => {
      cancelled = true;
      stopInitialOnVisible();
      timer();
    };
  }, []);

  return state;
}

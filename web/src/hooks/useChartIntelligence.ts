import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChartIntelligencePayload } from '../types/chartIntelligence';
import {
  memorySnapshot, readVerifiedSnapshot, shouldReplaceSnapshot, snapshotKey,
  type SnapshotExpectation, type SnapshotViewState, type VerifiedSnapshot,
  VERIFIED_VIEW_METHOD_VERSION, verifySnapshot, writeVerifiedSnapshot,
} from '../lib/verifiedSnapshot';
import { formatSnapshotStatus, snapshotFreshness } from '../lib/snapshotFreshness';

const legacyCache = new Map<string, { at: number; data: ChartIntelligencePayload }>();
const legacyInflight = new Map<string, Promise<ChartIntelligencePayload>>();
const inflight = new Map<string, Promise<SnapshotNetworkResult>>();
const failedUntil = new Map<string, number>();
const LEGACY_STALE_MS = 30 * 60 * 1000;
const REQUEST_TIMEOUT_MS = 15_000;

interface Options {
  scope: 'market' | 'asset'; symbol?: string; market?: string;
  timeframe?: 'daily' | 'weekly'; horizon?: 1 | 5 | 20; enabled?: boolean;
}

interface SnapshotNetworkResult {
  snapshot: VerifiedSnapshot<ChartIntelligencePayload> | null;
  notModified: boolean;
}

interface SnapshotView {
  key: string | null;
  snapshot: VerifiedSnapshot<ChartIntelligencePayload> | null;
  state: SnapshotViewState;
  error: string | null;
}

function baseUrl() {
  return (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? null;
}

function legacyEndpoint(options: Options) {
  const base = baseUrl();
  if (!base) return null;
  const params = new URLSearchParams({
    scope: options.scope, timeframe: options.timeframe ?? 'daily',
  });
  if (options.symbol) params.set('symbol', options.symbol);
  if (options.market) params.set('market', options.market);
  return `${base}/api/argus/chart-intelligence?${params}`;
}

function marketExpectation(options: Options): SnapshotExpectation | null {
  if (options.scope !== 'market' || (options.timeframe ?? 'daily') !== 'daily') return null;
  return {
    kind: 'market-chart',
    instrument: (options.symbol ?? '1321').toUpperCase(),
    horizon: `${options.horizon ?? 5}D`,
    methodVersion: VERIFIED_VIEW_METHOD_VERSION,
  };
}

function verifiedEndpoint(options: Options, expectation: SnapshotExpectation | null) {
  const base = baseUrl();
  if (!base || !expectation) return null;
  const params = new URLSearchParams({
    scope: 'market', timeframe: 'daily', symbol: expectation.instrument,
    horizon: expectation.horizon, snapshot: 'verified',
  });
  return `${base}/api/argus/chart-intelligence?${params}`;
}

function matchesInstrument(data: ChartIntelligencePayload, expectedSymbol?: string) {
  if (!expectedSymbol) return true;
  const actual = data.instrumentMetadata?.symbol ?? data.symbol;
  return actual?.toUpperCase() === expectedSymbol.toUpperCase();
}

async function loadLegacy(url: string, expectedSymbol?: string) {
  if ((failedUntil.get(url) ?? 0) > Date.now()) throw new Error('再試行待機中');
  const current = legacyCache.get(url);
  if (current && Date.now() - current.at < LEGACY_STALE_MS &&
      matchesInstrument(current.data, expectedSymbol)) return current.data;
  if (current && !matchesInstrument(current.data, expectedSymbol)) legacyCache.delete(url);
  const pending = legacyInflight.get(url);
  if (pending) return pending;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort('timeout'), REQUEST_TIMEOUT_MS);
  const request = fetch(url, {
    method: 'GET', cache: 'no-store', headers: { Accept: 'application/json' },
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json() as ChartIntelligencePayload;
    if (!matchesInstrument(data, expectedSymbol)) throw new Error('instrument_mismatch');
    legacyCache.set(url, { at: Date.now(), data });
    return data;
  }).catch((error: unknown) => {
    failedUntil.set(url, Date.now() + 30_000);
    throw error;
  }).finally(() => {
    window.clearTimeout(timer); legacyInflight.delete(url);
  });
  legacyInflight.set(url, request);
  return request;
}

function performanceMark(name: string) {
  try { performance.mark(`argus-snapshot:${name}`); } catch { /* diagnostics only */ }
}

function fetchVerifiedSnapshot(
  url: string, expectation: SnapshotExpectation,
  current: VerifiedSnapshot<ChartIntelligencePayload> | null,
) {
  const existing = inflight.get(url);
  if (existing) return existing;
  if ((failedUntil.get(url) ?? 0) > Date.now()) {
    return Promise.reject(new Error('再試行待機中'));
  }
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort('timeout'), REQUEST_TIMEOUT_MS);
  performanceMark('network-revalidation-start');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (current) headers['If-None-Match'] = `"${current.snapshotId}"`;
  const request = fetch(url, {
    method: 'GET', cache: 'no-store', headers, signal: controller.signal,
  }).then(async (response): Promise<SnapshotNetworkResult> => {
    performanceMark('network-response');
    if (response.status === 304) return { snapshot: null, notModified: true };
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const candidate: unknown = await response.json();
    const validation = await verifySnapshot(candidate, expectation);
    performanceMark('snapshot-validation-complete');
    if (!validation.ok) throw new Error(`snapshot_${validation.reason}`);
    return { snapshot: validation.snapshot, notModified: false };
  }).catch((error: unknown) => {
    failedUntil.set(url, Date.now() + 30_000);
    throw error;
  }).finally(() => {
    window.clearTimeout(timer); inflight.delete(url);
  });
  inflight.set(url, request);
  return request;
}

function withAbort<T>(promise: Promise<T>, signal: AbortSignal) {
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(new DOMException('Request superseded', 'AbortError'));
    if (signal.aborted) { abort(); return; }
    signal.addEventListener('abort', abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}

export function useChartIntelligence(options: Options) {
  const expectation = useMemo(() => marketExpectation(options), [
    options.scope, options.symbol, options.timeframe, options.horizon,
  ]);
  const verifiedUrl = useMemo(() => verifiedEndpoint(options, expectation), [
    options.scope, options.symbol, options.market, options.timeframe,
    options.horizon, expectation,
  ]);
  const legacyUrl = useMemo(() => legacyEndpoint(options), [
    options.scope, options.symbol, options.market, options.timeframe,
  ]);
  const expectedKey = expectation ? snapshotKey(expectation) : legacyUrl;
  const initial = expectation ? memorySnapshot(expectation) : null;
  const [view, setView] = useState<SnapshotView>({
    key: initial ? expectedKey : null,
    snapshot: initial,
    state: initial ? 'CACHE_READY_REVALIDATING' : 'NO_CACHE_LOADING',
    error: null,
  });
  const [legacyData, setLegacyData] = useState<ChartIntelligencePayload | null>(
    legacyUrl ? legacyCache.get(legacyUrl)?.data ?? null : null);
  const [legacyKey, setLegacyKey] = useState<string | null>(
    legacyData ? legacyUrl : null);
  const [legacyError, setLegacyError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const sequence = useRef(0);
  const [loaderVisible, setLoaderVisible] = useState(false);
  const [slowInitial, setSlowInitial] = useState(false);

  useEffect(() => {
    const loading = expectation
      ? ['NO_CACHE_LOADING', 'CACHE_READY_REVALIDATING'].includes(view.state)
      : !legacyData;
    if (!loading) { setLoaderVisible(false); setSlowInitial(false); return; }
    const loaderTimer = window.setTimeout(() => setLoaderVisible(true), 225);
    const slowTimer = window.setTimeout(() => setSlowInitial(true), 5_000);
    return () => {
      window.clearTimeout(loaderTimer); window.clearTimeout(slowTimer);
      setLoaderVisible(false); setSlowInitial(false);
    };
  }, [expectation, legacyData, view.state, expectedKey]);

  useEffect(() => {
    if (options.enabled === false || document.visibilityState === 'hidden') return;
    if (!expectation || !verifiedUrl) return;
    const requestSequence = ++sequence.current;
    const controller = new AbortController();
    const key = snapshotKey(expectation);
    const memoryCached = memorySnapshot(expectation);
    setView({
      key: memoryCached ? key : null, snapshot: memoryCached,
      state: memoryCached ? 'CACHE_READY_REVALIDATING' : 'NO_CACHE_LOADING',
      error: null,
    });
    performanceMark('navigation-start');
    const cachePromise = readVerifiedSnapshot(expectation);
    // Cache restore and revalidation begin in the same effect. The network
    // result is deliberately held until the cache lookup has had first paint.
    const networkPromise = withAbort(
      fetchVerifiedSnapshot(verifiedUrl, expectation, memoryCached),
      controller.signal);
    // Attach both handlers immediately. Otherwise a superseded request can
    // reject while IndexedDB is still being read and briefly surface as an
    // unhandled AbortError before this task reaches its network await.
    const networkOutcomePromise = networkPromise.then(
      (value) => ({ ok: true as const, value }),
      (reason: unknown) => ({ ok: false as const, reason }),
    );
    void (async () => {
      let cached = await cachePromise;
      if (controller.signal.aborted || requestSequence !== sequence.current) return;
      if (cached) {
        setView({
          key, snapshot: cached, state: 'CACHE_READY_REVALIDATING', error: null,
        });
        performanceMark('first-cached-chart-render');
      }
      try {
        const networkOutcome = await networkOutcomePromise;
        if (!networkOutcome.ok) throw networkOutcome.reason;
        const network = networkOutcome.value;
        if (controller.signal.aborted || requestSequence !== sequence.current) return;
        if (network.notModified) {
          const freshness = snapshotFreshness(cached, Date.now(), false);
          setView({
            key, snapshot: cached,
            state: freshness === 'stale_usable' || freshness === 'expired'
              ? 'STALE_FALLBACK' : 'CURRENT_READY',
            error: null,
          });
          return;
        }
        if (!network.snapshot) throw new Error('snapshot_missing');
        if (cached && !shouldReplaceSnapshot(cached, network.snapshot)) {
          setView({ key, snapshot: cached, state: 'CURRENT_READY', error: null });
          return;
        }
        const published = await writeVerifiedSnapshot(
          network.snapshot, expectation, cached);
        if (controller.signal.aborted || requestSequence !== sequence.current) return;
        if (!published) throw new Error('snapshot_readback_failed');
        cached = published;
        setView({ key, snapshot: published, state: 'CURRENT_READY', error: null });
        performanceMark('atomic-swap-complete');
      } catch (reason) {
        if (controller.signal.aborted || requestSequence !== sequence.current) return;
        const message = reason instanceof Error ? reason.message : '取得失敗';
        const freshness = snapshotFreshness(cached);
        setView({
          key: cached ? key : null, snapshot: cached,
          state: cached
            ? freshness === 'expired' ? 'STALE_FALLBACK' : 'ERROR_WITH_CACHE'
            : 'ERROR_WITHOUT_CACHE',
          error: message,
        });
      }
    })();
    return () => controller.abort('view_changed');
  }, [verifiedUrl, options.enabled, refreshToken, expectation]);

  useEffect(() => {
    if (options.enabled === false || expectation || !legacyUrl) return;
    let cancelled = false;
    const run = () => {
      if (document.visibilityState === 'hidden') return;
      void loadLegacy(legacyUrl, options.symbol).then((value) => {
        if (!cancelled) {
          setLegacyData(value); setLegacyKey(legacyUrl); setLegacyError(null);
        }
      }).catch((reason: unknown) => {
        if (!cancelled) setLegacyError(
          reason instanceof Error ? reason.message : '取得失敗');
      });
    };
    run();
    return () => { cancelled = true; };
  }, [legacyUrl, options.enabled, options.symbol, expectation, refreshToken]);

  useEffect(() => {
    const visible = () => {
      if (document.visibilityState === 'visible') setRefreshToken((value) => value + 1);
    };
    document.addEventListener('visibilitychange', visible);
    return () => document.removeEventListener('visibilitychange', visible);
  }, []);

  if (!expectation) {
    const data = legacyKey === legacyUrl ? legacyData : null;
    return {
      data, loading: !data, error: legacyError, snapshotState:
        data ? 'CURRENT_READY' as const : 'NO_CACHE_LOADING' as const,
      statusText: data ? '更新済' : '初回データを準備中',
      loaderVisible, slowInitial, snapshotId: null,
    };
  }
  const matching = view.key === expectedKey ? view.snapshot : null;
  const effectiveState = view.key === expectedKey
    ? view.state
    : 'NO_CACHE_LOADING';
  const loading = effectiveState === 'NO_CACHE_LOADING' ||
    effectiveState === 'CACHE_READY_REVALIDATING';
  return {
    data: matching?.payload ?? null,
    loading,
    error: view.key === expectedKey ? view.error : null,
    snapshotState: effectiveState,
    statusText: formatSnapshotStatus(effectiveState, matching),
    loaderVisible, slowInitial,
    snapshotId: matching?.snapshotId ?? null,
  };
}

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChartIntelligencePayload } from '../types/chartIntelligence';
import {
  memorySnapshot, readVerifiedSnapshot, shouldReplaceSnapshot, snapshotKey,
  type SnapshotExpectation, type SnapshotViewState, type VerifiedSnapshot,
  VERIFIED_VIEW_METHOD_VERSION, verifySnapshot, writeVerifiedSnapshot,
} from '../lib/verifiedSnapshot';
import { formatSnapshotStatus, snapshotFreshness } from '../lib/snapshotFreshness';
import {
  DEFAULT_MARKET_INSTRUMENT, isVerifiedMarketInstrument,
} from '../domain/marketInstruments';
import {
  ASSET_CHART_METHOD_VERSION, assetChartRequestGate, boundedRetryAt,
  assetChartUiTransition, parseRetryAfter, readAssetChart, writeAssetChart,
  type AssetChartIdentity, type AssetChartViewState,
} from '../lib/assetChartCache';

const legacyCache = new Map<string, { at: number; data: ChartIntelligencePayload }>();
const legacyInflight = new Map<string, Promise<ChartIntelligencePayload>>();
const inflight = new Map<string, Promise<SnapshotNetworkResult>>();
const failedUntil = new Map<string, number>();
const assetFailureCount = new Map<string, number>();
const REQUEST_TIMEOUT_MS = 15_000;

export interface ChartIntelligenceOptions {
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

class AssetChartRequestError extends Error {
  status: number | null;
  retryAt: number | null;
  errorClass: 'rate_limited' | 'timeout' | 'aborted' | 'http' | 'invalid_json'
    | 'instrument_mismatch' | 'retry_wait' | 'network' | 'expected_skip';

  constructor(message: string, options: {
    status?: number | null; retryAt?: number | null;
    errorClass: AssetChartRequestError['errorClass'];
  }) {
    super(message);
    this.name = 'AssetChartRequestError';
    this.status = options.status ?? null;
    this.retryAt = options.retryAt ?? null;
    this.errorClass = options.errorClass;
  }
}

function baseUrl() {
  return (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? null;
}

function legacyEndpoint(options: ChartIntelligenceOptions) {
  const base = baseUrl();
  if (!base) return null;
  const params = new URLSearchParams({
    scope: options.scope, timeframe: options.timeframe ?? 'daily',
  });
  if (options.symbol) params.set('symbol', options.symbol);
  if (options.market) params.set('market', options.market);
  return `${base}/api/argus/chart-intelligence?${params}`;
}

export function marketExpectation(
  options: ChartIntelligenceOptions,
): SnapshotExpectation | null {
  const symbol = options.symbol
    ?? (options.scope === 'market' ? DEFAULT_MARKET_INSTRUMENT.JP : null);
  if (!isVerifiedMarketInstrument(symbol, options.timeframe ?? 'daily')) return null;
  return {
    kind: 'market-chart',
    instrument: symbol!.toUpperCase(),
    horizon: `${options.horizon ?? 5}D`,
    methodVersion: VERIFIED_VIEW_METHOD_VERSION,
  };
}

function verifiedEndpoint(options: ChartIntelligenceOptions, expectation: SnapshotExpectation | null) {
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
  const blockedUntil = failedUntil.get(url) ?? 0;
  if (blockedUntil > Date.now()) {
    throw new AssetChartRequestError('再試行待機中', {
      errorClass: 'retry_wait', retryAt: blockedUntil,
    });
  }
  const pending = legacyInflight.get(url);
  if (pending) return pending;
  const request = assetChartRequestGate.enqueue(async () => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort('timeout'), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        method: 'GET', cache: 'no-store', headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response.ok) {
        const count = (assetFailureCount.get(url) ?? 0) + 1;
        assetFailureCount.set(url, count);
        const retryAt = response.status === 429
          ? parseRetryAfter(response.headers.get('Retry-After')) ?? boundedRetryAt(count - 1)
          : boundedRetryAt(0);
        failedUntil.set(url, retryAt);
        throw new AssetChartRequestError(`HTTP ${response.status}`, {
          status: response.status, retryAt,
          errorClass: response.status === 429 ? 'rate_limited' : 'http',
        });
      }
      let data: ChartIntelligencePayload;
      try {
        data = await response.json() as ChartIntelligencePayload;
      } catch {
        throw new AssetChartRequestError('invalid_json', {
          errorClass: 'invalid_json', retryAt: boundedRetryAt(0),
        });
      }
      if (data.status === 'expected_skip') {
        const skipReason = (data as ChartIntelligencePayload & {
          stateUpdate?: { reason?: string | null };
        }).stateUpdate?.reason;
        throw new AssetChartRequestError(
          skipReason === 'price_cache_unavailable'
            ? '価格キャッシュの更新待ち' : '次回データ更新待ち',
          { errorClass: 'expected_skip' },
        );
      }
      if (!matchesInstrument(data, expectedSymbol)) {
        throw new AssetChartRequestError('instrument_mismatch', {
          errorClass: 'instrument_mismatch', retryAt: boundedRetryAt(0),
        });
      }
      legacyCache.set(url, { at: Date.now(), data });
      assetFailureCount.delete(url);
      failedUntil.delete(url);
      return data;
    } catch (reason) {
      if (reason instanceof AssetChartRequestError) throw reason;
      const aborted = controller.signal.aborted
        || (reason instanceof DOMException && reason.name === 'AbortError');
      const timedOut = controller.signal.aborted
        && controller.signal.reason === 'timeout';
      const retryAt = boundedRetryAt(0);
      failedUntil.set(url, retryAt);
      throw new AssetChartRequestError(
        timedOut ? 'timeout' : aborted ? 'aborted' : 'network_error', {
        errorClass: timedOut ? 'timeout' : aborted ? 'aborted' : 'network',
        retryAt,
      });
    } finally {
      window.clearTimeout(timer);
    }
  }).finally(() => legacyInflight.delete(url));
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

export function useChartIntelligence(options: ChartIntelligenceOptions) {
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
  const [legacyState, setLegacyState] = useState<AssetChartViewState>(
    legacyData ? 'CACHE_READY_REVALIDATING' : 'NO_CACHE_LOADING');
  const [legacyError, setLegacyError] = useState<AssetChartRequestError | null>(null);
  const [legacyRetryAt, setLegacyRetryAt] = useState<number | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const sequence = useRef(0);
  const visibilityBlocked = useRef(false);
  const [loaderVisible, setLoaderVisible] = useState(false);
  const [slowInitial, setSlowInitial] = useState(false);

  useEffect(() => {
    const loading = expectation
      ? ['NO_CACHE_LOADING', 'CACHE_READY_REVALIDATING'].includes(view.state)
      : ['NO_CACHE_LOADING', 'CACHE_READY_REVALIDATING'].includes(legacyState);
    if (!loading) { setLoaderVisible(false); setSlowInitial(false); return; }
    const loaderTimer = window.setTimeout(() => setLoaderVisible(true), 225);
    const slowTimer = window.setTimeout(() => setSlowInitial(true), 5_000);
    return () => {
      window.clearTimeout(loaderTimer); window.clearTimeout(slowTimer);
      setLoaderVisible(false); setSlowInitial(false);
    };
  }, [expectation, legacyState, view.state, expectedKey]);

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
          // Keep the requested identity even without cache so
          // ERROR_WITHOUT_CACHE (and its retry control) is observable. A null
          // key made the return path reinterpret the error as perpetual loading.
          key, snapshot: cached,
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
    if (document.visibilityState === 'hidden') {
      visibilityBlocked.current = true;
      return;
    }
    const requestSequence = ++sequence.current;
    let cancelled = false;
    const identity: AssetChartIdentity = {
      market: options.market ?? (options.symbol?.match(/^\d/) ? 'JP' : 'US'),
      symbol: options.symbol ?? '',
      timeframe: options.timeframe ?? 'daily',
      methodVersion: ASSET_CHART_METHOD_VERSION,
    };
    let cached = legacyCache.get(legacyUrl)?.data ?? null;
    setLegacyKey(legacyUrl);
    setLegacyData(cached);
    setLegacyState(cached ? 'CACHE_READY_REVALIDATING' : 'NO_CACHE_LOADING');
    setLegacyError(null);
    setLegacyRetryAt(null);
    void (async () => {
      const restored = await readAssetChart(identity);
      if (restored && matchesInstrument(restored.payload, options.symbol)) {
        cached = restored.payload;
        legacyCache.set(legacyUrl, { at: Date.parse(restored.generatedAt), data: cached });
        if (!cancelled && requestSequence === sequence.current) {
          setLegacyData(cached);
          setLegacyKey(legacyUrl);
          setLegacyState('CACHE_READY_REVALIDATING');
        }
      }
      try {
        const value = await loadLegacy(legacyUrl, options.symbol);
        const published = await writeAssetChart(identity, value);
        if (cancelled || requestSequence !== sequence.current) return;
        const ready = assetChartUiTransition({
          state: legacyState,
          errorClass: legacyError?.errorClass ?? null,
          retryAt: legacyRetryAt,
        }, { type: 'http_200' });
        setLegacyData(published?.payload ?? value);
        setLegacyKey(legacyUrl);
        setLegacyState(ready.state);
        setLegacyError(null);
        setLegacyRetryAt(ready.retryAt);
      } catch (reason) {
        if (cancelled || requestSequence !== sequence.current) return;
        const error = reason instanceof AssetChartRequestError
          ? reason : new AssetChartRequestError('取得失敗', { errorClass: 'network' });
        const hasCache = !!cached;
        const failed = assetChartUiTransition({
          state: legacyState,
          errorClass: legacyError?.errorClass ?? null,
          retryAt: legacyRetryAt,
        }, {
          type: 'failure', hasCache, errorClass: error.errorClass,
          retryAt: error.retryAt,
        });
        setLegacyData(cached);
        setLegacyKey(legacyUrl);
        setLegacyState(failed.state);
        setLegacyError(error);
        setLegacyRetryAt(failed.retryAt);
      }
    })();
    return () => { cancelled = true; };
  }, [legacyUrl, options.enabled, options.symbol, options.market,
      options.timeframe, expectation, refreshToken]);

  useEffect(() => {
    const visible = () => {
      if (document.visibilityState !== 'visible') return;
      // Verified market views retain SWR-on-return. Asset charts only resume
      // when a request was actually blocked by a hidden document; a normal
      // visibilitychange never causes an extra legacy request.
      if (expectation || visibilityBlocked.current) {
        visibilityBlocked.current = false;
        setRefreshToken((value) => value + 1);
      }
    };
    document.addEventListener('visibilitychange', visible);
    return () => document.removeEventListener('visibilitychange', visible);
  }, [expectation]);

  if (!expectation) {
    const data = legacyKey === legacyUrl ? legacyData : null;
    const effectiveLegacyState: AssetChartViewState = legacyKey === legacyUrl
      ? legacyState : 'NO_CACHE_LOADING';
    const retry = () => {
      if (legacyUrl) failedUntil.delete(legacyUrl);
      if (legacyUrl) assetFailureCount.delete(legacyUrl);
      setRefreshToken((value) => value + 1);
    };
    const time = data?.asOf || data?.periodEnd;
    const parsedTime = time ? Date.parse(time) : Number.NaN;
    const cachedTime = Number.isFinite(parsedTime)
      ? new Intl.DateTimeFormat('ja-JP', {
        timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false,
      }).format(new Date(parsedTime))
      : null;
    const statusText = effectiveLegacyState === 'CURRENT_READY' ? '更新済'
      : effectiveLegacyState === 'CACHE_READY_REVALIDATING'
        ? `前回${cachedTime ? ` ${cachedTime}` : ''} · 更新中`
      : effectiveLegacyState === 'RATE_LIMITED_WITH_CACHE'
        ? `前回${cachedTime ? ` ${cachedTime}` : ''} · 更新制限中`
      : effectiveLegacyState === 'RATE_LIMITED_WITHOUT_CACHE' ? 'チャート取得制限中'
      : effectiveLegacyState === 'ERROR_WITH_CACHE'
        ? `前回${cachedTime ? ` ${cachedTime}` : ''} · 更新失敗`
      : effectiveLegacyState === 'ERROR_WITHOUT_CACHE' ? 'チャート取得失敗'
      : '初回データを準備中';
    return {
      data,
      loading: effectiveLegacyState === 'NO_CACHE_LOADING'
        || effectiveLegacyState === 'CACHE_READY_REVALIDATING',
      error: legacyKey === legacyUrl ? legacyError?.message ?? null : null,
      errorClass: legacyKey === legacyUrl ? legacyError?.errorClass ?? null : null,
      retryAt: legacyKey === legacyUrl ? legacyRetryAt : null,
      snapshotState: effectiveLegacyState,
      statusText,
      loaderVisible, slowInitial, snapshotId: null,
      retry,
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
    errorClass: null,
    retryAt: null,
    snapshotId: matching?.snapshotId ?? null,
    retry: () => {
      if (verifiedUrl) failedUntil.delete(verifiedUrl);
      setRefreshToken((value) => value + 1);
    },
  };
}

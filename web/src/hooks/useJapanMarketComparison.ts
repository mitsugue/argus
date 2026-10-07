import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../lib/pollingPolicy';
import { useEffect, useState } from 'react';
import type { ForecastTrackRecord, JapanMarketComparison } from '../types/japanMarketComparison';
import { validForecastTrackRecord, validJapanMarketComparison } from '../lib/japanMarketComparison';
import { validLevelMap, type LevelMapState } from '../lib/levelMap';
import { comparisonReply, retainComparisonReply, comparisonReadInterval, type ComparisonReply } from '../lib/japanMarketComparisonReply';
import { validResearchChart } from '../lib/researchChart';

type State = { document: JapanMarketComparison | null; loading: boolean; error: boolean;
  reason: string | null; lastSuccessfulAcquisitionAt: string | null; levelMap?: LevelMapState | null; levelMapError?: boolean };
// levelMap (2026-10-04): the morning map rides the five-session reply.
type Reply = ComparisonReply;
const memory = new Map<string, Reply>();
const flights = new Map<string, Promise<Reply>>();
const empty = (): State => ({ document: null, loading: true, error: false, reason: null, lastSuccessfulAcquisitionAt: null });
const storageKey = (key: string) => `argus.jp-market-comparison.v1:${key}`;
const MAX_SAVED_BYTES = 131072;

function previous(key: string, horizon: number): Reply | undefined {
  if (memory.has(key)) return memory.get(key);
  try {
    const raw = localStorage.getItem(storageKey(key));
    if (!raw || raw.length > MAX_SAVED_BYTES) return;
    const value = JSON.parse(raw);
    if (!validJapanMarketComparison(value.document, horizon)
      && !(value.document === null && validLevelMap(value.levelMap) && validResearchChart(value.levelMap.chart))) return;
    const result: Reply = { document: value.document, reason: null,
      lastSuccessfulAcquisitionAt: typeof value.lastSuccessfulAcquisitionAt === 'string'
        && Number.isFinite(Date.parse(value.lastSuccessfulAcquisitionAt)) ? value.lastSuccessfulAcquisitionAt : null,
      levelMap: validLevelMap(value.levelMap) ? value.levelMap : null };
    memory.set(key, result); return result;
  } catch { return; }
}

function remember(key: string, result: Reply) {
  memory.set(key, result);
  try {
    const raw = JSON.stringify(result);
    if (new TextEncoder().encode(raw).length <= MAX_SAVED_BYTES) localStorage.setItem(storageKey(key), raw);
  } catch { /* The current chart remains usable when the public cache cannot be saved. */ }
}

async function load(base: string, horizon: number): Promise<Reply> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${base}/api/argus/index-chart?index=N225&comparison=1&horizon=${horizon}`,
      { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    return comparisonReply(body, horizon);
  } finally { window.clearTimeout(timer); }
}

export function useJapanMarketComparison(horizon: number) {
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? '';
  const key = `${base}:${horizon}`;
  const [snapshot, setSnapshot] = useState<{ key: string; state: State }>({ key, state: empty() });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    let active = false;
    let retryTimer: number | undefined;
    const publish = (state: State) => { if (!cancelled) setSnapshot({ key, state }); };
    const refresh = async () => {
      if (cancelled || active) return;
      active = true;
      window.clearTimeout(retryTimer);
      const cached = previous(key, horizon);
      publish({ ...empty(), ...cached, loading: true });
      try {
        if (!base) throw new Error('backend_url_missing');
        if (!flights.has(key)) flights.set(key, load(base, horizon).finally(() => flights.delete(key)));
        const result = await flights.get(key)!;
        const retained = retainComparisonReply(result, cached);
        if (result.document || result.levelMap) remember(key, retained);
        publish({ ...retained, loading: false, error: !result.document, levelMapError: !result.levelMap });
        if (!result.document && !cancelled) retryTimer = window.setTimeout(visible, 30_000);
      } catch {
        publish({ ...empty(), ...memory.get(key), loading: false, error: true, levelMapError: true, reason: 'refresh_failed' });
        if (!cancelled) retryTimer = window.setTimeout(visible, 30_000);
      } finally { active = false; }
    };
    const visible = () => { if (document.visibilityState === 'visible') void refresh(); };
    void refresh();
    const timer = scheduleVisibleInterval(visible, () => comparisonReadInterval(memory.get(key), Date.now()));
    const stopInitialVisible = subscribeInitialVisibleRead(visible);
    return () => { cancelled = true; window.clearTimeout(retryTimer); timer();
      stopInitialVisible(); };
  }, [base, key, horizon, retry]);
  return { ...(snapshot.key === key ? snapshot.state : { ...empty(), ...memory.get(key) }),
    retry: () => setRetry(value => value + 1) };
}

// Record of the forecasts actually issued (shared by every chart on the page).
// Until the backend serves it the line simply stays absent.
const TRACK_RECORD_TTL_MS = 10 * 60_000;
let trackRecord: { value: ForecastTrackRecord | null; at: number } | null = null;
let trackRecordFlight: Promise<ForecastTrackRecord | null> | null = null;

async function loadTrackRecord(base: string): Promise<ForecastTrackRecord | null> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${base}/api/argus/market-brief?trackRecord=1`, { cache: 'no-store', signal: controller.signal });
    if (!response.ok) return null;
    const body = await response.json();
    return validForecastTrackRecord(body?.trackRecord) ? body.trackRecord : null;
  } catch { return null; } finally { window.clearTimeout(timer); }
}

export function useForecastTrackRecord(): ForecastTrackRecord | null {
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? '';
  const [value, setValue] = useState<ForecastTrackRecord | null>(trackRecord?.value ?? null);
  useEffect(() => {
    let cancelled = false;
    if (!base || (trackRecord && Date.now() - trackRecord.at < TRACK_RECORD_TTL_MS)) return;
    trackRecordFlight ??= loadTrackRecord(base).then(result => {
      trackRecord = { value: result, at: Date.now() }; return result;
    }).finally(() => { trackRecordFlight = null; });
    void trackRecordFlight.then(result => { if (!cancelled) setValue(result); });
    return () => { cancelled = true; };
  }, [base]);
  return value;
}

// Delayed intraday Nikkei quote (owner request 2026-10-02). Display only.
export interface NikkeiLiveQuote { price: number; previousClose: number | null; changePct: number | null;
  tradedAt: string; receivedAt?: string; delaySeconds: number; sessionOpen: boolean; realtime: boolean }
const liveValid = (q: unknown): q is NikkeiLiveQuote => {
  const v = q as NikkeiLiveQuote;
  return !!v && typeof v.price === 'number' && Number.isFinite(v.price) && v.price > 0
    && typeof v.tradedAt === 'string' && Number.isFinite(Date.parse(v.tradedAt))
    && typeof v.delaySeconds === 'number' && v.delaySeconds >= 0 && typeof v.sessionOpen === 'boolean'
    && (v.realtime === false || v.realtime === true && (q as { source?: unknown }).source === '立花証券' && v.delaySeconds <= 15 && typeof v.receivedAt === 'string' && Number.isFinite(Date.parse(v.receivedAt))) && (v.changePct === null || Number.isFinite(v.changePct));
};
export interface NikkeiLive { quote: NikkeiLiveQuote | null; futures: NikkeiLiveQuote | null }
// The CME future read outside the Tokyo session (owner check 2026-10-03).
const futuresValid = (q: unknown): q is NikkeiLiveQuote =>
  liveValid(q) && (q as { symbol?: unknown }).symbol === 'NKD=F';
export function useNikkeiLive(): NikkeiLive {
  const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? '';
  const [quote, setQuote] = useState<NikkeiLiveQuote | null>(null);
  const [futures, setFutures] = useState<NikkeiLiveQuote | null>(null);
  useEffect(() => {
    if (!base) return;
    let cancelled = false;
    let liveCadence = false;
    let lastRead = 0;
    let active = false;
    const load = async () => {
      if (document.visibilityState !== 'visible' || active) return;
      active = true;
      lastRead = Date.now();
      try {
        const response = await fetch(`${base}/api/argus/index-chart?index=N225&live=1`, { cache: 'no-store' });
        if (!response.ok) return;
        const body = await response.json();
        if (cancelled || body?.actionAuthority !== false) return;
        liveCadence = liveValid(body?.quote) && body.quote.realtime && body.quote.sessionOpen;
        if (liveValid(body?.quote)) setQuote(body.quote);
        if (futuresValid(body?.overnightFutures)) setFutures(body.overnightFutures);
      } catch { liveCadence = false; /* keep the last value; the close remains the fallback */ }
      finally { active = false; }
    };
    void load();
    const ageQuote = () => {
      setQuote(current => {
        if (!current?.realtime) return current;
        const tradeAge = Date.now() - Date.parse(current.tradedAt);
        const receiptAge = Date.now() - Date.parse(current.receivedAt ?? '');
        return tradeAge >= 0 && tradeAge <= 15_000 && receiptAge >= 0 && receiptAge <= 15_000 ? current : null;
      });
    };
    const timer = scheduleVisibleInterval(() => {
      ageQuote();
      if (Date.now() - lastRead >= (liveCadence ? 10_000 : 60_000)) void load();
    }, 10_000);
    // Age immediately after a suspended app resumes, without a network read.
    const onVisibleAge = () => { if (document.visibilityState === 'visible') ageQuote(); };
    document.addEventListener('visibilitychange', onVisibleAge);
    const stopInitialLoad = subscribeInitialVisibleRead(load);
    return () => { cancelled = true; timer(); stopInitialLoad();
      document.removeEventListener('visibilitychange', onVisibleAge); };
  }, [base]);
  return { quote, futures };
}

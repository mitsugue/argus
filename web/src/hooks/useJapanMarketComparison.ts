import { useEffect, useState } from 'react';
import type { JapanMarketComparison } from '../types/japanMarketComparison';
import { validJapanMarketComparison } from '../lib/japanMarketComparison';

type State = { document: JapanMarketComparison | null; loading: boolean; error: boolean;
  reason: string | null; lastSuccessfulAcquisitionAt: string | null };
type Reply = { document: JapanMarketComparison | null; reason: string | null; lastSuccessfulAcquisitionAt: string | null };
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
    if (!validJapanMarketComparison(value.document, horizon)) return;
    const result: Reply = { document: value.document, reason: null,
      lastSuccessfulAcquisitionAt: typeof value.lastSuccessfulAcquisitionAt === 'string'
        && Number.isFinite(Date.parse(value.lastSuccessfulAcquisitionAt)) ? value.lastSuccessfulAcquisitionAt : null };
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
    if (body.status === 'unavailable' && body.comparison === null) return {
      document: null, reason: typeof body.reason === 'string' ? body.reason : 'unavailable',
      lastSuccessfulAcquisitionAt: body.lastSuccessfulAcquisitionAt ?? null };
    if (body.status !== 'available' || body.actionAuthority !== false || body.automaticAiCalls !== 0
      || !validJapanMarketComparison(body.comparison, horizon)) throw new Error('invalid_comparison_response');
    return { document: body.comparison, reason: null, lastSuccessfulAcquisitionAt: body.lastSuccessfulAcquisitionAt ?? null };
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
        if (result.document) remember(key, result);
        publish({ ...(result.document ? result : cached ?? result), reason: result.reason,
          loading: false, error: !result.document });
        if (!result.document && !cancelled) retryTimer = window.setTimeout(visible, 30_000);
      } catch {
        publish({ ...empty(), ...memory.get(key), loading: false, error: true, reason: 'refresh_failed' });
        if (!cancelled) retryTimer = window.setTimeout(visible, 30_000);
      } finally { active = false; }
    };
    const visible = () => { if (document.visibilityState === 'visible') void refresh(); };
    void refresh();
    const timer = window.setInterval(visible, 5 * 60_000);
    document.addEventListener('visibilitychange', visible);
    return () => { cancelled = true; window.clearTimeout(retryTimer); window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visible); };
  }, [base, key, horizon, retry]);
  return { ...(snapshot.key === key ? snapshot.state : { ...empty(), ...memory.get(key) }),
    retry: () => setRetry(value => value + 1) };
}

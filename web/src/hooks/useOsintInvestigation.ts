import { useCallback, useEffect, useRef, useState } from 'react';
import { OWNER_SYNC_TOKEN_KEY } from '../lib/watchlistAutoSync';

// 2026-10-25 (owner): the stock page researches one name when the owner
// presses 「調べる」. The read is the cached public GET; the only write is the
// owner-key request below (never the admin credential).

export interface OsintVerifiedSource {
  titleJa: string; url?: string | null; sourceName?: string | null;
  publishedAt?: string | null; primaryEligible?: boolean; directness?: string | null;
}

export interface OsintInvestigation {
  symbol: string; asOf: string;
  ownerReadableSummaryJa?: string;
  verifiedSources: OsintVerifiedSource[];
  catalystVerdict?: { verdict: string; verdictJa: string; primaryCauseJa: string | null;
    ownerReadableJa?: string } | null;
}

export interface OsintOwnerRequest {
  running: boolean; requestedToday: boolean; remainingToday: number;
  completedAt?: string | null; complete?: boolean | null; failureReason?: string | null;
}

export type OsintRequestError =
  | 'no_key' | 'bad_key' | 'daily_limit' | 'already_today' | 'ai_stopped' | 'failed';

interface State { inv: OsintInvestigation | null; loading: boolean; error: boolean;
  owner: OsintOwnerRequest | null; requestError: OsintRequestError | null; }

const POLL_MS = 15_000;

const ownerKey = () => { try { return localStorage.getItem(OWNER_SYNC_TOKEN_KEY) || ''; } catch { return ''; } };

export function useOsintInvestigation(symbol: string, market: string, name?: string) {
  const [state, setState] = useState<State>({ inv: null, loading: true, error: false,
    owner: null, requestError: null });
  const backend = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
  const request = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    request.current?.abort();
    if (!backend) { setState((s) => ({ ...s, loading: false })); return; }
    const ctrl = new AbortController(); request.current = ctrl;
    setState((s) => ({ ...s, loading: true, error: false }));
    fetch(`${backend}/api/argus/osint/investigation?symbol=${encodeURIComponent(symbol)}`, { signal: AbortSignal.any([ctrl.signal, AbortSignal.timeout(12000)]) })
      .then((r) => { if (!r.ok) throw new Error('investigation_unavailable'); return r.json(); })
      .then((d) => { if (ctrl.signal.aborted) return; setState((s) => ({ ...s, inv: d.investigation ?? null,
        owner: d.ownerRequest ?? null, loading: false })); })
      .catch(() => { if (!ctrl.signal.aborted) setState((s) => ({ ...s, loading: false, error: true })); });
  }, [backend, symbol]);

  useEffect(() => {
    setState({ inv: null, loading: true, error: false, owner: null, requestError: null });
    load(); return () => request.current?.abort();
  }, [load]);

  const running = !!state.owner?.running;
  useEffect(() => {
    if (!running) return undefined;
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, load]);

  const research = useCallback(async () => {
    const key = ownerKey();
    if (!key) { setState((s) => ({ ...s, requestError: 'no_key' })); return; }
    if (!backend) { setState((s) => ({ ...s, requestError: 'failed' })); return; }
    setState((s) => ({ ...s, requestError: null }));
    try {
      const r = await fetch(`${backend}/api/argus/osint/research-request`, {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, market, name, ownerToken: key }), signal: AbortSignal.timeout(12000) });
      if (r.status === 401 || r.status === 403) { setState((s) => ({ ...s, requestError: 'bad_key' })); return; }
      const d = await r.json() as { status?: string } & Partial<OsintOwnerRequest>;
      const owner: OsintOwnerRequest = { running: !!d.running, requestedToday: !!d.requestedToday,
        remainingToday: d.remainingToday ?? 0, completedAt: d.completedAt ?? null, complete: d.complete ?? null,
        failureReason: d.failureReason ?? null };
      const failure = (['daily_limit', 'already_today', 'ai_stopped'] as const)
        .find((code) => code === d.status) ?? (d.status === 'started' || d.status === 'running' ? null : 'failed');
      setState((s) => ({ ...s, owner, requestError: failure }));
    } catch {
      setState((s) => ({ ...s, requestError: 'failed' }));
    }
  }, [backend, symbol, market, name]);

  return { ...state, reload: load, research };
}

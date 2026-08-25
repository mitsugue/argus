import { useSyncExternalStore } from 'react';
import { createSharedPollingStore } from '../lib/sharedPollingStore';

// Decision Evidence (v13.5.13) — canonical artifact references for the device
// SDA, served by /api/argus/decision-evidence. The payload carries verified
// marketTruth / predictionLedger / sho reference dicts per subject; the
// canonicalDecisionEvidence resolver validates and registers them before any
// SDA input may use them. This hook only transports the document.

const REFRESH_INTERVAL_MS = 120_000;   // matches the backend evidence TTL
const MAX_SYMBOLS_PER_REQUEST = 8;
const HEADLINE_SYMBOLS = ['1321', '1306', 'SPY', 'QQQ'] as const;

// v13.5.34 (review item A): document-level SHO MARKET VIEW. Display-only —
// the resolver never registers it as an SDA input; actionAuthority stays
// false by construction on the backend projection.
export interface ShoMarketView {
  schemaVersion: string;
  informationCutoff: string;
  projection: {
    families?: Record<string, {
      status?: string; conditionMet?: boolean | null;
      lineage?: string; validationStatus?: string;
    }>;
    reversal?: {
      downsideState?: string; reversalState?: string;
      validationStatus?: string;
    } | null;
    status?: string;
    actionAuthority?: boolean;
  } | null;
  sourceStatus: Record<string, string>;
  actionAuthority: boolean;
}

export interface DecisionEvidenceState {
  subjects: Record<string, unknown> | null;
  marketView: ShoMarketView | null;
  generatedAt: string | null;
  loading: boolean;
  error: string | null;
}

// The desired-symbols set is device-local (owner watchlist) and can change
// after mount; the poller reads the current set on every cycle. Headline
// subjects are always requested so the Today instruments can decide.
let desiredSymbols: string[] = [...HEADLINE_SYMBOLS];
let desiredRevision = 0;

export function requestDecisionEvidenceSymbols(symbols: readonly string[]): void {
  const merged: string[] = [...HEADLINE_SYMBOLS];
  for (const raw of symbols) {
    const sym = String(raw || '').toUpperCase();
    if (sym && !merged.includes(sym)) merged.push(sym);
    if (merged.length >= MAX_SYMBOLS_PER_REQUEST) break;
  }
  if (merged.join(',') !== desiredSymbols.join(',')) {
    desiredSymbols = merged;
    desiredRevision += 1;
  }
}

const decisionEvidenceStore = createSharedPollingStore<DecisionEvidenceState>(
  { subjects: null, marketView: null, generatedAt: null, loading: true, error: null },
  (setState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ subjects: null, marketView: null, generatedAt: null, loading: false, error: null });
      return () => {};
    }
    const base = backend.replace(/\/$/, '') + '/api/argus/decision-evidence';
    let cancelled = false;
    let fetchedRevision = -1;
    const controllers = new Set<AbortController>();

    async function fetchOnce(): Promise<void> {
      if (cancelled || document.hidden) return;
      const ctrl = new AbortController();
      controllers.add(ctrl);
      const timeout = window.setTimeout(() => ctrl.abort(), 12_000);
      const revision = desiredRevision;
      try {
        const url = `${base}?symbols=${encodeURIComponent(desiredSymbols.join(','))}`;
        const response = await fetch(url, { signal: ctrl.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (cancelled) return;
        const data = await response.json() as {
          schemaVersion?: string; generatedAt?: string;
          subjects?: Record<string, unknown>;
          marketView?: ShoMarketView;
        };
        if (data.schemaVersion !== 'argus-decision-evidence-v1'
            || typeof data.subjects !== 'object' || data.subjects === null) {
          throw new Error('decision_evidence_schema_mismatch');
        }
        fetchedRevision = revision;
        if (!cancelled) {
          const view = data.marketView;
          const marketView = view
            && view.schemaVersion === 'argus-sho-market-view-v1'
            && view.actionAuthority === false ? view : null;
          setState({ subjects: data.subjects, marketView,
            generatedAt: typeof data.generatedAt === 'string' ? data.generatedAt : null,
            loading: false, error: null });
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setState((current) => ({ ...current, loading: false,
            error: err instanceof Error ? err.message : String(err) }));
        }
      } finally {
        window.clearTimeout(timeout);
        controllers.delete(ctrl);
      }
    }

    void fetchOnce();
    const timer = window.setInterval(() => {
      // A symbol-set change is picked up on the next cycle; an unchanged set
      // simply refreshes within the backend TTL cadence.
      void fetchOnce();
    }, REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void fetchOnce(); };
    const revisionTimer = window.setInterval(() => {
      if (desiredRevision !== fetchedRevision) void fetchOnce();
    }, 5_000);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      for (const controller of controllers) controller.abort();
      controllers.clear();
      window.clearInterval(timer);
      window.clearInterval(revisionTimer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
);

export function useDecisionEvidence(): DecisionEvidenceState {
  return useSyncExternalStore(
    decisionEvidenceStore.subscribe,
    decisionEvidenceStore.getSnapshot,
    decisionEvidenceStore.getSnapshot,
  );
}

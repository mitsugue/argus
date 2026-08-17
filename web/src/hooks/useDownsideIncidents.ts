import { useSyncExternalStore } from 'react';
import { deauthorizeDownsideSnapshot, liveAuthorityState,
  scheduleLiveAuthorityExpiry } from '../domain/liveAuthority';
import { createSharedPollingStore } from '../lib/sharedPollingStore';

// Downside Incident Response (downside-v1, v10.98) — when a held/watched name
// drops materially, the backend classifies the incident (cause buckets, action
// override, missing data, next condition) so the UI never shows a bare "急落".
// Refreshes every 60s while visible (server caches 60s).

export interface CauseBucket {
  cause: string;
  probability: number;   // 0..1, buckets sum to 1
  evidenceIds: string[];
}

export interface DownsideIncident {
  incidentId: string;
  symbol: string;
  market: 'JP' | 'US' | string;
  assetName: string;
  changePct: number | null;
  incidentType: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  holderImpact: string;
  currentAction: string;
  actionOverride: string;
  causeBuckets: CauseBucket[];
  reasonJa: string;
  missingData: string[];
  nextConditionJa: string;
  doNotDoJa: string;
  nextReviewAt: string | null;
  isHeld: boolean;
  ownerState?: string;       // watch | active | held | protected | null
  priority?: string;         // low | normal | high
  status: 'live' | 'partial';
  dedupKey?: string;
  /** C.A.O.S. candidate lead (v10.174): the linked news behind the move (by name OR entity
   *  relationship), corroboration-labeled. A candidate, not an asserted cause. */
  caosLead?: { titleJa: string; via: string; term?: string; relationJa?: string | null; corroboration: string };
  /** Mover Cause ladder (v11.3.3): 原因確認/有力材料/候補/有力候補なし — a bare 原因未確認 is banned. */
  causeStatus?: 'confirmed_cause' | 'probable_catalyst' | 'candidate_catalyst' | 'no_lead_yet' | 'not_scoreable';
  moverCause?: MoverCauseCompact;
}

export interface MoverCauseCandidate {
  titleJa?: string; category?: string; timingRelation?: string;
  /** v11.5.2: English original + status when titleJa was a translated headline. */
  titleOriginal?: string; translationStatus?: 'translated' | 'not_needed' | 'pending' | 'failed';
  /** v11.5.3: freshness gate — old/stale news is 過去材料, never a current lead. */
  newsFreshness?: { ageHours?: number | null; freshness?: string;
                    eligibleAsPrimaryLead?: boolean; staleReasonJa?: string };
  corroborationLevel?: string; confidence?: number; source?: string;
}
export interface MoverCauseFreshness {
  lastEvidenceRefreshAt?: string; evidenceAgeSec?: number;
  isStale?: boolean; staleReasonJa?: string; nextAutoCheckAt?: string | null;
}
export interface MoverMarketConfirmation {
  status?: string; stale?: boolean; volumeRatio?: number | null; relativeToIndexPct?: number | null;
  peerBasketMovePct?: number | null; vwapDistancePct?: number | null; window?: string;
}
export interface MoverCauseCompact {
  causeStatus?: string; causeStatusJa?: string;
  bestLeadJa?: string; whyNotConfirmedJa?: string; checkedJa?: string;
  nextChecksJa?: string[]; impactCommentJa?: string; confidence?: number;
  explanationJa?: string | null;
  explanationStatus?: 'cached' | 'pending' | 'not_generated';
  freshness?: MoverCauseFreshness;
  marketConfirmation?: MoverMarketConfirmation;
  topCandidates?: MoverCauseCandidate[];
}

export interface JpOverlay {
  globalRegime: string;
  jpIntradayOverlay: 'NORMAL' | 'CAUTION' | 'RISK_OFF_WATCH' | string;
  holderRiskOverlay: 'NONE' | 'REVIEW_REQUIRED' | string;
  flags: string[];
  displayJa: string;
  reasonJa: string;
}

export interface DownsideSnapshot {
  status: 'live' | 'partial';
  asOf: string;
  engineVersion: string;
  incidents: DownsideIncident[];
  activeCount: number;
  ownerAffected: boolean;
  globalRegime: string;
  jpIntradayOverlay: string;
  holderRiskOverlay: string;
  overlay: JpOverlay;
  dataLimitations: string[];
  noteJa: string;
}

const REFRESH_INTERVAL_MS = 60_000;    // restored 120→60s (v10.126): Render is on Standard 2GB now — poll the downside layer every 60s for faster drop detection

interface State {
  data: DownsideSnapshot | null;
  loading: boolean;
  error: string | null;
  authority: string;
}

const downsideStore = createSharedPollingStore<State>(
  { data: null, loading: true, error: null, authority: 'unavailable' },
  (setState, getState) => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: null, loading: false, error: null, authority: 'unavailable' });
      return () => {};
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/downside-incidents';
    let cancelled = false;
    let acquisition: Promise<void> | null = null;
    let cancelExpiry = () => {};
    const controllers = new Set<AbortController>();

    function acquire(task: () => Promise<void>) {
      if (acquisition) return acquisition;
      const current = task().finally(() => {
        if (acquisition === current) acquisition = null;
      });
      acquisition = current;
      return current;
    }

    function accept(data: DownsideSnapshot) {
      cancelExpiry();
      const authority = liveAuthorityState(data.asOf, 'downsideIncidents');
      if (authority !== 'fresh') {
        setState({ data: deauthorizeDownsideSnapshot(data,
          authority === 'expired' ? 'snapshot_expired' : 'invalid_as_of'),
        loading: false, error: null, authority });
        return;
      }
      setState({ data, loading: false, error: null, authority: 'fresh' });
      cancelExpiry = scheduleLiveAuthorityExpiry(data.asOf, 'downsideIncidents', () => {
        const current = getState();
        if (!current.data || current.authority !== 'fresh') return;
        setState({ ...current,
          data: deauthorizeDownsideSnapshot(current.data, 'snapshot_expired'),
          authority: 'expired' });
      });
    }

    function fail(message: string) {
      const current = getState();
      cancelExpiry();
      if (current.data) {
        setState({ ...current,
          data: deauthorizeDownsideSnapshot(current.data, 'refresh_failed'),
          loading: false, error: message, authority: 'refresh_failed' });
      } else {
        setState({ data: null, loading: false, error: message, authority: 'unavailable' });
      }
    }

    async function fetchOnce() {
      if (cancelled || document.hidden) return;
      const controller = new AbortController();
      controllers.add(controller);
      const timer = window.setTimeout(() => controller.abort(), 12_000);
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json() as DownsideSnapshot;
        if (!cancelled) accept(data);
      } catch (err: unknown) {
        if (!cancelled) fail(err instanceof Error ? err.message : String(err));
      } finally {
        window.clearTimeout(timer);
        controllers.delete(controller);
      }
    }

    const retained = getState();
    if (retained.data && retained.authority === 'fresh') accept(retained.data);
    const interval = window.setInterval(
      () => void acquire(fetchOnce), REFRESH_INTERVAL_MS);
    const onVisible = () => { if (!document.hidden) void acquire(fetchOnce); };
    document.addEventListener('visibilitychange', onVisible);
    void acquire(fetchOnce);
    return () => {
      cancelled = true;
      cancelExpiry();
      for (const controller of controllers) controller.abort();
      controllers.clear();
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  },
);

export function useDownsideIncidents(): State {
  return useSyncExternalStore(
    downsideStore.subscribe, downsideStore.getSnapshot, downsideStore.getSnapshot);
}

import { useEffect, useState } from 'react';
import { FEED_VISIBLE_MS, isPageVisible } from '../lib/pollingPolicy';

// v13.5.3 Nikkei mail intelligence: normalized NewsRiskEvidence envelopes
// classified server-side (dedicated read-only mailbox → pure policy engine).
// Evidence only — never SDA authority. Read-only cached GET with explicit
// intake states; the raw email never reaches the browser.
export interface NewsIntelEvent {
  schemaVersion: string;
  eventId: string;
  revision: number;
  source: string;
  sourceReceivedAt: string | null;
  processedAt: string;
  headlineJa: string;
  titleOriginal: string;
  displayTitleJa: string;
  translationStatus: 'translated' | 'not_needed';
  eventType: string;
  themeTags: string[];
  facts: string[];
  sourceUrl: string | null;
  staleness: string;          // backend UPPERCASE enum, re-evaluated at read time
  ageMinutes?: number;        // minutes since receipt (server-computed at read)
  severity: 'INFO' | 'WATCH' | 'HIGH' | 'CRITICAL';
  severityReasons: string[];
  confirmationState: 'MARKET_CONFIRMED' | 'MARKET_CONFIRMATION_PENDING';
  whyJa: string;
  japanImpactJa: string | null;
  generalTransmissionJa?: string;
  // v13.5.36 NEWS/EVENT DIRECTIONAL IMPACT — independent axis beside
  // severity and market confirmation. Optional: events stored before the
  // direction engine existed simply have no signal (UNCLEAR, not fabricated).
  impactDirection?: {
    schemaVersion: string;
    polarity: string;
    directionByTarget: Record<string, 'BULLISH' | 'BEARISH' | 'MIXED' | 'UNCLEAR'>;
    primaryDirection: 'BULLISH' | 'BEARISH' | 'MIXED' | 'UNCLEAR';
    timeHorizon: string;
    transmissionChain: string[];
    confidence: 'LOW' | 'MEDIUM';
    directionAuthority: false;
  };
  executionConstraint?: 'NO_CONSTRAINT' | 'CAUTION' | 'BLOCK_NEW_BUY'
    | 'RISK_REVIEW_REQUIRED';
  marketReadings: Array<{ key: string; labelJa: string; value: number | null;
    change: number | null; unit: string; asOf?: string | null }>;
  analysisState: string;
  analysisInputScope?: string;
  analysisDiagnostic?: { reason?: string | null; outcome?: string; completedAt?: string; returnedModel?: string | null };
  alertEligible: boolean;
  backfill: boolean;
  sdaAuthority: false;
  eventMemory: {
    status: string;
    firstSeenAt: string;
    openedDaysAgo: number | null;
    episodeId: string;
    flagRecovery: boolean;
    hypothesisStates: Record<string, string>;
    analogEvidence: {
      sampleSize: number;
      independentEpisodeCount: number;
      confidence: string;
      insufficientEvidence: boolean;
    } | null;
    calibrationMode: 'SHADOW';
    sdaAuthority: false;
  } | null;
}

export interface NewsIntelView {
  schemaVersion: string;
  generatedAt: string;
  intakeStatus: string;
  aiBudgetEnforced?: boolean;
  eventCount: number;
  pendingTranslationCount?: number;
  events: NewsIntelEvent[];
}

export interface NewsIntelState {
  status: 'loading' | 'data' | 'error';
  view: NewsIntelView | null;
  intakeHealth?: NewsIntakeHealth | null;
}

export interface NewsIntakeHealth {
  status: string; lastSyncAt: string | null; lastMessageAt: string | null;
  pending: number; configured: boolean; threadAlive: boolean;
}
let healthFlight: Promise<NewsIntakeHealth | null> | null = null;
async function fetchIntakeHealth(): Promise<NewsIntakeHealth | null> {
  const base = baseUrl();
  if (!base) return null;
  try {
    const response = await fetch(`${base}/api/argus/news-intake/health`, { cache:'no-store', signal:AbortSignal.timeout(5000) });
    if (!response.ok) return null;
    const body = await response.json();
    if (body.schemaVersion !== 'argus-news-intake-health-v1') return null;
    // Keep only the status fields the screen needs, never mail IDs/domains.
    return { status:String(body.status), lastSyncAt:typeof body.lastSyncAt === 'string' ? body.lastSyncAt : null,
      lastMessageAt:typeof body.lastMessageAt === 'string' ? body.lastMessageAt : null,
      pending:Number.isFinite(body.pending) ? body.pending : 0, configured:body.configured === true, threadAlive:body.threadAlive === true };
  } catch { return null; }
}

let memory: NewsIntelView | null = null;
let inflight: Promise<NewsIntelView | null> | null = null;

function baseUrl() {
  return (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)
    ?.replace(/\/$/, '') ?? null;
}

async function fetchNewsIntel(): Promise<NewsIntelView | null> {
  const base = baseUrl();
  if (!base) return null;
  // Release the shared flight on stalled headers/body so later refreshes can
  // recover. Previously acquired rows remain visible with an error state.
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 20_000);
  try {
    const response = await fetch(`${base}/api/argus/news-intelligence`, {
      method: 'GET', cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json() as NewsIntelView;
    if (body.schemaVersion !== 'argus-news-intelligence-v1') {
      throw new Error('schema_incompatible');
    }
    return body;
  } finally {
    window.clearTimeout(timer);
  }
}

export function useNewsIntelligence(): NewsIntelState {
  const [intakeHealth, setIntakeHealth] = useState<NewsIntakeHealth | null>(null);
  const [state, setState] = useState<NewsIntelState>(() => (memory
    ? { status: 'data', view: memory }
    : { status: 'loading', view: null }));
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!healthFlight) healthFlight = fetchIntakeHealth().finally(() => { healthFlight = null; });
      void healthFlight.then(health => { if (!cancelled) setIntakeHealth(health); });
      if (!cancelled) setState(current => ({ ...current, status: 'loading' }));
      if (!inflight) {
        inflight = fetchNewsIntel().finally(() => { inflight = null; });
      }
      try {
        const view = await inflight;
        if (!cancelled && view) {
          memory = view;
          setState({ status: 'data', view });
        } else if (!cancelled && !view) {
          setState({ status: 'error', view: memory });
        }
      } catch {
        // v13.5.50: a failed refresh never relabels retained data as current.
        if (!cancelled) {
          setState({ status: 'error', view: memory });
        }
      }
    };
    void load();
    const timer = window.setInterval(() => { if (isPageVisible()) void load(); }, FEED_VISIBLE_MS);
    const onVisible = () => { if (!document.hidden) void load(); };
    const onOnline = () => void load();
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('online', onOnline);
    return () => {
      cancelled = true; window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('online', onOnline);
    };
  }, []);
  return { ...state, intakeHealth };
}

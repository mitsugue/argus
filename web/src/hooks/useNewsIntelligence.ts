import { useEffect, useState } from 'react';

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
  staleness: string;
  severity: 'INFO' | 'WATCH' | 'HIGH' | 'CRITICAL';
  severityReasons: string[];
  confirmationState: 'MARKET_CONFIRMED' | 'MARKET_CONFIRMATION_PENDING';
  whyJa: string;
  japanImpactJa: string | null;
  // v13.5.20 NEWS/EVENT DIRECTIONAL IMPACT — independent axis beside
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
  eventCount: number;
  pendingTranslationCount?: number;
  events: NewsIntelEvent[];
}

export interface NewsIntelState {
  status: 'loading' | 'data' | 'error';
  view: NewsIntelView | null;
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
  const response = await fetch(`${base}/api/argus/news-intelligence`, {
    method: 'GET', cache: 'no-store', headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = await response.json() as NewsIntelView;
  if (body.schemaVersion !== 'argus-news-intelligence-v1') {
    throw new Error('schema_incompatible');
  }
  return body;
}

export function useNewsIntelligence(): NewsIntelState {
  const [state, setState] = useState<NewsIntelState>(() => (memory
    ? { status: 'data', view: memory }
    : { status: 'loading', view: null }));
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
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
        if (!cancelled) {
          setState({ status: memory ? 'data' : 'error', view: memory });
        }
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 5 * 60_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);
  return state;
}

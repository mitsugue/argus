import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { TriangleStepLoader } from '../common/TriangleStepLoader';
import { useTodayHeadline } from '../../hooks/useTodayHeadline';
import { useImportantEvents } from '../../hooks/useImportantEvents';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import { useAIJudgment } from '../../hooks/useAIJudgment';
import { useFutureMapLoad } from '../../hooks/useFutureMap';
import './BootConsole.css';

/** One centered console that stays up until every Today lane has settled.
 *
 *  It never invents progress: the percentage is settled lanes over total
 *  lanes, each lane is the real state of the hook that feeds Today, and a
 *  lane that fails is reported as unavailable rather than hidden. The card
 *  is non-blocking (pointer events pass through) and is rendered through a
 *  body portal so the shell transform cannot pin it to the page. */

export type BootLaneStatus = 'loading' | 'ready' | 'cached' | 'unavailable';

export interface BootLane {
  id: string;
  label: string;
  detail: string;
  status: BootLaneStatus;
}

export interface BootConsoleInputs {
  chart: { snapshotState: string; snapshotId: string | null; error: string | null };
  index: { data: unknown | null; loading: boolean; error: string | null; expectedSkip?: boolean };
  news: { loading: boolean; data: unknown | null; failureClass: string | null };
  newsIntel: { status: 'loading' | 'data' | 'error' };
  decision: { loading: boolean; error: string | null; subjects: unknown | null };
}

const SETTLED_HOLD_MS = 900;
const SLOW_AFTER_MS = 20_000;

function chartLaneStatus(input: BootConsoleInputs['chart']): BootLaneStatus {
  switch (input.snapshotState) {
    case 'CURRENT_READY': return 'ready';
    case 'STALE_FALLBACK':
    case 'ERROR_WITH_CACHE': return 'cached';
    case 'ERROR_WITHOUT_CACHE': return 'unavailable';
    default: return input.snapshotId ? 'cached' : 'loading';
  }
}

function settled(status: BootLaneStatus): boolean {
  return status !== 'loading';
}

function combine(a: BootLaneStatus, b: BootLaneStatus): BootLaneStatus {
  if (a === 'loading' || b === 'loading') return 'loading';
  if (a === 'unavailable' && b === 'unavailable') return 'unavailable';
  if (a === 'ready' && b === 'ready') return 'ready';
  return 'cached';
}

export function useBootLanes(inputs: BootConsoleInputs): BootLane[] {
  const headline = useTodayHeadline();
  const events = useImportantEvents();
  const brief = useMarketBrief();
  const judgment = useAIJudgment();
  const futureMap = useFutureMapLoad();
  return useMemo<BootLane[]>(() => {
    const chart = chartLaneStatus(inputs.chart);
    const index: BootLaneStatus = inputs.index.loading ? 'loading'
      : inputs.index.data ? 'ready'
        : (inputs.index.error || inputs.index.expectedSkip) ? 'unavailable' : 'loading';
    // The stored headline shows at once while it is being re-read
    // ('revalidating'); that is still loading, not a settled cached view.
    // Only a failed re-read leaves it 'cached' (2026-10-04: the console
    // closed while this lane still read 'cached').
    const headlineStatus: BootLaneStatus = headline.status === 'loading' ? 'loading'
      : headline.status === 'data'
        ? (headline.stale ? (headline.reason === 'revalidating' ? 'loading' : 'cached') : 'ready')
        : 'unavailable';
    const eventStatus: BootLaneStatus = events.loading ? 'loading'
      : events.data ? 'ready' : 'unavailable';
    const marketNews: BootLaneStatus = inputs.news.loading ? 'loading'
      : inputs.news.data ? 'ready' : 'unavailable';
    const intel: BootLaneStatus = inputs.newsIntel.status === 'loading' ? 'loading'
      : inputs.newsIntel.status === 'data' ? 'ready' : 'unavailable';
    const briefStatus: BootLaneStatus = brief.loading && !brief.brief ? 'loading'
      : brief.brief ? 'ready' : 'unavailable';
    // The integrated outlook is a stored judgment by design: the product does
    // not run the AI on every page load. Reserving 'ready' for a live run
    // therefore left this lane reading 'cached' on every first load, as if
    // something had failed (owner, 2026-09-29). A judgment that is current
    // for the latest scheduled run is ready; only a missed run is 'cached'.
    const judgmentStatus: BootLaneStatus = judgment.loading ? 'loading'
      : !judgment.data ? 'unavailable'
        : judgment.phase === 'disabled' || judgment.phase === 'mock' ? 'unavailable'
          : judgment.data.freshness === 'stale' ? 'cached' : 'ready';
    const decision: BootLaneStatus = inputs.decision.loading ? 'loading'
      : inputs.decision.subjects ? 'ready' : 'unavailable';
    // Lanes follow the Today screen from top to bottom (owner, 2026-10-04).
    return [
      { id: 'outlook', label: 'Today outlook', detail: 'integrated AI · market position',
        status: combine(briefStatus, judgmentStatus) },
      { id: 'future-map', label: 'FUTURE MAP', detail: 'external views table',
        status: futureMap },
      { id: 'nikkei', label: 'Nikkei 225 & analogs', detail: 'verified calc · index · market headline',
        status: combine(combine(chart, index), headlineStatus) },
      { id: 'decision', label: 'Decision evidence', detail: 'data · seven signs · call',
        status: decision },
      { id: 'news', label: 'Material news', detail: 'headlines · market risk',
        status: combine(marketNews, intel) },
      { id: 'events', label: 'Event calendar', detail: 'next 30 days · SQ',
        status: eventStatus },
    ];
  }, [inputs, headline.status, headline.stale, headline.reason, futureMap, events.loading, events.data,
    brief.loading, brief.brief, judgment.loading, judgment.data, judgment.phase]);
}

const STATUS_WORD: Record<BootLaneStatus, string> = {
  loading: 'loading', ready: 'ready', cached: 'cached', unavailable: 'unavailable',
};

export const BootConsole: React.FC<{ inputs: BootConsoleInputs }> = ({ inputs }) => {
  const lanes = useBootLanes(inputs);
  const total = lanes.length;
  const done = lanes.filter((lane) => settled(lane.status)).length;
  const percent = Math.round((done / total) * 100);
  const complete = done === total;
  const [phase, setPhase] = useState<'open' | 'closing' | 'closed'>('open');
  const [dismissed, setDismissed] = useState(false);
  const [slow, setSlow] = useState(false);
  const startedAt = useRef<number>(Date.now());

  useEffect(() => {
    if (!complete || phase !== 'open') return;
    const hold = window.setTimeout(() => setPhase('closing'), SETTLED_HOLD_MS);
    return () => window.clearTimeout(hold);
  }, [complete, phase]);

  useEffect(() => {
    if (phase !== 'closing') return;
    const gone = window.setTimeout(() => setPhase('closed'), 420);
    return () => window.clearTimeout(gone);
  }, [phase]);

  useEffect(() => {
    if (complete) return;
    const elapsed = Date.now() - startedAt.current;
    const wait = Math.max(0, SLOW_AFTER_MS - elapsed);
    const timer = window.setTimeout(() => setSlow(true), wait);
    return () => window.clearTimeout(timer);
  }, [complete]);

  if (phase === 'closed' || dismissed || typeof document === 'undefined') return null;

  const summary = complete
    ? `Market context ready · ${total} of ${total}`
    : `Loading market context · ${done} of ${total}`;

  return createPortal(
    <div className={`boot-console${phase === 'closing' ? ' is-closing' : ''}${complete ? ' is-complete' : ''}`}
      role="status" aria-live="polite" aria-label={summary}>
      <div className="boot-console__head">
        <TriangleStepLoader compact label="" />
        <span className="boot-console__title">{complete ? 'READY' : 'SCANNING'}</span>
        <span className="boot-console__percent">{percent}%</span>
        <button type="button" className="boot-console__dismiss" aria-label="Dismiss"
          onClick={() => setDismissed(true)}>×</button>
      </div>
      <div className="boot-console__bar" aria-hidden="true">
        <span className="boot-console__fill" style={{ width: `${percent}%` }} />
      </div>
      <ul className="boot-console__lanes">
        {lanes.map((lane) => (
          <li key={lane.id} className={`boot-console__lane is-${lane.status}`}>
            <span className="boot-console__dot" aria-hidden="true" />
            <span className="boot-console__label">{lane.label}</span>
            <span className="boot-console__detail">{lane.detail}</span>
            <span className="boot-console__state">{STATUS_WORD[lane.status]}</span>
          </li>
        ))}
      </ul>
      {slow && !complete && (
        <div className="boot-console__note">Still fetching · cached views stay visible behind this card</div>
      )}
    </div>,
    document.body,
  );
};

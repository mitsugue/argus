import React, { useMemo } from 'react';
import { PageShell } from './PageShell';
import { WatchRow } from '../components/dashboard/WatchRow';
import { ActionPill } from '../components/action/ActionBadge';
import { useJapanWatchlist } from '../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../hooks/useUSWatchlist';
import { useActionLabels } from '../hooks/useActionLabels';
import type { WatchEntry, WatchJP, WatchUS, JapanStockQuote, USStockQuote } from '../types/watch';
import type { ActionLabel } from '../types/actionLabels';
import type { ActionKey } from '../types/action';
import '../components/dashboard/Dashboard.css';

// Sort: defensive first (EXIT > TRIM > WAIT_FOR_PULLBACK > WAIT > BUY_DIP > ADD > HOLD).
const URGENCY: Record<ActionKey, number> = {
  EXIT: 0,
  TRIM: 1,
  WAIT_FOR_PULLBACK: 2,
  WAIT: 3,
  BUY_DIP: 4,
  ADD: 5,
  HOLD: 6,
};

const sortByUrgency = (a: WatchEntry, b: WatchEntry) =>
  URGENCY[a.action as ActionKey] - URGENCY[b.action as ActionKey];

// Distinct actions that appear in scope — used for the summary chip strip.
function tally(entries: WatchEntry[]): { action: ActionKey; count: number }[] {
  const counts = new Map<ActionKey, number>();
  for (const e of entries) {
    counts.set(e.action as ActionKey, (counts.get(e.action as ActionKey) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([action, count]) => ({ action, count }))
    .sort((a, b) => URGENCY[a.action] - URGENCY[b.action]);
}

const ACTION_KEYS: ActionKey[] = ['EXIT', 'TRIM', 'WAIT', 'WAIT_FOR_PULLBACK', 'BUY_DIP', 'ADD', 'HOLD'];
// Backend sends English action strings ("WAIT FOR PULLBACK"); normalize to the
// frontend's underscored ActionKey. Falls back to HOLD when no label is present.
function toActionKey(a?: string): ActionKey {
  const k = (a ?? 'HOLD').replace(/ /g, '_');
  return (ACTION_KEYS as string[]).includes(k) ? (k as ActionKey) : 'HOLD';
}

// Map a live quote + (optional) action label into a watch row. Price/volume
// come from the watchlist hook; action/reason/confidence/risk from the label.
function toRow<M extends 'JP' | 'US'>(
  q: JapanStockQuote | USStockQuote,
  market: M,
  label: ActionLabel | undefined,
): WatchJP | WatchUS {
  return {
    market,
    symbol: q.symbol,
    name: q.name,
    price: q.price,
    changePct: q.changePct,
    changeAbs: q.changeAbs,
    volume: q.volume,
    action: toActionKey(label?.action),
    reason: label?.reasonJa,
    confidence: label?.confidence,
    signalRisk: label?.risk,
    nextConditionJa: label?.nextConditionJa,
    updatedAt: Date.now(),
  } as WatchJP | WatchUS;
}

function statusLabel(phase: 'connecting' | 'live' | 'partial' | 'mock', attempt: number): string {
  if (phase === 'connecting') return attempt > 1 ? `waking backend · try ${attempt}` : 'connecting';
  return phase; // 'live' | 'partial' | 'mock'
}

export const Watchlist: React.FC = () => {
  const { data: jp, phase: jpPhase, attempt: jpAttempt } = useJapanWatchlist();
  const { data: us, phase: usPhase, attempt: usAttempt } = useUSWatchlist();
  const { data: labels } = useActionLabels();

  // symbol → action label (rule-based engine v0). Empty when labels unavailable.
  const labelMap = useMemo(() => {
    const m = new Map<string, ActionLabel>();
    (labels?.labels ?? []).forEach((l) => m.set(l.symbol, l));
    return m;
  }, [labels]);

  const jpRows = useMemo<WatchJP[]>(
    () => (jp ? jp.stocks.map((s) => toRow(s, 'JP', labelMap.get(s.symbol)) as WatchJP).sort(sortByUrgency) : []),
    [jp, labelMap],
  );
  const usRows = useMemo<WatchUS[]>(
    () => (us ? us.stocks.map((s) => toRow(s, 'US', labelMap.get(s.symbol)) as WatchUS).sort(sortByUrgency) : []),
    [us, labelMap],
  );
  const summary = useMemo(() => tally([...jpRows, ...usRows]), [jpRows, usRows]);

  return (
    <PageShell
      title="Watchlist"
      subtitle="Tracked names with their action label. Sorted by urgency — defensive calls first."
    >
      {labels?.marketPosture && (
        <div className="watch-posture">
          <span className="watch-posture__label">{labels.marketPosture.label.replace('_', ' ')}</span>
          <span className="watch-posture__note">{labels.marketPosture.rationaleJa}</span>
        </div>
      )}

      <div className="watch-summary">
        {summary.map(({ action, count }) => (
          <span className="watch-summary__item" key={action}>
            <ActionPill action={action} size="sm" />
            <span className="watch-summary__count">{count}</span>
          </span>
        ))}
      </div>

      <section>
        <div className="section-head">
          <span className="section-head__title">Japan</span>
          <span className={`watch-status watch-status--${jpPhase}`}>{statusLabel(jpPhase, jpAttempt)}</span>
          {jpPhase === 'live' && jp?.asOf ? (
            <span className="section-head__count">live · as of {jp.asOf}</span>
          ) : (
            <span className="section-head__count">{jpRows.length} names</span>
          )}
        </div>
        <div className="card watch-list">
          {jpRows.map((row) => (
            <WatchRow key={row.symbol} entry={row} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">United States</span>
          <span className={`watch-status watch-status--${usPhase}`}>{statusLabel(usPhase, usAttempt)}</span>
          {usPhase === 'live' && us?.asOf ? (
            <span className="section-head__count">live · as of {us.asOf}</span>
          ) : (
            <span className="section-head__count">{usRows.length} names</span>
          )}
        </div>
        <div className="card watch-list">
          {usRows.map((row) => (
            <WatchRow key={row.symbol} entry={row} />
          ))}
        </div>
      </section>
    </PageShell>
  );
};

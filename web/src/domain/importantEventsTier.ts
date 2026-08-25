// Important-event constraint tiering (v13.5.31, external review item C).
//
// The reviewer's finding: a flat D/D-1 → WAIT_REQUIRED rule made a medium
// statistics release carry the same hard constraint as FOMC. The tiered rule:
//   critical / high  → WAIT_REQUIRED (hard: the decision itself waits)
//   medium / low     → BLOCK_BUY     (execution constraint only: no new adds,
//                                     held-position judgment continues)
// Unknown impact defaults to the SOFTER tier — an event we cannot classify
// must not silently escalate to a hard WAIT (that inversion is exactly what
// the audit flagged); the calendar-unknown state has its own MISSING factor.
//
// The gate is built from the uncapped `imminent` feed when the backend
// provides it, falling back to the capped display list for older backends so
// the constraint never silently disappears during a rollout.

import type { EventImpact, ImminentEvent, ImportantEventsSnapshot } from '../hooks/useImportantEvents';

export type EventTierConstraint = 'WAIT_REQUIRED' | 'BLOCK_BUY';

export interface EventGateEntry {
  eventCode: string;
  displayImpact: EventImpact | null;
}

const IMPACT_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

export function eventKernelConstraint(displayImpact: EventImpact | null | undefined): EventTierConstraint {
  return displayImpact === 'critical' || displayImpact === 'high'
    ? 'WAIT_REQUIRED' : 'BLOCK_BUY';
}

export function eventKernelSeverity(displayImpact: EventImpact | null | undefined): 'HIGH' | 'MEDIUM' {
  return displayImpact === 'critical' ? 'HIGH' : 'MEDIUM';
}

/** Strongest imminent (D / D-1) linked event per symbol. */
export function imminentEventGate(snapshot: ImportantEventsSnapshot | null | undefined): Map<string, EventGateEntry> {
  const gate = new Map<string, EventGateEntry>();
  const source: ImminentEvent[] = snapshot?.imminent
    ?? (snapshot?.events ?? [])
      .filter((event) => event.countdown === 'D' || event.countdown === 'D-1')
      .map((event) => ({
        eventCode: event.eventCode, countdown: event.countdown,
        displayImpact: event.displayImpact,
        linkedAssets: event.linkedAssets ?? [], title: event.title,
      }));
  for (const event of source) {
    if (event.countdown !== 'D' && event.countdown !== 'D-1') continue;
    for (const linked of event.linkedAssets ?? []) {
      const sym = String(linked).toUpperCase();
      if (!sym) continue;
      const previous = gate.get(sym);
      const rank = IMPACT_RANK[String(event.displayImpact)] ?? 0;
      const previousRank = previous ? (IMPACT_RANK[String(previous.displayImpact)] ?? 0) : -1;
      if (rank > previousRank) {
        gate.set(sym, {
          eventCode: String(event.eventCode ?? ''),
          displayImpact: event.displayImpact ?? null,
        });
      }
    }
  }
  return gate;
}

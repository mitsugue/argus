// News → execution-constraint gate (v13.5.23, external review BLOCKERs 2/5).
//
// The direction signal is PER TARGET; the kernel constraint must therefore be
// PER SUBJECT: an energy-only bearish headline may not block buying an index
// ETF (the reviewer's ceasefire example — broad tailwind, energy headwind).
// A subject is gated only when a MARKET-CONFIRMED, non-stale HIGH/CRITICAL
// bearish signal covers a target that actually includes it:
//   broadMarket   → every JP/US equity subject
//   japanEquities → JP subjects
//   theme targets → subjects whose theme intersects the target's theme set
// PENDING or STALE headlines never gate here (they advise on the Today strip
// only), and the constraint stays BLOCK_BUY-only — news can never
// SELL/EXIT/WAIT the decision.

import type { NewsIntelEvent } from '../hooks/useNewsIntelligence';
import type { ThemeKey } from './positionExposure';

// Direction targets → the app's theme vocabulary (positionExposure.ThemeKey).
export const TARGET_THEMES: Record<string, ThemeKey[]> = {
  growth: ['ai_infrastructure', 'physical_ai_robotics', 'semiconductor_photonics'],
  semiconductors: ['semiconductor_photonics', 'ai_infrastructure'],
  banks: [],                       // no bank theme in the owner universe yet
  exporters: ['defense_heavy_industry', 'trading_commodity'],
  energy: ['trading_commodity'],
};

export interface NewsGateSubject {
  symbol: string;
  market: string;
  theme: ThemeKey | null;
}

export interface NewsGateHit {
  eventId: string;
  severity: 'HIGH' | 'CRITICAL';
  bearishTargets: string[];
  matchedTarget: string;
}

const eligible = (event: NewsIntelEvent): boolean =>
  (event.severity === 'HIGH' || event.severity === 'CRITICAL')
  && event.confirmationState === 'MARKET_CONFIRMED'
  && String(event.staleness).toUpperCase() !== 'STALE';

/** Strongest confirmed bearish signal that actually covers this subject. */
export function newsKernelGate(
  events: readonly NewsIntelEvent[] | undefined,
  subject: NewsGateSubject,
): NewsGateHit | null {
  if (subject.market !== 'JP' && subject.market !== 'US') return null;
  let best: NewsGateHit | null = null;
  for (const event of events ?? []) {
    if (!eligible(event)) continue;
    const byTarget = event.impactDirection?.directionByTarget ?? {};
    const bearish = Object.entries(byTarget)
      .filter(([, direction]) => direction === 'BEARISH')
      .map(([target]) => target);
    if (bearish.length === 0) continue;
    let matched: string | null = null;
    if (bearish.includes('broadMarket')) matched = 'broadMarket';
    else if (bearish.includes('japanEquities') && subject.market === 'JP') {
      matched = 'japanEquities';
    } else if (subject.theme) {
      matched = bearish.find((target) =>
        (TARGET_THEMES[target] ?? []).includes(subject.theme as ThemeKey)) ?? null;
    }
    if (!matched) continue;
    const hit: NewsGateHit = {
      eventId: String(event.eventId), severity: event.severity as 'HIGH' | 'CRITICAL',
      bearishTargets: bearish, matchedTarget: matched,
    };
    if (!best || (hit.severity === 'CRITICAL' && best.severity !== 'CRITICAL')) {
      best = hit;
    }
  }
  return best;
}

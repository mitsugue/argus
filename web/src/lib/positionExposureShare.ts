// V11.8.0 — device-local hand-off of the computed PortfolioExposure between
// components (Today/Watchlist compute it; ProHandoffButton / AI Review Sheet
// read it at copy time). Module-singleton on purpose: the data never leaves
// the page, is never persisted, and is never sent to the backend.

import type { PortfolioExposure } from '../domain/positionExposure';

let latest: PortfolioExposure | null = null;

export function publishExposure(pe: PortfolioExposure): void {
  latest = pe;
}

export function latestExposure(): PortfolioExposure | null {
  return latest;
}

// v11.12.0: latest device-local Action Priority items (same lifecycle contract).
import type { APItem } from '../domain/actionPriority';
let latestAP: APItem[] = [];
export function publishActionPriorities(items: APItem[]): void { latestAP = items; }
export function latestActionPriorities(): APItem[] { return latestAP; }

// v11.13.0: latest device-local Session Brief (same lifecycle contract).
import type { LocalBrief } from '../domain/sessionBrief';
let latestSB: LocalBrief | null = null;
export function publishSessionBrief(b: LocalBrief): void { latestSB = b; }
export function latestSessionBrief(): LocalBrief | null { return latestSB; }

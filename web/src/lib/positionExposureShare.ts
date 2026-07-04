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

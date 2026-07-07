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

// v11.17.0: latest device-local Scenario Sets (same lifecycle contract).
import type { LocalScenarioSet } from '../domain/scenario';
let latestSC: LocalScenarioSet[] = [];
export function publishScenarios(sets: LocalScenarioSet[]): void { latestSC = sets; }
export function latestScenarios(): LocalScenarioSet[] { return latestSC; }

// v11.18.0: latest device-local Position Plans (same lifecycle contract).
import type { LocalPlan } from '../domain/positionPlan';
let latestPP: LocalPlan[] = [];
export function publishPlans(plans: LocalPlan[]): void { latestPP = plans; }
export function latestPlans(): LocalPlan[] { return latestPP; }

// v11.19.0: latest device-local Portfolio Strategy (same lifecycle contract).
import type { LocalStrategy } from '../domain/portfolioStrategy';
let latestPS: LocalStrategy | null = null;
export function publishStrategy(s: LocalStrategy): void { latestPS = s; }
export function latestStrategy(): LocalStrategy | null { return latestPS; }

// v11.19.1: latest device-local FIRE Core summary (same lifecycle contract).
import type { LocalFireCore } from './fireCore';
let latestFC: LocalFireCore | null = null;
export function publishFireCore(f: LocalFireCore): void { latestFC = f; }
export function latestFireCore(): LocalFireCore | null { return latestFC; }

// v11.22.0: latest Data Quality summary (Today fetch → pack/snapshot readers).
export interface DataQualityShare {
  overallStatus: string; overallStatusJa: string;
  topIssuesJa: string[]; expectedDisabledJa: string[];
}
let latestDQx: DataQualityShare | null = null;
export function publishDataQuality(d: DataQualityShare): void { latestDQx = d; }
export function latestDataQuality(): DataQualityShare | null { return latestDQx; }

// v11.20.0: latest Important Events one-liners (for the AI Review Pack —
// the event summary appears in the pack exactly ONCE, from this list).
let latestEV: string[] = [];
export function publishEventsJa(lines: string[]): void { latestEV = lines; }
export function latestEventsJa(): string[] { return latestEV; }

// v12.0.8: 銘柄別OSINT帰属(候補原因) — OSINT Review Packが読む(端末内のみ)。
export interface OsintShare {
  symbol: string; headlineJa: string; osintConfidenceJa: string;
  causes: { categoryJa: string; titleJa: string; source: string; whyWrongJa: string }[];
  sourcesMissingJa: string[];
}
const latestOSINT = new Map<string, OsintShare>();

// v12.1.0: 深掘りOSINT調査の共有(パック用・端末内のみ)。
export interface OsintDeepShare {
  symbol: string; summaryJa: string; coverageJa: string; reliabilityJa: string;
  benchmarkJa: string; disagreementJa: string[]; verifiedTitlesJa: string[];
  missingAreasJa: string[];
  // v12.1.1: 優位性メトリクス
  superiorityJa?: string; superiorityVerdictJa?: string;
  unresolvedCount?: number; verificationRatePct?: number;
  // v12.1.3: Research Power(Gemini基準比)+矛盾警告
  researchPowerJa?: string; researchPowerVerdictJa?: string;
  contradictionWarningsJa?: string[];
}
const latestOSINTDeep = new Map<string, OsintDeepShare>();
export function publishOsintDeep(o: OsintDeepShare): void { latestOSINTDeep.set(o.symbol.toUpperCase(), o); }
export function latestOsintDeep(symbol: string): OsintDeepShare | null {
  return latestOSINTDeep.get(symbol.toUpperCase()) ?? null;
}
export function publishOsint(o: OsintShare): void { latestOSINT.set(o.symbol.toUpperCase(), o); }
export function latestOsint(symbol: string): OsintShare | null {
  return latestOSINT.get(symbol.toUpperCase()) ?? null;
}

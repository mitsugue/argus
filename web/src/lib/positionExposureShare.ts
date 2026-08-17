// V11.8.0 — device-local hand-off of the computed PortfolioExposure between
// components (Today/Watchlist compute it; ProHandoffButton / AI Review Sheet
// read it at copy time). Module-singleton on purpose: the data never leaves
// the page, is never persisted, and is never sent to the backend.

import type { PortfolioExposure } from '../domain/positionExposure';

const DERIVED_SHARE_MAX_AGE_MS = 2 * 60_000;
interface TimedShare<T> {
  value: T;
  publishedAtMs: number;
  /** Earliest upstream evidence deadline. Re-publishing the same evidence does
   * not extend this timestamp. */
  authorityValidUntilMs: number;
}
function currentShare<T>(share: TimedShare<T> | null, nowMs: number): T | null {
  return share && Number.isFinite(nowMs) && nowMs >= share.publishedAtMs
    && nowMs - share.publishedAtMs <= DERIVED_SHARE_MAX_AGE_MS
    && Number.isFinite(share.authorityValidUntilMs)
    && nowMs <= share.authorityValidUntilMs
    ? share.value : null;
}

function timed<T>(value: T, authorityValidUntilMs: number): TimedShare<T> {
  return { value, publishedAtMs: Date.now(), authorityValidUntilMs };
}

let latest: TimedShare<PortfolioExposure> | null = null;

export function publishExposure(pe: PortfolioExposure, authorityValidUntilMs: number): void {
  latest = timed(pe, authorityValidUntilMs);
}

export function latestExposure(nowMs = Date.now()): PortfolioExposure | null {
  return currentShare(latest, nowMs);
}

// v11.12.0: latest device-local Action Priority items (same lifecycle contract).
import type { APItem } from '../domain/actionPriority';
let latestAP: TimedShare<APItem[]> | null = null;
export function publishActionPriorities(items: APItem[], authorityValidUntilMs: number): void {
  latestAP = timed(items, authorityValidUntilMs);
}
export function latestActionPriorities(nowMs = Date.now()): APItem[] {
  return currentShare(latestAP, nowMs) ?? [];
}

// v11.13.0: latest device-local Session Brief (same lifecycle contract).
import type { LocalBrief } from '../domain/sessionBrief';
let latestSB: TimedShare<LocalBrief> | null = null;
export function publishSessionBrief(b: LocalBrief, authorityValidUntilMs: number): void {
  latestSB = timed(b, authorityValidUntilMs);
}
export function latestSessionBrief(nowMs = Date.now()): LocalBrief | null {
  return currentShare(latestSB, nowMs);
}

// v11.17.0: latest device-local Scenario Sets (same lifecycle contract).
import type { LocalScenarioSet } from '../domain/scenario';
let latestSC: TimedShare<LocalScenarioSet[]> | null = null;
export function publishScenarios(sets: LocalScenarioSet[], authorityValidUntilMs: number): void {
  latestSC = timed(sets, authorityValidUntilMs);
}
export function latestScenarios(nowMs = Date.now()): LocalScenarioSet[] {
  return currentShare(latestSC, nowMs) ?? [];
}

// v11.18.0: latest device-local Position Plans (same lifecycle contract).
import type { LocalPlan } from '../domain/positionPlan';
let latestPP: TimedShare<LocalPlan[]> | null = null;
export function publishPlans(plans: LocalPlan[], authorityValidUntilMs: number): void {
  latestPP = timed(plans, authorityValidUntilMs);
}
export function latestPlans(nowMs = Date.now()): LocalPlan[] {
  return currentShare(latestPP, nowMs) ?? [];
}

// v11.19.0: latest device-local Portfolio Strategy (same lifecycle contract).
import type { LocalStrategy } from '../domain/portfolioStrategy';
let latestPS: TimedShare<LocalStrategy> | null = null;
export function publishStrategy(s: LocalStrategy, authorityValidUntilMs: number): void {
  latestPS = timed(s, authorityValidUntilMs);
}
export function latestStrategy(nowMs = Date.now()): LocalStrategy | null {
  return currentShare(latestPS, nowMs);
}

// v11.19.1: latest device-local FIRE Core summary (same lifecycle contract).
import type { LocalFireCore } from './fireCore';
let latestFC: TimedShare<LocalFireCore> | null = null;
export function publishFireCore(f: LocalFireCore, authorityValidUntilMs: number): void {
  latestFC = timed(f, authorityValidUntilMs);
}
export function latestFireCore(nowMs = Date.now()): LocalFireCore | null {
  return currentShare(latestFC, nowMs);
}

function clearDerivedDecisionShares() {
  latest = null;
  latestAP = null;
  latestSB = null;
  latestSC = null;
  latestPP = null;
  latestPS = null;
  latestFC = null;
}

let activePublishers = 0;

/** A route publishing derived decisions owns a lifecycle lease. The last
 * publisher leaving clears every authority-bearing singleton immediately, so
 * Notifications/Backup cannot re-stamp a former route's plan as current. */
export function retainDerivedSharePublisher(): () => void {
  activePublishers += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    activePublishers = Math.max(0, activePublishers - 1);
    if (activePublishers === 0) clearDerivedDecisionShares();
  };
}

// v11.22.0: latest Data Quality summary (Today fetch → pack/snapshot readers).
export interface DataQualityShare {
  overallStatus: string; overallStatusJa: string;
  topIssuesJa: string[]; expectedDisabledJa: string[];
  // v12.1.7: 2x準備の一行(Pack用)
  twoXReadinessJa?: string;
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
  // v12.1.3: Research Power(Gemini基準比)+矛盾警告+ソースカバレッジ要約
  researchPowerJa?: string; researchPowerVerdictJa?: string;
  contradictionWarningsJa?: string[];
  sourceCoverageJa?: string;
  // v12.1.4: 具体ソース欠落と仮説の分離要約
  gapGroupsJa?: string;
  // v12.1.5: 結論/因果/一次ソース
  conclusionJa?: string; causalJa?: string; primarySourceJa?: string;
  // v12.1.6: Gemini基準の校正状態
  baselineJa?: string;
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

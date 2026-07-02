// Device-local judgment log — ARGUS's first "memory". One entry per JST date
// (latest wins), recorded whenever the Today page composes a LIVE/PARTIAL
// judgment (mock is never logged — no fake history). This is what makes
// "what changed since yesterday?" and future outcome-tracking possible.
// localStorage only: per device, no cross-device sync (honest limitation).

import type { ActionKey, RiskLevel } from '../types/action';
import { markLocalEdit } from './vault';

export interface JudgmentLogEntry {
  date: string;              // JST YYYY-MM-DD
  overall: ActionKey;
  risk: RiskLevel;
  posture: string;           // EVENT_WAIT / RISK_OFF / ...
  confidence: number | null; // regime confidence 0..1 (null if unavailable)
  summary: string;
  phase: 'live' | 'partial';
  updatedAt: number;
}

const KEY = 'argus.judgmentLog.v1';
const MAX_ENTRIES = 180; // ~ 9 months of trading days

export function readJudgmentLog(): JudgmentLogEntry[] {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? (JSON.parse(raw) as JudgmentLogEntry[]) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

/** Upsert today's entry (keyed by JST date), newest last. */
export function recordJudgment(entry: JudgmentLogEntry): void {
  try {
    const log = readJudgmentLog().filter((e) => e.date !== entry.date);
    log.push(entry);
    log.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    localStorage.setItem(KEY, JSON.stringify(log.slice(-MAX_ENTRIES)));
    markLocalEdit();   // device-data edit → cloud-sync push (v11.3.3)
  } catch {
    /* quota / private mode — memory is best-effort */
  }
}

/** Most recent entry strictly BEFORE the given date (i.e. "yesterday's call"). */
export function previousJudgment(beforeDate: string): JudgmentLogEntry | null {
  const log = readJudgmentLog();
  for (let i = log.length - 1; i >= 0; i--) {
    if (log[i].date < beforeDate) return log[i];
  }
  return null;
}

/** Last N entries, newest first (for the compact history strip). */
export function recentJudgments(n: number): JudgmentLogEntry[] {
  return readJudgmentLog().slice(-n).reverse();
}

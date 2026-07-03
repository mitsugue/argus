// ARGUS V11.5.3 — client-side news freshness (mirrors argus_news_freshness.py).
// Old news is 過去材料 — never presented as the current-move explanation.

export interface NewsFreshness {
  ageHours: number | null;
  freshness: 'fresh' | 'recent' | 'stale' | 'old' | 'unknown_time';
  eligibleAsPrimaryLead: boolean;
  role?: string;
  staleReasonJa?: string;
}

/** Compute freshness from a timestamp (ISO string or unix seconds). */
export function classifyFreshness(ts: string | number | null | undefined): NewsFreshness {
  let ms: number | null = null;
  if (typeof ts === 'number' && ts > 0) ms = ts * 1000;
  else if (typeof ts === 'string' && ts) {
    const p = Date.parse(ts);
    if (!Number.isNaN(p)) ms = p;
  }
  if (ms === null) {
    return { ageHours: null, freshness: 'unknown_time', eligibleAsPrimaryLead: false };
  }
  const age = Math.max(0, (Date.now() - ms) / 3_600_000);
  if (age <= 6) return { ageHours: age, freshness: 'fresh', eligibleAsPrimaryLead: true };
  if (age <= 24) return { ageHours: age, freshness: 'recent', eligibleAsPrimaryLead: true };
  if (age <= 72) return { ageHours: age, freshness: 'stale', eligibleAsPrimaryLead: false };
  return { ageHours: age, freshness: 'old', eligibleAsPrimaryLead: false };
}

/** Chip text: 過去材料(N日前) / 過去材料寄り(Nh前) / N時間前 / 時刻不明. */
export function freshnessLabelJa(f: NewsFreshness | undefined | null): string {
  if (!f) return '';
  const h = f.ageHours;
  switch (f.freshness) {
    case 'old': return h != null ? `過去材料(${Math.floor(h / 24)}日前)` : '過去材料';
    case 'stale': return h != null ? `過去材料寄り(${Math.floor(h)}時間前)` : '過去材料寄り';
    case 'unknown_time': return '時刻不明';
    default:
      if (h == null) return '';
      return h >= 1 ? `${Math.floor(h)}時間前` : '1時間以内';
  }
}

/** True when the item must be demoted to 過去材料 in the UI. */
export function isPastMaterial(f: NewsFreshness | undefined | null): boolean {
  return !!f && (f.freshness === 'old' || f.freshness === 'stale');
}

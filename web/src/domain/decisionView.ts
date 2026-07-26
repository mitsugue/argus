// Shared decision semantics for every decision surface.
//
// Components render this contract; they must not invent an additional action,
// reason or probability. The contract deliberately separates an owner's
// existing position from a prospective entry.

export type EvidenceState =
  | 'VERIFIED_FACT'
  | 'SUPPORTED_HYPOTHESIS'
  | 'UNRESOLVED'
  | 'UNAVAILABLE'
  | 'STALE'
  | 'CONFLICT';

export type DataState = 'LIVE' | 'PARTIAL' | 'STALE' | 'UNAVAILABLE' | 'CONFLICT';

export interface DecisionView {
  primaryAction: string;
  ownerAction: string;
  entryAction: string;
  reason: string;
  nextCheck: string;
  changeCondition: string;
  evidenceState: EvidenceState;
  dataState: DataState;
  asOf: string | null;
}

export interface EvidenceTruth {
  state: EvidenceState;
  source: string | null;
  asOf: string | null;
  confirmed: string[];
  missing: string[];
  nextCheck: string | null;
  alternative: string | null;
}

export interface ProbabilityProvenance {
  method: string | null;
  sampleSize: number | null;
  calibration: string | null;
  outcomeDefinition: string | null;
  asOf: string | null;
}

export interface ProbabilityDisplay {
  showPercent: boolean;
  percentText: string | null;
  qualitative: '優勢' | '中立' | '条件付き' | '判定保留';
  reason: 'verified_probability' | 'provenance_incomplete';
}

const SEMANTIC_PATTERNS: Array<[string, RegExp]> = [
  ['exit', /EXIT|撤退/],
  ['trim', /TRIM|縮小|リスク縮小/],
  ['review', /REVIEW|再点検|要点検|リスク確認/],
  ['wait', /WAIT|PAUSE|様子見|待機|状況待ち|条件待ち|見送り/],
  ['hold', /HOLD|保有継続|維持/],
  ['no-entry', /新規.*(禁止|停止|見送り)|新規禁止/],
  ['no-add', /(買い増し|追加).*(禁止|停止|しない)/],
];

export function semanticDecisionKey(value: string | null | undefined): string {
  const text = String(value ?? '').toUpperCase()
    .replace(/[・／/、。\s()[\]（）]/g, '');
  if (!text) return '';
  const keys = SEMANTIC_PATTERNS
    .filter(([, pattern]) => pattern.test(text))
    .map(([key]) => key);
  return keys.length ? [...new Set(keys)].sort().join(':') : text;
}

export function duplicateDecisionKeys(values: Array<string | null | undefined>): string[] {
  const counts = new Map<string, number>();
  for (const value of values) {
    const key = semanticDecisionKey(value);
    if (!key) continue;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()].filter(([, count]) => count > 1).map(([key]) => key);
}

export function normalizeDataState(value: string | null | undefined): DataState {
  const state = String(value ?? '').trim().toUpperCase();
  if (state === 'LIVE' || state === 'FRESH' || state === 'VERIFIED') return 'LIVE';
  if (state === 'STALE' || state === 'DELAYED' || state === 'CACHED') return 'STALE';
  if (state === 'CONFLICT') return 'CONFLICT';
  if (state === 'PARTIAL' || state === 'MIXED') return 'PARTIAL';
  return 'UNAVAILABLE';
}

export function evidenceTruth(input: Partial<EvidenceTruth> & {
  state: EvidenceState;
}): EvidenceTruth {
  const truth: EvidenceTruth = {
    state: input.state,
    source: input.source?.trim() || null,
    asOf: input.asOf?.trim() || null,
    confirmed: (input.confirmed ?? []).filter(Boolean).slice(0, 3),
    missing: (input.missing ?? []).filter(Boolean).slice(0, 3),
    nextCheck: input.nextCheck?.trim() || null,
    alternative: input.alternative?.trim() || null,
  };
  if (truth.state === 'VERIFIED_FACT' && (!truth.source || !truth.asOf)) {
    return { ...truth, state: 'UNRESOLVED' };
  }
  if (truth.state === 'STALE' && !truth.asOf) {
    return { ...truth, state: 'UNAVAILABLE' };
  }
  return truth;
}

export function probabilityDisplay(
  value: number | null | undefined,
  provenance?: Partial<ProbabilityProvenance> | null,
): ProbabilityDisplay {
  const hasCompleteProvenance = Number.isFinite(value)
    && !!provenance?.method?.trim()
    && Number.isInteger(provenance.sampleSize)
    && (provenance.sampleSize ?? 0) > 0
    && !!provenance.calibration?.trim()
    && !!provenance.outcomeDefinition?.trim()
    && !!provenance.asOf?.trim();
  if (hasCompleteProvenance) {
    const percent = Math.max(0, Math.min(100, Number(value)));
    return {
      showPercent: true,
      percentText: `${Math.round(percent)}%`,
      qualitative: percent >= 45 ? '優勢' : percent >= 25 ? '中立' : '条件付き',
      reason: 'verified_probability',
    };
  }
  const numeric = Number.isFinite(value) ? Number(value) : null;
  return {
    showPercent: false,
    percentText: null,
    qualitative: numeric == null ? '判定保留'
      : numeric >= 45 ? '優勢' : numeric >= 25 ? '中立' : '条件付き',
    reason: 'provenance_incomplete',
  };
}

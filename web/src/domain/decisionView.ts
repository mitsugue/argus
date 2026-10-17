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
  reason: 'verified_probability' | 'provenance_incomplete' | 'invalid_probability';
}

export type ConfidenceDisplay = '高' | '中' | '低' | '判定保留';

const SEMANTIC_PATTERNS: Array<[string, RegExp]> = [
  ['exit', /EXIT|撤退/],
  ['trim', /TRIM|縮小|リスク縮小/],
  ['review', /REVIEW|再点検|要点検|リスク確認/],
  ['wait', /WAIT|PAUSE|様子見|待機|状況待ち|条件待ち|見送り/],
  ['hold', /HOLD|保有継続|維持/],
  ['no-entry', /新規.*(禁止|停止|見送り)|新規禁止/],
  ['no-add', /(買い増し|追加).*(禁止|停止|しない)/],
  ['enter', /ENTER|新規可|新規.*可能/],
  ['add', /(買い増し|追加).*(可|可能)/],
];

const TRUTH_TEXT_MAX = 64;

function compactTruthText(value: string | null | undefined,
                          maxLength = TRUTH_TEXT_MAX): string | null {
  const clean = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!clean) return null;
  return clean.length <= maxLength ? clean : `${clean.slice(0, maxLength - 1)}…`;
}

function compactTruthList(values: string[] | undefined, limit: number): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values ?? []) {
    const compact = compactTruthText(value);
    if (!compact) continue;
    const key = compact.toLocaleLowerCase('ja');
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(compact);
    if (result.length >= limit) break;
  }
  return result;
}

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

/** Canonical decision surfaces may expose one primary conclusion plus three
 * differently-scoped fields. Narrative fields must not repeat the primary
 * conclusion or each other. Owner/entry actions are intentionally excluded:
 * their separate roles are part of the DecisionView contract. */
export function duplicateDecisionViewKeys(view: DecisionView): string[] {
  return duplicateDecisionKeys([
    view.primaryAction, view.reason, view.nextCheck, view.changeCondition,
  ]);
}

/** Fail-closed contradiction audit for the canonical DecisionView. */
export function contradictoryDecisionStates(view: DecisionView): string[] {
  const primary = new Set(semanticDecisionKey(view.primaryAction).split(':'));
  const owner = new Set(semanticDecisionKey(view.ownerAction).split(':'));
  const entry = new Set(semanticDecisionKey(view.entryAction).split(':'));
  const contradictions: string[] = [];
  if ((primary.has('exit') || primary.has('trim'))
      && (owner.has('hold') || owner.has('add'))) {
    contradictions.push('owner_action_conflicts_with_primary');
  }
  if ([...primary].some((key) =>
    ['exit', 'trim', 'review', 'wait', 'no-entry'].includes(key))
      && entry.has('enter')) {
    contradictions.push('entry_action_conflicts_with_primary');
  }
  if (view.evidenceState === 'VERIFIED_FACT' && !view.asOf) {
    contradictions.push('verified_evidence_missing_as_of');
  }
  return contradictions;
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
    source: compactTruthText(input.source, 80),
    asOf: input.asOf?.trim() || null,
    confirmed: compactTruthList(input.confirmed, 3),
    missing: compactTruthList(input.missing, 2),
    nextCheck: compactTruthText(input.nextCheck),
    // A "best hypothesis" is meaningful only when the state explicitly says
    // that evidence supports one. UNRESOLVED must not simultaneously claim an
    // influential candidate.
    alternative: input.state === 'SUPPORTED_HYPOTHESIS'
      ? compactTruthText(input.alternative) : null,
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
  const numeric = Number.isFinite(value) ? Number(value) : null;
  const validRange = numeric != null && numeric >= 0 && numeric <= 100;
  const hasCompleteProvenance = validRange
    && !!provenance?.method?.trim()
    && Number.isInteger(provenance.sampleSize)
    && (provenance.sampleSize ?? 0) > 0
    && !!provenance.calibration?.trim()
    && !!provenance.outcomeDefinition?.trim()
    && !!provenance.asOf?.trim();
  if (hasCompleteProvenance) {
    return {
      showPercent: true,
      percentText: `${Math.round(numeric!)}%`,
      qualitative: numeric! >= 45 ? '優勢' : numeric! >= 25 ? '中立' : '条件付き',
      reason: 'verified_probability',
    };
  }
  return {
    showPercent: false,
    percentText: null,
    qualitative: !validRange ? '判定保留'
      : numeric >= 45 ? '優勢' : numeric >= 25 ? '中立' : '条件付き',
    reason: numeric != null && !validRange
      ? 'invalid_probability' : 'provenance_incomplete',
  };
}

/** Confidence without a calibration contract is a qualitative ordering, not a
 * probability. Keep the value useful without manufacturing decimal precision. */
export function confidenceDisplay(value: number | null | undefined): ConfidenceDisplay {
  if (!Number.isFinite(value) || Number(value) < 0 || Number(value) > 1) {
    return '判定保留';
  }
  if (Number(value) >= 0.7) return '高';
  if (Number(value) >= 0.4) return '中';
  return '低';
}

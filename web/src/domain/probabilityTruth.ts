export type DirectionProbabilities = { UP: number; RANGE: number; DOWN: number };

export interface ProbabilityHoldoutEvidence {
  start: string;
  end: string;
  brierSkill: number | null;
}

export interface ProbabilityTruthEvidence {
  serverEligible: boolean;
  oosEffectiveN: number | null;
  ruleEffectiveN: number | null;
  holdouts: ProbabilityHoldoutEvidence[];
  beatsUnconditional: boolean | null;
  beatsMomentum: boolean | null;
  wilsonHalfWidthPt: number | null;
  ece: number | null;
  breadthLagTradingDays: number | null;
  unresolvedPartitionCount: number | null;
  duplicateCount: number | null;
}

export type DirectionalLean = 'UP' | 'RANGE' | 'DOWN' | 'UNRESOLVED';
export type EvidenceStrength = '高' | '中' | '低';

export interface ProbabilityTruthResult {
  exactPercentageAllowed: boolean;
  reasonCodes: string[];
  directionalLean: DirectionalLean;
  directionalLeanJa: string;
  evidenceStrength: EvidenceStrength;
  effectiveN: number | null;
  uncertaintyJa: string;
  label: 'EXPERIMENTAL';
}

const VALID_DIRECTIONS: Array<keyof DirectionProbabilities> = ['UP', 'RANGE', 'DOWN'];

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function validProbabilities(value: DirectionProbabilities | null | undefined): value is DirectionProbabilities {
  if (!value) return false;
  const values = VALID_DIRECTIONS.map((key) => finiteNumber(value[key]));
  if (!values.every((item) => item != null && item >= 0 && item <= 100)) return false;
  return Math.abs(values.reduce<number>((sum, item) => sum + Number(item), 0) - 100) <= 0.5;
}

function nonOverlappingSkilledHoldouts(holdouts: ProbabilityHoldoutEvidence[]): boolean {
  const valid = holdouts
    .filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.start)
      && /^\d{4}-\d{2}-\d{2}$/.test(row.end)
      && row.start <= row.end
      && finiteNumber(row.brierSkill) != null
      && (row.brierSkill ?? 0) >= 0.05)
    .sort((left, right) => left.start.localeCompare(right.start));
  for (let left = 0; left < valid.length; left += 1) {
    for (let right = left + 1; right < valid.length; right += 1) {
      if (valid[left].end < valid[right].start || valid[right].end < valid[left].start) return true;
    }
  }
  return false;
}

function lean(probabilities: DirectionProbabilities | null | undefined): DirectionalLean {
  if (!validProbabilities(probabilities)) return 'UNRESOLVED';
  const ranked = VALID_DIRECTIONS
    .map((key) => ({ key, value: probabilities[key] }))
    .sort((left, right) => right.value - left.value);
  if (ranked[0].value === ranked[1].value) return 'UNRESOLVED';
  return ranked[0].key;
}

function leanJa(value: DirectionalLean): string {
  if (value === 'UP') return '上方向の傾向';
  if (value === 'DOWN') return '下方向への警戒';
  if (value === 'RANGE') return 'レンジ傾向';
  return '方向判定保留';
}

function uncertainty(reasonCodes: string[]): string {
  // Universal-first ordering (v13.5.14): the holdout/baseline reasons apply to
  // every instrument; breadth applies to JP conditioning only, so it must not
  // headline a US instrument's caveat when its lag simply is not measured.
  if (reasonCodes.includes('holdout_skill_unverified')) return '独立holdoutで再現性を証明できていません';
  if (reasonCodes.includes('breadth_freshness_unverified')) return 'breadth鮮度を証明できていません';
  if (reasonCodes.includes('baseline_dominance_unverified')) return '無条件・momentum基準への優位を証明できていません';
  if (reasonCodes.includes('partition_integrity_unverified')) return 'partition／重複整合性が未解決です';
  if (reasonCodes.includes('sample_below_threshold')) return '有効標本が表示基準未満です';
  if (reasonCodes.length) return '確率校正の表示条件が未充足です';
  return '表示条件を満たしています';
}

export function evaluateProbabilityTruth(
  evidence: ProbabilityTruthEvidence,
  probabilities?: DirectionProbabilities | null,
): ProbabilityTruthResult {
  const reasons: string[] = [];
  if (!evidence.serverEligible) reasons.push('server_eligibility_failed');
  if ((evidence.oosEffectiveN ?? -1) < 100 || (evidence.ruleEffectiveN ?? -1) < 60) {
    reasons.push('sample_below_threshold');
  }
  if (!nonOverlappingSkilledHoldouts(evidence.holdouts)) reasons.push('holdout_skill_unverified');
  if (evidence.beatsUnconditional !== true || evidence.beatsMomentum !== true) {
    reasons.push('baseline_dominance_unverified');
  }
  if (evidence.wilsonHalfWidthPt == null || evidence.wilsonHalfWidthPt > 10) {
    reasons.push('wilson_interval_too_wide_or_missing');
  }
  if (evidence.ece == null || evidence.ece > 0.05) reasons.push('calibration_error_too_high_or_missing');
  if (evidence.breadthLagTradingDays == null || evidence.breadthLagTradingDays > 1) {
    reasons.push('breadth_freshness_unverified');
  }
  if (evidence.unresolvedPartitionCount !== 0 || evidence.duplicateCount !== 0) {
    reasons.push('partition_integrity_unverified');
  }
  if (!validProbabilities(probabilities)) reasons.push('probability_vector_invalid_or_missing');
  const effectiveValues = [evidence.oosEffectiveN, evidence.ruleEffectiveN]
    .filter((value): value is number => value != null && Number.isFinite(value));
  const directionalLean = lean(probabilities);
  const sampleReady = (evidence.oosEffectiveN ?? 0) >= 100
    && (evidence.ruleEffectiveN ?? 0) >= 60;
  const evidenceStrength: EvidenceStrength = reasons.length === 0 ? '高'
    : sampleReady && evidence.serverEligible ? '中' : '低';
  return {
    exactPercentageAllowed: reasons.length === 0,
    reasonCodes: reasons,
    directionalLean,
    directionalLeanJa: leanJa(directionalLean),
    evidenceStrength,
    effectiveN: effectiveValues.length ? Math.min(...effectiveValues) : null,
    uncertaintyJa: uncertainty(reasons),
    label: 'EXPERIMENTAL',
  };
}

export function unavailableProbabilityEvidence(input: {
  serverEligible?: boolean;
  oosEffectiveN?: number | null;
  ruleEffectiveN?: number | null;
} = {}): ProbabilityTruthEvidence {
  return {
    serverEligible: input.serverEligible === true,
    oosEffectiveN: finiteNumber(input.oosEffectiveN),
    ruleEffectiveN: finiteNumber(input.ruleEffectiveN),
    holdouts: [],
    beatsUnconditional: null,
    beatsMomentum: null,
    wilsonHalfWidthPt: null,
    ece: null,
    breadthLagTradingDays: null,
    unresolvedPartitionCount: null,
    duplicateCount: null,
  };
}

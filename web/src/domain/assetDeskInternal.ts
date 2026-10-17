import {
  evidenceTruth,
  type EvidenceState,
  type EvidenceTruth,
} from './decisionView';

export interface AssetPositionInput {
  held: boolean;
  quantity?: number | null;
  averageCost?: number | null;
  currentPrice?: number | null;
  portfolioConcentrationPct?: number | null;
  theme?: string | null;
  themeConcentrationPct?: number | null;
  eventLabels?: string[];
  volume?: number | null;
  ownerRiskLine?: number | null;
  support?: number | null;
  trimReviewCondition?: string | null;
}

export interface AssetPositionView {
  held: boolean;
  quantity: number | null;
  averageCost: number | null;
  currentPrice: number | null;
  currentValue: number | null;
  unrealizedPl: number | null;
  unrealizedPlPct: number | null;
  portfolioConcentrationPct: number | null;
  theme: string | null;
  themeConcentrationPct: number | null;
  breakEvenDistancePct: number | null;
  eventExposure: string | null;
  volume: number | null;
  ownerRiskLine: number | null;
  ownerRiskLineDistancePct: number | null;
  supportDistancePct: number | null;
  trimReviewCondition: string | null;
  unavailable: string[];
}

const positive = (value: number | null | undefined): number | null =>
  Number.isFinite(value) && Number(value) > 0 ? Number(value) : null;

const finite = (value: number | null | undefined): number | null =>
  Number.isFinite(value) ? Number(value) : null;

/**
 * Device-local position math only. It never invents a support level, risk
 * budget or liquidity verdict. Missing computations are disclosed once in the
 * `unavailable` row rather than repeated as placeholder cards.
 */
export function buildAssetPositionView(input: AssetPositionInput): AssetPositionView {
  const quantity = positive(input.quantity);
  const averageCost = positive(input.averageCost);
  const currentPrice = positive(input.currentPrice);
  const ownerRiskLine = positive(input.ownerRiskLine);
  const support = positive(input.support);
  const currentValue = quantity != null && currentPrice != null
    ? quantity * currentPrice : null;
  const cost = quantity != null && averageCost != null
    ? quantity * averageCost : null;
  const unrealizedPl = currentValue != null && cost != null
    ? currentValue - cost : null;
  const unrealizedPlPct = unrealizedPl != null && cost != null && cost > 0
    ? (unrealizedPl / cost) * 100 : null;
  const breakEvenDistancePct = currentPrice != null && averageCost != null
    ? ((averageCost / currentPrice) - 1) * 100 : null;
  const ownerRiskLineDistancePct = currentPrice != null && ownerRiskLine != null
    ? ((ownerRiskLine / currentPrice) - 1) * 100 : null;
  const supportDistancePct = currentPrice != null && support != null
    ? ((support / currentPrice) - 1) * 100 : null;
  const eventExposure = (input.eventLabels ?? []).filter(Boolean).slice(0, 2).join(' / ') || null;
  const unavailable: string[] = [];
  if (input.held && currentValue == null) unavailable.push('現在評価');
  if (input.held && unrealizedPl == null) unavailable.push('含み損益');
  if (breakEvenDistancePct == null) unavailable.push('損益分岐距離');
  if (finite(input.portfolioConcentrationPct) == null) unavailable.push('資産集中');
  if (finite(input.themeConcentrationPct) == null) unavailable.push('テーマ集中');
  if (supportDistancePct == null) unavailable.push('支持線距離');
  if (ownerRiskLine == null) unavailable.push('オーナーリスクライン');
  if (positive(input.volume) == null) unavailable.push('出来高');
  // A raw volume is useful evidence, but without a comparable baseline it is
  // not a liquidity warning. Keep that verdict explicitly unavailable.
  unavailable.push('流動性判定');
  unavailable.push('追加余力');

  return {
    held: input.held,
    quantity,
    averageCost,
    currentPrice,
    currentValue,
    unrealizedPl,
    unrealizedPlPct,
    portfolioConcentrationPct: finite(input.portfolioConcentrationPct),
    theme: input.theme?.trim() || null,
    themeConcentrationPct: finite(input.themeConcentrationPct),
    breakEvenDistancePct,
    eventExposure,
    volume: positive(input.volume),
    ownerRiskLine,
    ownerRiskLineDistancePct,
    supportDistancePct,
    trimReviewCondition: input.trimReviewCondition?.trim() || null,
    unavailable: [...new Set(unavailable)],
  };
}

export interface AssetEvidenceSource {
  label: string;
  asOf: string;
  freshness: 'current' | 'stale' | 'unknown';
}

export interface AssetEvidenceInput {
  state: EvidenceState;
  source?: string | null;
  asOf?: string | null;
  confirmed?: string[];
  hypothesis?: string | null;
  contradicting?: string[];
  missing?: string[];
  nextInvestigation?: string | null;
  sources?: Array<Partial<AssetEvidenceSource>>;
}

export interface AssetEvidenceView {
  truth: EvidenceTruth;
  contradicting: string[];
  sources: AssetEvidenceSource[];
}

const compact = (value: string | null | undefined, max = 64): string | null => {
  const clean = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!clean) return null;
  return clean.length <= max ? clean : `${clean.slice(0, max - 1)}…`;
};

export function buildAssetEvidenceView(input: AssetEvidenceInput): AssetEvidenceView {
  const truth = evidenceTruth({
    state: input.state,
    source: input.source,
    asOf: input.asOf,
    confirmed: input.confirmed,
    missing: input.missing,
    nextCheck: input.nextInvestigation,
    alternative: input.hypothesis,
  });
  const contradicting = input.state === 'CONFLICT'
    ? [...new Set((input.contradicting ?? []).map((item) => compact(item))
      .filter((item): item is string => !!item))].slice(0, 2)
    : [];
  const seen = new Set<string>();
  const sources: AssetEvidenceSource[] = [];
  for (const source of input.sources ?? []) {
    const label = compact(source.label, 48);
    const asOf = compact(source.asOf, 48);
    if (!label || !asOf) continue;
    const freshness = source.freshness === 'current' || source.freshness === 'stale'
      ? source.freshness : 'unknown';
    const key = `${label}|${asOf}|${freshness}`;
    if (seen.has(key)) continue;
    seen.add(key);
    sources.push({ label, asOf, freshness });
    if (sources.length >= 3) break;
  }
  return { truth, contradicting, sources };
}

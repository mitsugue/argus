import { SIGNALS, type DataQuality, type SignalCode } from './actionLevel';

export type ArgusFinalAction = 'BUY' | 'WAIT' | 'SELL';
export type ArgusMarket = 'JP' | 'US';

export interface ArgusFactor {
  key: 'TREND' | 'BREADTH' | 'FLOW' | 'CREDIT' | 'CLOSE' | 'RELATIVE' | 'VALUE';
  state: '↑' | '→' | '↓' | '△' | '—' | 'JP' | 'US' | 'HIGH' | 'LOW';
  source?: string;
}
export interface ArgusMarketDecisionInput {
  market: ArgusMarket;
  baseSignal: SignalCode;
  confidence: number | null;
  dataQuality: DataQuality;
  closingWindowSignal?: SignalCode | null;
  ownerPolicyLimit?: SignalCode | null;
  eventHardVeto?: boolean;
  globalRisk?: 'normal' | 'elevated' | 'critical';
  factors?: ArgusFactor[];
  evidence?: string[];
  methodVersion?: string;
  calculatedAt?: string;
}

export interface ArgusMarketDecision {
  market: ArgusMarket;
  finalAction: ArgusFinalAction;
  actionScore: number;
  internalAction: SignalCode;
  confidence: number | null;
  dataQuality: DataQuality;
  globalRisk: 'normal' | 'elevated' | 'critical';
  factors: ArgusFactor[];
  evidence: string[];
  methodVersion: string;
  calculatedAt: string;
}

const DATA_CAP: Record<DataQuality, number> = {
  LIVE: 1, PARTIAL: 0.6, DELAYED: 0.55, STALE: 0.45,
  MOCK: 0.35, UNKNOWN: 0.4, UNAVAILABLE: 0.3,
};

export function finalActionForScore(score: number): ArgusFinalAction {
  if (score <= 2) return 'SELL';
  if (score >= 7) return 'BUY';
  return 'WAIT';
}

function moreDefensive(a: SignalCode, b?: SignalCode | null): SignalCode {
  if (!b) return a;
  return SIGNALS[a].level <= SIGNALS[b].level ? a : b;
}

/**
 * The deterministic A.R.G.U.S. Engine display synthesis.
 * Every overlay is a one-way safety constraint: none can make the result more
 * bullish than the existing seven-stage action. No network or AI call occurs.
 */
export function synthesizeArgusDecision(input: ArgusMarketDecisionInput): ArgusMarketDecision {
  let signal = input.baseSignal;
  signal = moreDefensive(signal, input.closingWindowSignal);
  signal = moreDefensive(signal, input.ownerPolicyLimit);
  if (input.eventHardVeto) signal = moreDefensive(signal, 'PAUSE');
  if (input.dataQuality === 'UNAVAILABLE') signal = moreDefensive(signal, 'REVIEW');

  const score = SIGNALS[signal].level;
  const rawConfidence = input.confidence == null || !Number.isFinite(input.confidence)
    ? null : Math.max(0, Math.min(1, input.confidence));
  const confidence = rawConfidence == null ? null
    : Math.round(Math.min(rawConfidence, DATA_CAP[input.dataQuality]) * 100) / 100;

  return {
    market: input.market,
    finalAction: finalActionForScore(score),
    actionScore: score,
    internalAction: signal,
    confidence,
    dataQuality: input.dataQuality,
    globalRisk: input.globalRisk ?? 'normal',
    factors: [...(input.factors ?? [])].slice(0, 7),
    evidence: [...(input.evidence ?? [])].slice(0, 12),
    methodVersion: input.methodVersion ?? 'argus-engine-13.0.0',
    calculatedAt: input.calculatedAt ?? new Date().toISOString(),
  };
}

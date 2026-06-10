import type {
  ActionKey,
  AssetClass,
  Confidence,
  CoreActionKey,
  RiskLevel,
} from './action';

export type RegimeTag =
  | 'Risk On'
  | 'Risk Off'
  | 'Event Risk'
  | 'Cautious'
  | 'Mixed'
  | 'Rates Pressure'
  | 'Liquidity Tightening'
  | 'JPY Shock'
  | 'Gold Hedge'
  | 'Crypto Heat'
  | 'Capitulation'
  | 'Buyable Pullback';

export interface DailyJudgment {
  date: string;            // ISO YYYY-MM-DD
  overall: ActionKey;
  risk: RiskLevel;
  regime: RegimeTag[];     // 1–2 primary regime tags
  summary: string;         // one clear sentence
  reasons: string[];       // up to 3
  assetsToTouch: string[]; // short labels
  assetsToAvoid: string[]; // short labels
  nextCondition: string;   // what to watch for next
  updatedAt: number;       // ms epoch
}

export interface AssetActionCard {
  assetClass: AssetClass;
  displayName: string;     // human label (e.g., "US Individual Stocks")
  action: ActionKey | CoreActionKey;
  confidence: Confidence;
  risk: RiskLevel;
  reason: string;          // one-line reason
  dataPoints: string[];    // 2–4 short supporting points
  nextCondition: string;   // what to watch
}

export type EventKind =
  | 'BOJ'
  | 'FOMC'
  | 'CPI'
  | 'PCE'
  | 'NFP'
  | 'CB_SPEECH'
  | 'EARNINGS'
  | 'TREASURY'
  | 'GEOPOLITICAL'
  | 'REGULATORY'
  | 'CRYPTO';

export interface MarketEvent {
  id: string;
  kind: EventKind;
  title: string;
  at: number;              // ms epoch
  impact: RiskLevel;
  note?: string;
}

export interface CorePosition {
  symbol: string;
  name: string;
  market: 'JP' | 'US';
  action: CoreActionKey;
  reason: string;
}

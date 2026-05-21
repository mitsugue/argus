export type Region = 'asia' | 'middle-east' | 'us' | 'europe';

export interface GlobePillar {
  id: string;
  lat: number;
  lng: number;
  label: string; // city / market code
  intensity: number; // 0..1 — pillar height factor
  region: Region;
  color: 'cyan' | 'amber' | 'danger';
  country: string; // e.g. "Japan"
  countryCode: string; // ISO-3166 alpha-2, used for flag emoji
  source: string; // news outlet
  headline: string; // short news line
}

export interface PredictionRecord {
  id: string;
  timestamp: number;
  predicted: number;
  actual: number | null; // null = pending
  hit: boolean | null;
}

export interface TrackedSymbol {
  code: string;
  name: string;
  currentPrice: number;
  predictedPrice: number;
  actualPrice: number | null;
  predictedAt: number; // ms
  resolvesAt: number; // ms (10 min later)
  history: PredictionRecord[];
}

export interface AlertItem {
  id: string;
  symbol: string;
  title: string;
  detail: string;
  severity: 'info' | 'warn' | 'critical';
  createdAt: number;
}

export interface StickyNote {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  text: string;
  z: number;
  color: 'cyan' | 'amber';
}

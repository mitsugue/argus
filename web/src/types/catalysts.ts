// Mirrors the backend /api/argus/catalysts shape (Corporate Catalyst Layer v1).

export type SnapshotStatus = 'live' | 'partial' | 'mock';
export type CatalystRisk = 'low' | 'medium' | 'high';
export type ActionImpact = 'none' | 'caution' | 'avoid_chasing' | 'wait_for_event' | 'post_event_review';

export interface CatalystSource {
  name: string;
  status: string; // live | partial | unavailable | error | pending_addon
  lastUpdated?: string | null;
}

export interface CatalystEarnings {
  status: string;
  date: string | null;
  daysUntil: number;
  epsEstimate: number | null;
  revenueEstimate: number | null;
}

export interface CatalystFiling {
  source: string; form: string; filingDate: string | null;
  accessionNumber: string; url: string; status: string;
}
export interface CatalystNews {
  source: string; headline: string; publisher: string;
  publishedAt: string | null; url: string; status: string;
}
export interface CatalystDisclosure {
  source: string; type: string; date: string | null; title: string; status: string;
}

export interface CatalystItem {
  symbol: string;
  market: 'US' | 'JP';
  name: string;
  catalystRisk: CatalystRisk;
  summaryJa: string;
  earnings: CatalystEarnings;
  filings: CatalystFiling[];
  news: CatalystNews[];
  disclosures: CatalystDisclosure[];
  rationaleJa: string;
  actionImpact: ActionImpact;
  status: string;
}

export interface CatalystsSnapshot {
  status: SnapshotStatus;
  asOf: string;
  engineVersion: string;
  horizonDays: number;
  sources: CatalystSource[];
  items: CatalystItem[];
}

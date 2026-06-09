// GET /api/argus/integrations — public, secret-free integration-health summary.
// Shows which providers are configured / live / partial / missing / disabled /
// pending. Never contains key values. The public frontend never triggers AI.

export type IntegrationOverall = 'live' | 'partial' | 'degraded';
export type ProviderCategory = 'market_data' | 'news_catalyst' | 'ai' | 'flow_orderbook';
export type RuntimeStatus =
  | 'live' | 'partial' | 'mock' | 'missing' | 'disabled' | 'unknown'
  | 'no_cached_result' | 'pending' | 'pending_local_validation';

export interface IntegrationProvider {
  id: string;
  label: string;
  category: ProviderCategory;
  configured: boolean;
  runtimeStatus: RuntimeStatus;
  usedFor: string[];
  lastKnownStatus: string | null;
  notesJa: string;
}

export interface AiJudgmentHealth {
  enabled: boolean;
  openaiConfigured: boolean;
  geminiConfigured: boolean;
  adminTokenConfigured: boolean;
  hasCachedResult: boolean;
  cachedStatus: string;
  lastRunAt: string | null;
  publicGetStatus: string;
  truthStatus: string;
}

export interface IntegrationsSnapshot {
  status: IntegrationOverall;
  asOf: string;
  engineVersion: string;
  providers: IntegrationProvider[];
  aiJudgment: AiJudgmentHealth;
  nextRecommendedApis: string[];
}

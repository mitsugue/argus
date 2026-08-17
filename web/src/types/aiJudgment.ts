// Mirrors the backend /api/argus/ai-judgment shape (AI Judgment Layer v1).

export type AIStatus = 'live' | 'partial' | 'mock' | 'disabled' | 'no_cached_result';
export type AIView = 'confirm' | 'caution' | 'disagree' | 'unavailable';

export interface AIJudgmentLabel {
  symbol: string;
  market: 'US' | 'JP';
  ruleAction: string;
  aiFinalAction: string;
  aiView: AIView;
  confidence: number;
  risk: 'low' | 'medium' | 'high';
  reasonJa: string;
  whatCouldChangeJa: string;
  openaiReasonJa: string;
  geminiCheckJa: string;
  redFlags: string[];
  dataLimitations: string[];
  status: 'live' | 'partial' | 'mock';
}

export interface GroundingSource { title: string; url: string; }

export interface AIJudgment {
  status: AIStatus;
  asOf: string;
  engineVersion: string;
  runMode: string;
  models: { primary: string | null; checker: string | null };
  summaryJa: string;
  marketRiskJa: string;
  labels: AIJudgmentLabel[];
  globalRedFlags?: string[];
  groundingSources?: GroundingSource[];
}

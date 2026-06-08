// Mirrors the backend /api/argus/ai-judgment shape (AI Judgment Layer v1).

export type AIStatus = 'live' | 'partial' | 'mock' | 'disabled';
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

export interface AIJudgment {
  status: AIStatus;
  asOf: string;
  engineVersion: string;
  runMode: string;
  models: { primary: string | null; checker: string | null };
  summaryJa: string;
  marketRiskJa: string;
  labels: AIJudgmentLabel[];
}

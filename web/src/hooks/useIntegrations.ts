import { useEffect, useState } from 'react';
import type { IntegrationsSnapshot } from '../types/integrations';

export type IntegrationsPhase = 'connecting' | 'live' | 'partial' | 'degraded' | 'mock';

interface State {
  data: IntegrationsSnapshot | null;
  error: string | null;
  loading: boolean;
  phase: IntegrationsPhase;
}

// Mock fallback so the Guide always renders. Honest: everything unknown/missing
// when the backend is unreachable.
const MOCK_SNAPSHOT: IntegrationsSnapshot = {
  status: 'degraded',
  asOf: '',
  engineVersion: 'integrations-v1',
  providers: [
    { id: 'fred', label: 'FRED', category: 'market_data', configured: false, runtimeStatus: 'unknown', usedFor: ['rates', 'market-regime'], lastKnownStatus: null, notesJa: '金利・VIX・HY OASに使用。' },
    { id: 'jquants', label: 'J-Quants', category: 'market_data', configured: false, runtimeStatus: 'unknown', usedFor: ['japan-watchlist', 'catalysts'], lastKnownStatus: null, notesJa: '日本株価格・決算/開示メタデータに使用。' },
    { id: 'twelvedata', label: 'Twelve Data', category: 'market_data', configured: false, runtimeStatus: 'unknown', usedFor: ['us-watchlist', 'market-regime'], lastKnownStatus: null, notesJa: '米国株価格・ETFレジームproxyに使用。' },
    { id: 'finnhub', label: 'Finnhub', category: 'news_catalyst', configured: false, runtimeStatus: 'missing', usedFor: ['corporate-catalysts'], lastKnownStatus: null, notesJa: '未設定なら米国ニュース/決算カレンダーはpartial。' },
    { id: 'openai', label: 'OpenAI GPT-5.5', category: 'ai', configured: false, runtimeStatus: 'missing', usedFor: ['ai-judgment'], lastKnownStatus: null, notesJa: 'APIキーとAI_JUDGE_ENABLEDが必要。ChatGPT Proとは別請求。' },
    { id: 'gemini', label: 'Gemini', category: 'ai', configured: false, runtimeStatus: 'missing', usedFor: ['ai-judgment-double-check'], lastKnownStatus: null, notesJa: 'OpenAI判断の二重チェック用。' },
    { id: 'coingecko', label: 'CoinGecko', category: 'market_data', configured: false, runtimeStatus: 'pending', usedFor: ['crypto-watchlist'], lastKnownStatus: null, notesJa: '次候補。BTC/ETHのlive化に使う。' },
    { id: 'moomoo', label: 'moomoo OpenAPI', category: 'flow_orderbook', configured: false, runtimeStatus: 'pending_local_validation', usedFor: ['flow', 'orderbook', 'vwap', 'tape'], lastKnownStatus: null, notesJa: '短期精度向上の有力候補。ただし実機検証が必要。' },
  ],
  aiJudgment: {
    enabled: false, openaiConfigured: false, geminiConfigured: false, adminTokenConfigured: false,
    hasCachedResult: false, cachedStatus: 'none', lastRunAt: null, publicGetStatus: 'disabled', truthStatus: 'disabled',
  },
  nextRecommendedApis: ['coingecko-crypto-watchlist', 'alerts-scanner-live', 'moomoo-flow-vwap-orderbook', 'portfolio-exposure-layer', 'what-if-simulator'],
};

const ATTEMPT_TIMEOUT_MS = 9_000;

export function useIntegrations(): State {
  const [state, setState] = useState<State>({ data: null, error: null, loading: true, phase: 'connecting' });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ data: MOCK_SNAPSHOT, error: null, loading: false, phase: 'mock' });
      return;
    }
    const url = backend.replace(/\/$/, '') + '/api/argus/integrations';
    let cancelled = false;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ATTEMPT_TIMEOUT_MS);

    (async () => {
      try {
        const r = await fetch(url, { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as IntegrationsSnapshot;
        if (cancelled) return;
        setState({ data, error: null, loading: false, phase: data.status });
      } catch (err: unknown) {
        clearTimeout(timer);
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        setState({ data: MOCK_SNAPSHOT, error: msg, loading: false, phase: 'mock' });
      }
    })();

    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  return state;
}

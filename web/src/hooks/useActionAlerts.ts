import { useEffect, useState } from 'react';
import { actionAlerts as MOCK_CARDS } from '../mock/dashboard';
import type { AssetActionCard } from '../types/dashboard';
import type { ActionKey } from '../types/action';

// Live per-asset-class action cards from /api/argus/action-alerts (alerts-v1).
// Backend action strings use spaces; the UI ActionKey uses underscores.
export type ConnPhase = 'connecting' | 'live' | 'partial' | 'mock';

const TO_KEY: Record<string, ActionKey> = {
  EXIT: 'EXIT', TRIM: 'TRIM', WAIT: 'WAIT',
  'WAIT FOR PULLBACK': 'WAIT_FOR_PULLBACK', 'BUY DIP': 'BUY_DIP',
  ADD: 'ADD', HOLD: 'HOLD',
};

interface BackendCard {
  assetClass: string; displayName: string; action: string;
  confidence: 'low' | 'med' | 'high'; risk: 'low' | 'med' | 'high';
  reasonJa: string; dataPoints: string[]; nextConditionJa: string;
  status: 'live' | 'partial';
}

interface Snapshot {
  status: ConnPhase; asOf: string; engineVersion: string;
  posture: string; cards: BackendCard[];
}

interface State {
  cards: AssetActionCard[];
  posture: string | null;
  phase: ConnPhase;
  loading: boolean;
}

export function useActionAlerts(): State {
  const [state, setState] = useState<State>({
    cards: MOCK_CARDS, posture: null, phase: 'connecting', loading: true,
  });

  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) {
      setState({ cards: MOCK_CARDS, posture: null, phase: 'mock', loading: false });
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 9_000);
    (async () => {
      try {
        const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/action-alerts', { signal: ctrl.signal });
        clearTimeout(timer);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as Snapshot;
        if (cancelled) return;
        const cards: AssetActionCard[] = d.cards.map((c) => ({
          assetClass: c.assetClass as AssetActionCard['assetClass'],
          displayName: c.displayName,
          action: TO_KEY[c.action] ?? 'WAIT',
          confidence: c.confidence,
          risk: c.risk,
          reason: c.reasonJa,
          dataPoints: c.dataPoints,
          nextCondition: c.nextConditionJa,
        }));
        setState({ cards, posture: d.posture, phase: d.status, loading: false });
      } catch {
        clearTimeout(timer);
        if (!cancelled) setState({ cards: MOCK_CARDS, posture: null, phase: 'mock', loading: false });
      }
    })();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  return state;
}

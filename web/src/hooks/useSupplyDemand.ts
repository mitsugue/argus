import { useEffect, useState } from 'react';

// V11.10.0 Supply/Demand Intelligence (JP) — 「需給は良いのか悪いのか」に
// ランク+状態で答える。数値はエンジンが読み、生数値はevidence(UI折りたたみ)。
// 状態評価であり売買指示ではない。

export interface SupplyDemandSignal {
  schemaVersion: string;
  id: string;
  symbol: string;
  market: string;
  name?: string;
  asOf: string;
  dataDate: string | null;
  supplyDemandRank: 'S' | 'A' | 'B' | 'C' | 'D' | 'E' | 'Unknown';
  rankJa: string;
  /** v11.14.0: 水準は方向と別表示(改善中でも重い時はA/S不可) */
  supplyDemandLevel?: 'light' | 'normal' | 'heavy' | 'very_heavy' | 'unknown';
  levelJa?: string;
  rankCapReason?: string | null;
  condition: string;
  conditionJa: string;
  chips: string[];
  direction: 'improving' | 'worsening' | 'stable' | 'mixed' | 'unknown';
  confidence: number;
  readabilityLabelJa: string;
  ownerReadableWhyJa: string;
  checkNextJa: string;
  actionImplication: string;
  actionImplicationJa: string;
  directness: string;
  directnessJa: string;
  evidence: Record<string, unknown>;
  missingEvidence: string[];
  sourceLimitNote: string;
  complianceNote: string;
}

// v12.0.4 (owner request): C/Unknownがmuted/faintで「かなり暗い」— 全ランクを
// ダーク背景で読める明色に固定(状態の意味は不変・色だけ)。
export const RANK_TONE: Record<string, string> = {
  S: '#34d399', A: '#6ee7b7', B: '#67e8f9',
  C: '#e2e8f0', D: '#fbbf24', E: '#f87171',
  Unknown: '#94a3b8',
};

interface State { signals: SupplyDemandSignal[]; loading: boolean; }

export function useSupplyDemandList(): State {
  const [state, setState] = useState<State>({ signals: [], loading: true });
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) { setState({ signals: [], loading: false }); return; }
    let alive = true;
    const load = () => {
      fetch(`${backend.replace(/\/$/, '')}/api/argus/supply-demand`)
        .then((r) => r.json())
        .then((d) => {
          if (!alive) return;
          // 429/error bodies have no signals array — keep the last good list
          // instead of wiping the section blank (owner report 2026-07-04).
          if (Array.isArray(d.signals)) setState({ signals: d.signals as SupplyDemandSignal[], loading: false });
          else setState((s) => ({ ...s, loading: false }));
        })
        .catch(() => { if (alive) setState((s) => ({ ...s, loading: false })); });
    };
    load();
    const iv = setInterval(load, 5 * 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return state;
}

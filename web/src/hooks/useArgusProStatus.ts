import { useEffect, useState } from 'react';

// ARGUS Pro foundation status (v11) — folds the four auditable status endpoints so the
// Guide can show, HONESTLY, what is actually active vs inactive/unavailable. Every field
// is backed by a backend endpoint; nothing here asserts capability the backend can't prove.

export interface CalibrationV4Status {
  schemaVersion?: string;
  artifactFound?: boolean;
  isActive?: boolean;
  reliabilityStage?: 'burn_in' | 'early_signal' | 'provisional' | 'regime_level';
  nPredictions?: number;
  nScored?: number;
  reasonJa?: string;
}
export interface DecisionValueStatus {
  schemaVersion?: string;
  phase?: 'not_configured' | 'engine_ready_no_records_yet' | 'shadow_recording_active' | 'scoring_active';
  privateStoreConfigured?: boolean;
  totalRecords?: number;
  scoredCount?: number;
  sampleStage?: string;
  reasonJa?: string;
  disclaimer?: string;
}
export interface DepthProof {
  schemaVersion?: string;
  summary?: {
    trueDepthLiveCount?: number;
    computedIndicatorsLiveCount?: number;
    unverifiedLiveCount?: number;
    requiresContractCount?: number;
    unavailableCount?: number;
  };
  proofNoteJa?: string;
}
export interface SourceCoverage {
  schemaVersion?: string;
  tiers?: { tier: string; itemCount: number; canGroundJudgment: boolean; weakSignal: boolean }[];
  summary?: { totalItems?: number; canGroundJudgmentItems?: number; weakSignalItems?: number; distinctTiers?: number };
}
export interface ArgusProStatus {
  calibration?: CalibrationV4Status;
  decisionValue?: DecisionValueStatus;
  depthProof?: DepthProof;
  sourceCoverage?: SourceCoverage;
}

export function useArgusProStatus(): ArgusProStatus {
  const [s, setS] = useState<ArgusProStatus>({});
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    const base = backend.replace(/\/$/, '');
    let alive = true;
    const get = (path: string, key: keyof ArgusProStatus) =>
      fetch(base + path).then((r) => r.json())
        .then((d) => { if (alive && d) setS((prev) => ({ ...prev, [key]: d })); })
        .catch(() => { /* keep last */ });
    const load = () => {
      get('/api/argus/calibration/v4/status', 'calibration');
      get('/api/argus/decision-value/status', 'decisionValue');
      get('/api/argus/market-depth/proof', 'depthProof');
      get('/api/argus/source-coverage', 'sourceCoverage');
    };
    load();
    const iv = setInterval(load, 120_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return s;
}

import { useCallback, useEffect, useState } from 'react';

// ARGUS V12.1.0 — Multi-Agent OSINT Engine のFE接続。
// 公開GET=cached-only / 公開POST(deep-dive)=決定論部分のみ+スカウトはキュー
// (外部AIは公開画面から絶対に起動しない — 管理側の定期実行で反映)。

export interface OsintVerifiedSource {
  titleJa: string; url?: string | null; sourceName?: string | null;
  publishedAt?: string | null; ageHours?: number | null;
  freshness: string; directness: string; verificationStatus: string;
  labelJa: string; primaryEligible: boolean; supportStrength: string;
}

export interface OsintInvestigation {
  id: string; symbol: string; assetName: string; asOf: string;
  mode: string; modeJa: string; trigger: string;
  investigationQuestionJa: string;
  queryPlan: { queryCount: number; direct: string[]; sector: string[];
    valueChain: string[]; globalCatalyst: string[]; negative: string[];
    extraFromOwner: string[] };
  agentRuns: { provider: string; status: string; claims: { titleJa?: string;
    url?: string; publishedAt?: string; directness?: string; verified?: boolean }[];
    missingEvidence: string[] }[];
  verifiedSources: OsintVerifiedSource[];
  rejectedSources: OsintVerifiedSource[];
  catalystVerdict: { verdict: string; verdictJa: string; primaryCauseJa: string | null;
    secondaryCausesJa: string[]; rejectedCausesJa: string[]; missingEvidenceJa: string[];
    confidence: string; directEvidencePresent: boolean; ownerReadableJa: string;
    whyThisMightBeWrongJa: string };
  contradictionReport: string[];
  coverageScore: Record<string, string> & { totalCoverage: string; totalCoverageJa: string };
  reliabilityScore: { overall: string; overallJa: string; verificationRate: number;
    directEvidence: boolean };
  benchmark: { argusCount: number; geminiCount: number; gptCount: number;
    overlapCount: number; geminiOnlyCount: number; gptOnlyCount: number;
    argusOnlyCount: number; missedByArgusCount: number; notesJa: string[] };
  ownerReadableSummaryJa: string;
  missingAreasJa: string[]; nextResearchJa: string[];
  privacyMode: string; costLabelJa?: string | null;
  /** v12.1.1: OSINT優位性メトリクス(未回収Gemini-onlyがあればexceeds不可)。 */
  superiority?: {
    argusVerifiedSourceCount: number; geminiSourceCount: number; gptSourceCount: number;
    geminiOnlyUnverifiedCount: number; gptOnlyUnverifiedCount: number;
    argusMissedImportantCount: number; verifiedOverlapCount: number;
    argusOnlyVerifiedCount: number; sourceVerificationRate: number;
    superiorityStatus: 'exceeds_gemini' | 'matches_gemini' | 'below_gemini' | 'insufficient_data';
    superiorityJa: string; ownerReadableVerdictJa: string; contextEdgeJa?: string | null;
    // v12.1.2: ギャップ台帳サマリ
    unresolvedImportant?: number;
    gapByStatus?: Record<string, number>;
    gapProgressLinesJa?: string[];
    unresolvedItemsJa?: string[];
    contextAdvantages?: string[];
  };
  /** v12.1.2: 全未回収に理由を付けた台帳。 */
  gapLedger?: {
    id: string; sourceTitle: string; sourceUrl?: string | null; sourceDomain?: string | null;
    providedBy: string; resolutionStatus: string; resolutionStatusJa: string;
    resolutionReasonJa: string; followUpQueries: string[]; ownerReadableJa: string;
  }[];
  budget?: { maxUrls?: number; maxLoops?: number; maxSeconds?: number; maxCostLabel?: string };
  /** v12.1.3 Phase 2: Research Power Score(生件数では2xにならない測定)。 */
  researchPower?: {
    components: Record<string, number>;
    geminiBaselineScore: number; gptBaselineScore: number; argusScore: number;
    argusVsGeminiRatio: number | null; argusVsBestExternalRatio: number | null;
    status: 'below_gemini' | 'matches_gemini' | 'exceeds_gemini' | 'exceeds_gemini_2x' | 'insufficient_data';
    statusJa: string; displayJa: string; ownerReadableVerdictJa: string;
    blockersJa: string[];
  };
  /** v12.1.3 Phase 6: 構造化矛盾レポート(旧contradictionReportはstring[]のまま)。 */
  contradictionReportV2?: {
    directEvidenceAbsent: boolean; themeInferenceOnly: boolean;
    priceOnlyNarrativeRisk: boolean; agentDisagreement: boolean;
    staleEvidencePresent: boolean; unsupportedClaims: number;
    ownerReadableWarningsJa: string[];
  };
  /** v12.1.3 Phase 4: 再利用可能な価値連鎖規則(無ければnull=捏造しない)。 */
  valueChainContext?: { theme: string; labelJa: string;
    rolesJa: Record<string, string>; cautionJa: string } | null;
  /** v12.1.3 Phase 3: 探索ソースユニバース(unavailableも可視)。 */
  sourceUniverse?: { key: string; labelJa: string; availability: string; noteJa: string }[];
}

export interface OsintProgress {
  stage: string; loop: number; maxLoops: number; notesJa: string[]; at: string;
  /** v12.1.3 Phase 5: Autopilot 14段階(failed_safe=嘘の完了を返さない)。 */
  autopilot?: {
    stages: { key: string; labelJa: string; state: 'done' | 'pending' | 'failed' }[];
    doneCount: number; totalStages: number;
    status: 'running' | 'completed' | 'failed_safe';
    currentStageJa: string | null; failReasonJa: string;
  };
}

interface State { inv: OsintInvestigation | null; loading: boolean; running: boolean;
  progress: OsintProgress | null; queuePosition: number | null; etaMin: number | null; }

export function useOsintInvestigation(symbol: string, market: string) {
  const [state, setState] = useState<State>({ inv: null, loading: true, running: false,
    progress: null, queuePosition: null, etaMin: null });
  const backend = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');

  const load = useCallback(() => {
    if (!backend) { setState((s) => ({ ...s, loading: false })); return; }
    fetch(`${backend}/api/argus/osint/investigation?symbol=${encodeURIComponent(symbol)}`)
      .then((r) => r.json())
      .then((d) => setState((s) => ({ ...s, inv: d.investigation ?? null, loading: false,
        progress: d.progress ?? null, queuePosition: d.queuePosition ?? null,
        etaMin: d.nextCronEtaMin ?? null })))
      .catch(() => setState((s) => ({ ...s, loading: false })));
  }, [backend, symbol]);

  useEffect(() => { load(); }, [load]);

  const runDeepDive = useCallback(async (privacyMode: 'redacted' | 'owner_context' | 'full_private') => {
    if (!backend) return null;
    setState((s) => ({ ...s, running: true }));
    try {
      const r = await fetch(`${backend}/api/argus/osint/deep-dive`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, market, mode: 'deep', privacyMode }),
      });
      const d = await r.json();
      setState((s) => ({ ...s, inv: d.investigation ?? s.inv, running: false,
        progress: d.progress ?? s.progress, queuePosition: d.queuePosition ?? s.queuePosition,
        etaMin: d.nextCronEtaMin ?? s.etaMin }));
      return d;
    } catch {
      setState((s) => ({ ...s, running: false }));
      return null;
    }
  }, [backend, symbol, market]);

  const verifyGaps = useCallback(async () => {
    if (!backend) return null;
    try {
      const r = await fetch(`${backend}/api/argus/osint/verify-gaps`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol }),
      });
      const d = await r.json();
      if (d.investigation) setState((s) => ({ ...s, inv: d.investigation }));
      return d;
    } catch { return null; }
  }, [backend, symbol]);

  const verifyUrl = useCallback(async (url: string) => {
    if (!backend || !url) return null;
    try {
      const r = await fetch(`${backend}/api/argus/osint/url-verify`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      return await r.json();
    } catch { return null; }
  }, [backend]);

  const postTerms = useCallback(async (terms: string[]) => {
    if (!backend || !terms.length) return;
    try {
      await fetch(`${backend}/api/argus/osint/terms`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, terms: terms.slice(0, 8) }),
      });
    } catch { /* enqueue-only — 失敗しても静かに */ }
  }, [backend, symbol]);

  return { ...state, reload: load, runDeepDive, postTerms, verifyGaps, verifyUrl };
}

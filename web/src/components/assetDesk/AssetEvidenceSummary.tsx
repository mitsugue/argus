import React from 'react';
import { evidenceTruth, type EvidenceState } from '../../domain/decisionView';
import type { DeskCardData } from './types';

const STATE_JA: Record<EvidenceState, string> = {
  VERIFIED_FACT: '確認済み事実',
  SUPPORTED_HYPOTHESIS: '支持された仮説',
  UNRESOLVED: '原因未確定',
  UNAVAILABLE: '必要データなし',
  STALE: '前回値',
  CONFLICT: '証拠が矛盾',
};

function evidenceStateOf(d: DeskCardData): EvidenceState {
  const cause = d.incident?.moverCause?.causeStatus;
  if (cause === 'confirmed_cause') return 'VERIFIED_FACT';
  if (cause === 'probable_catalyst' || cause === 'candidate_catalyst') {
    return 'SUPPORTED_HYPOTHESIS';
  }
  if (d.decisionFirst.dataState === 'STALE') return 'STALE';
  if (d.decisionFirst.dataState === 'UNAVAILABLE') return 'UNAVAILABLE';
  if (d.decisionFirst.dataState === 'CONFLICT') return 'CONFLICT';
  return d.decisionFirst.evidenceState;
}

export const AssetEvidenceSummary: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const direct = d.sdg?.directnessJa;
  const truth = evidenceTruth({
    state: evidenceStateOf(d),
    source: d.incident?.moverCause?.causeStatus === 'confirmed_cause'
      ? '公式・時刻整合済みソース' : null,
    asOf: d.decisionFirst.asOf,
    confirmed: [
      d.quote?.changePct != null ? `価格反応 ${d.quote.changePct >= 0 ? '+' : ''}${d.quote.changePct.toFixed(1)}%` : null,
      direct ? `需給 ${direct}` : null,
      d.strat.volume != null && d.strat.volume > 0 ? `出来高 ${d.strat.volume.toLocaleString()}` : null,
    ].filter((item): item is string => !!item),
    missing: [
      ...(d.incident?.missingData ?? []),
      ...d.strat.dataLimitations,
    ].slice(0, 3),
    nextCheck: d.decisionFirst.nextCheck,
    alternative: d.incident?.moverCause?.bestLeadJa ?? null,
  });

  return (
    <div className="ad-evidence-summary" data-evidence-state={truth.state}>
      <header>
        <span>EVIDENCE STATE</span>
        <strong>{STATE_JA[truth.state]}</strong>
        {truth.asOf && <time dateTime={truth.asOf}>{truth.asOf}</time>}
      </header>
      {truth.alternative && truth.state !== 'VERIFIED_FACT' && (
        <p><b>有力仮説</b><span>{truth.alternative}</span></p>
      )}
      {truth.confirmed.length > 0 && (
        <p><b>確認済み</b><span>{truth.confirmed.join(' / ')}</span></p>
      )}
      {truth.missing.length > 0 && (
        <p><b>不足</b><span>{truth.missing.join(' / ')}</span></p>
      )}
      {truth.nextCheck && (
        <p><b>次の確認</b><span>{truth.nextCheck}</span></p>
      )}
    </div>
  );
};

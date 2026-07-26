import React from 'react';
import { type EvidenceState } from '../../domain/decisionView';
import { buildAssetEvidenceView } from '../../domain/assetDeskInternal';
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
  const causeRefresh = d.incident?.moverCause?.freshness?.lastEvidenceRefreshAt;
  const causeSource = d.incident?.moverCause?.topCandidates
    ?.find((candidate) => candidate.source)?.source ?? null;
  const state = evidenceStateOf(d);
  const confirmedCause = d.incident?.moverCause?.causeStatus === 'confirmed_cause';
  const view = buildAssetEvidenceView({
    state,
    source: confirmedCause
      ? causeSource ?? '公式・時刻整合済みソース' : null,
    asOf: confirmedCause ? causeRefresh ?? null : d.decisionFirst.asOf,
    confirmed: [
      d.quote?.changePct != null ? `価格反応 ${d.quote.changePct >= 0 ? '+' : ''}${d.quote.changePct.toFixed(1)}%` : null,
      direct ? `需給 ${direct}` : null,
      d.strat.volume != null && d.strat.volume > 0 ? `出来高 ${d.strat.volume.toLocaleString()}` : null,
    ].filter((item): item is string => !!item),
    missing: [
      ...(d.incident?.missingData ?? []),
      ...d.strat.dataLimitations,
    ].slice(0, 3),
    nextInvestigation: d.decisionFirst.nextCheck,
    hypothesis: d.incident?.moverCause?.bestLeadJa ?? null,
    contradicting: state === 'CONFLICT'
      ? [d.incident?.moverCause?.whyNotConfirmedJa ?? '情報源の整合確認待ち'] : [],
    sources: [
      causeSource && causeRefresh
        ? {
            label: causeSource,
            asOf: causeRefresh,
            freshness: d.incident?.moverCause?.freshness?.isStale ? 'stale' : 'current',
          } as const
        : {},
      d.sdg?.asOf
        ? {
            label: 'Supply / Demand',
            asOf: d.sdg.asOf,
            freshness: d.decisionFirst.dataState === 'STALE' ? 'stale' : 'current',
          } as const
        : {},
      d.quote?.date
        ? {
            label: 'Market quote',
            asOf: d.quote.date,
            freshness: d.decisionFirst.dataState === 'STALE' ? 'stale' : 'current',
          } as const
        : {},
    ],
  });
  const truth = view.truth;

  return (
    <div className="ad-evidence-summary" data-evidence-state={truth.state}>
      <header>
        <span>EVIDENCE STATE</span>
        <strong>{STATE_JA[truth.state]}</strong>
        {truth.asOf && <time dateTime={truth.asOf}>{truth.asOf}</time>}
      </header>
      {truth.alternative && truth.state !== 'VERIFIED_FACT' && (
        <p><b>BEST CURRENT HYPOTHESIS</b><span>{truth.alternative}</span></p>
      )}
      {truth.confirmed.length > 0 && (
        <p><b>確認済み</b><span>{truth.confirmed.join(' / ')}</span></p>
      )}
      {truth.missing.length > 0 && (
        <p><b>MISSING EVIDENCE</b><span>{truth.missing.join(' / ')}</span></p>
      )}
      {view.contradicting.length > 0 && (
        <p><b>CONTRADICTING</b><span>{view.contradicting.join(' / ')}</span></p>
      )}
      {truth.nextCheck && (
        <p><b>NEXT INVESTIGATION</b><span>{truth.nextCheck}</span></p>
      )}
      {view.sources.length > 0 && (
        <div className="ad-evidence-sources">
          <b>SOURCES</b>
          {view.sources.map((source) => (
            <span key={`${source.label}-${source.asOf}`}>
              {source.label} · {source.asOf} · {source.freshness}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

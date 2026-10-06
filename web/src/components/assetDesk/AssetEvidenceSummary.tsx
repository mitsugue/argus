import React from 'react';
import { type EvidenceState } from '../../domain/decisionView';
import { buildAssetEvidenceView } from '../../domain/assetDeskInternal';
import { detailTime, uniqueDetailText } from './detailReading';
import type { DeskCardData } from './types';

const STATE_JA: Record<EvidenceState, string> = {
  VERIFIED_FACT: '確認済み事実',
  SUPPORTED_HYPOTHESIS: '原因候補（未確定）',
  UNRESOLVED: '原因未確定',
  // v13.5.53: 「必要データなし」 parses in Japanese as "no data is required" —
  // the opposite of the state it names, which is that the required evidence
  // could not be obtained.
  UNAVAILABLE: '必要な証拠が未取得',
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
    // 価格・出来高・需給の数値は、それぞれの専用欄に一度だけ表示する。
    confirmed: [],
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
            label: '需給',
            asOf: d.sdg.asOf,
            freshness: d.decisionFirst.dataState === 'STALE' ? 'stale' : 'current',
          } as const
        : {},
      d.quote?.date
        ? {
            label: '価格',
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
        <span>根拠の確認状況</span>
        <strong>{STATE_JA[truth.state]}</strong>
        {truth.asOf && <time dateTime={truth.asOf}>{detailTime(truth.asOf)}</time>}
      </header>
      {truth.alternative && truth.state !== 'VERIFIED_FACT' && (
        <p><b>原因の候補</b><span>{truth.alternative}</span></p>
      )}
      {truth.confirmed.length > 0 && (
        <p><b>確認した数値</b><span>{truth.confirmed.join(' / ')}</span></p>
      )}
      {truth.missing.length > 0 && (
        <p><b>不足している情報</b><span>{uniqueDetailText(truth.missing).join(' / ')}</span></p>
      )}
      {view.contradicting.length > 0 && (
        <p><b>食い違う情報</b><span>{view.contradicting.join(' / ')}</span></p>
      )}
      {truth.nextCheck && uniqueDetailText([truth.nextCheck], [d.decisionFirst.nextJa]).length > 0 && (
        <p><b>次の調査</b><span>{truth.nextCheck}</span></p>
      )}
      {view.sources.length > 0 && (
        <div className="ad-evidence-sources">
          <b>出典・時点</b>
          {view.sources.map((source) => (
            <span key={`${source.label}-${source.asOf}`}>
              {source.label} · {detailTime(source.asOf)} · {source.freshness === 'stale' ? '前回値' : source.freshness === 'current' ? '確認時点の値' : '時点未確認'}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

import React from 'react';
import { publishDataQuality } from '../lib/positionExposureShare';
import {
  usePublicDiagnostics, type PublicDiagnostics,
} from '../hooks/useSystemHealth';

const SERVICE_JA: Record<PublicDiagnostics['service']['overall'], string> = {
  ok: '稼働中',
  degraded: '一部確認が必要',
  unavailable: '状態を取得できません',
};

const FRESHNESS_JA: Record<PublicDiagnostics['freshness']['overall'], string> = {
  fresh: '新鮮',
  aging: '更新待ち',
  stale: '古いデータあり',
  unknown: '未確認',
  mixed: '混在',
};

export const PublicDiagnosticsPanel: React.FC = () => {
  const { diagnostics, loading, failed, refresh } = usePublicDiagnostics();
  React.useEffect(() => {
    if (!diagnostics) return;
    publishDataQuality({
      overallStatus: diagnostics.service.overall,
      overallStatusJa: SERVICE_JA[diagnostics.service.overall],
      topIssuesJa: diagnostics.service.overall === 'ok' ? [] : [
        `公開診断: ${SERVICE_JA[diagnostics.service.overall]} / 鮮度 ${FRESHNESS_JA[diagnostics.freshness.overall]}`,
      ],
      expectedDisabledJa: diagnostics.freshness.expectedDisabledCount
        ? [`仕様上無効なソース ${diagnostics.freshness.expectedDisabledCount}件`]
        : [],
    });
  }, [diagnostics]);

  return (
    <section id="settings-status" aria-label="Data quality status">
      {loading && <p className="cmd-alloc__note">公開診断を確認中…</p>}
      {failed && !loading && (
        <div className="card cmd-alloc">
          <p className="cmd-alloc__note">公開診断を取得できません。再読込してください。</p>
          <button type="button" onClick={() => void refresh()}>再読込</button>
        </div>
      )}
      {diagnostics && !loading && (
        <>
          <section>
            <div className="section-head">
              <span className="section-head__title">PUBLIC SERVICE STATUS</span>
            </div>
            <div className="card cmd-alloc">
              <p className="cmd-alloc__note">
                <b>{SERVICE_JA[diagnostics.service.overall]}</b>
                {' · '}liveness {diagnostics.service.liveness}
                {' · '}readiness {diagnostics.service.readiness}
              </p>
              <p className="cmd-alloc__note">
                Backend {diagnostics.service.backendVersion}
                {' · '}build {diagnostics.service.buildSha?.slice(0, 12) ?? 'unknown'}
              </p>
              <p className="cmd-alloc__note">生成時刻 {diagnostics.generatedAt}</p>
            </div>
          </section>
          <section>
            <div className="section-head">
              <span className="section-head__title">FRESHNESS SUMMARY</span>
            </div>
            <div className="card cmd-alloc">
              <p className="cmd-alloc__note">
                {FRESHNESS_JA[diagnostics.freshness.overall]}
                {' · '}fresh {diagnostics.freshness.sourceCounts.fresh}
                {' · '}aging {diagnostics.freshness.sourceCounts.aging}
                {' · '}stale {diagnostics.freshness.sourceCounts.stale}
                {' · '}unknown {diagnostics.freshness.sourceCounts.unknown}
              </p>
              <p className="cmd-alloc__note">
                仕様上無効 {diagnostics.freshness.expectedDisabledCount}件
              </p>
            </div>
          </section>
          <section>
            <div className="section-head">
              <span className="section-head__title">RECOVERY CLAIM</span>
            </div>
            <div className="card cmd-alloc">
              <p className="cmd-alloc__note">
                {diagnostics.recovery.mode} · {diagnostics.recovery.measurement}
              </p>
              <p className="cmd-alloc__note">
                Exact cold recovery: <b>{diagnostics.recovery.exactColdRecovery}</b>
                {' · '}Hard RPO claim: permitted={String(diagnostics.recovery.hardRpoClaimPermitted)}
              </p>
            </div>
          </section>
        </>
      )}
    </section>
  );
};

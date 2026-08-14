import React from 'react';
import { PageShell } from './PageShell';
import { publishDataQuality } from '../lib/positionExposureShare';

interface PublicDiagnostics {
  schemaVersion: 'argus-public-diagnostics-v1';
  generatedAt: string;
  service: {
    liveness: 'ok' | 'unavailable';
    readiness: 'ready' | 'not_ready';
    overall: 'ok' | 'degraded' | 'unavailable';
    backendVersion: string;
    buildSha: string | null;
  };
  freshness: {
    overall: 'fresh' | 'aging' | 'stale' | 'unknown' | 'mixed';
    sourceCounts: { fresh: number; aging: number; stale: number; unknown: number };
    expectedDisabledCount: number;
  };
  recovery: {
    mode: 'LEGACY_ONLY';
    measurement: 'SHADOW_INCOMPLETE';
    exactColdRecovery: 'NOT_PROVEN';
    hardRpoClaimPermitted: false;
  };
}

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
  const [diagnostics, setDiagnostics] = React.useState<PublicDiagnostics | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [failed, setFailed] = React.useState(false);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;

  const load = React.useCallback(() => {
    setLoading(true);
    if (!backend) {
      setFailed(true);
      setLoading(false);
      return;
    }
    fetch(backend.replace(/\/$/, '') + '/api/argus/data-quality/status')
      .then((response) => {
        if (!response.ok) throw new Error('public_diagnostics_unavailable');
        return response.json() as Promise<PublicDiagnostics>;
      })
      .then((value) => {
        if (value.schemaVersion !== 'argus-public-diagnostics-v1') {
          throw new Error('public_diagnostics_schema_invalid');
        }
        setDiagnostics(value);
        setFailed(false);
        publishDataQuality({
          overallStatus: value.service.overall,
          overallStatusJa: SERVICE_JA[value.service.overall],
          topIssuesJa: value.service.overall === 'ok' ? [] : [
            `公開診断: ${SERVICE_JA[value.service.overall]} / 鮮度 ${FRESHNESS_JA[value.freshness.overall]}`,
          ],
          expectedDisabledJa: value.freshness.expectedDisabledCount
            ? [`仕様上無効なソース ${value.freshness.expectedDisabledCount}件`]
            : [],
        });
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  }, [backend]);

  React.useEffect(() => { load(); }, [load]);

  return (
    <section id="settings-status" aria-label="Data quality status">
      {loading && <p className="cmd-alloc__note">公開診断を確認中…</p>}
      {failed && !loading && (
        <div className="card cmd-alloc">
          <p className="cmd-alloc__note">公開診断を取得できません。再読込してください。</p>
          <button type="button" onClick={load}>再読込</button>
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

export const DataQualityPage: React.FC = () => (
  <PageShell
    title="Data Quality"
    subtitle="公開画面では固定スキーマの稼働・鮮度・復旧ステータスだけを表示します。詳細な運用診断はサーバー間認証された管理経路へ移動しました。"
  >
    <PublicDiagnosticsPanel />
  </PageShell>
);

export default DataQualityPage;

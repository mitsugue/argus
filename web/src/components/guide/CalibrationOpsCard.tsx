import '../dashboard/Dashboard.css';
import React from 'react';

// Calibration Operations (v10.195) — is usable v4 capture actually happening, and
// can the clean epoch be activated? Read-only; states the truth or the blockers.
interface CalibOps {
  schemaVersion?: string;
  currentEpoch?: { active?: string; reliabilityStage?: string };
  v3Headline?: { days?: number; n?: number; hitRate?: number; brierMean?: number } | null;
  v4DryRun?: Record<string, unknown> | null;
  coverage?: { expected?: number; recorded?: number; missing?: string[]; layer1SessionCoverage?: number };
  marketClocks?: { clockVersion?: string; calendarVersion?: string };
  readiness?: { ready?: boolean; checks?: Record<string, boolean> };
  activationAllowed?: boolean;
  pendingJa?: string;
  noteJa?: string;
}

const CHECK_JA: Record<string, string> = {
  required_sensors_100pct: '必須センサー 100%',
  layer1_coverage_min_15_16: 'Layer1 被覆 ≥15/16',
  rolling_per_sensor_min_90pct: 'センサー別ローリング被覆 ≥90%',
  no_unresolved_write_failures: '書込失敗なし',
  no_stale_price_forecasts: '古い価格予測なし',
  cohort_definitions_finalized: 'コホート定義確定',
  scoring_tests_pass: '採点テスト通過',
};

export const CalibrationOpsCard: React.FC = () => {
  const [d, setD] = React.useState<CalibOps | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    const load = () => fetch(backend.replace(/\/$/, '') + '/api/argus/calibration/ops')
      .then((r) => r.json()).then((j) => { if (alive) setD(j); }).catch(() => {});
    load();
    const iv = setInterval(load, 5 * 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  if (!d) return null;
  const cov = d.coverage || {};
  const v4 = d.v4DryRun || {};
  const v4has = v4 && (v4 as { status?: string }).status !== 'no_v4_summary_yet' && Object.keys(v4).length > 0;
  const checks = d.readiness?.checks || {};
  return (
    <section className="calops">
      <div className="section-head">
        <span className="section-head__title">Calibration Operations</span>
        <span className="section-head__count">{d.currentEpoch?.reliabilityStage ?? '—'}</span>
      </div>
      <div className="card calops__card">
        <p className="calops__lead">
          校正は「待てば良くなる」のではなく、<b>正しい日付・被覆率・不変予測が記録できている時だけ</b>改善します。今の記録状態:
        </p>
        <div className="calops__grid">
          <div><span className="calops__k">v3 実績</span><span className="calops__v">
            {d.v3Headline ? `${d.v3Headline.days ?? '—'}営業日 / n=${d.v3Headline.n ?? '—'} · 的中${Math.round((d.v3Headline.hitRate ?? 0) * 100)}%` : '—'}
          </span></div>
          <div><span className="calops__k">v4 ドライラン</span><span className="calops__v">
            {v4has ? '記録中(calibration_v1)' : '生成前(平日ワークフロー後に出力)'}
          </span></div>
          <div><span className="calops__k">Layer1 被覆</span><span className="calops__v">
            {cov.recorded ?? '—'}/{cov.expected ?? 16}{(cov.missing && cov.missing.length) ? ` · 欠測: ${cov.missing.join(',')}` : ''}
          </span></div>
          <div><span className="calops__k">市場クロック</span><span className="calops__v">
            {d.marketClocks?.clockVersion ?? '—'} / {d.marketClocks?.calendarVersion ?? '—'}
          </span></div>
        </div>
        <div className="calops__ready">
          <div className="calops__ready-head">
            活性化の可否: <b className={d.activationAllowed ? 'calops__ok' : 'calops__no'}>
              {d.activationAllowed ? '要件充足(管理者操作で活性化可)' : 'まだ活性化できません'}
            </b>
          </div>
          <ul className="calops__checks">
            {Object.entries(checks).map(([k, ok]) => (
              <li key={k} className={ok ? 'calops__pass' : 'calops__fail'}>
                {ok ? '✓' : '×'} {CHECK_JA[k] ?? k}
              </li>
            ))}
          </ul>
        </div>
        {d.pendingJa && <p className="calops__note">保留中: {d.pendingJa}</p>}
      </div>
    </section>
  );
};

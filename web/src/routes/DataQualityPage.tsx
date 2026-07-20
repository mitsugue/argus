import React from 'react';
import { PageShell } from './PageShell';
import { useAssets } from '../hooks/useAssets';
import { assessBackupSafety } from '../lib/backupSafety';
import { latestStrategy, latestFireCore, latestPlans, latestScenarios,
  publishDataQuality } from '../lib/positionExposureShare';

// V11.22.0 — Admin / Data Quality Console。「今の判断は最新データに基づいて
// いるか」に運用者目線で答えるページ。取引機能ではない。
// サーバー側(公開redacted)の実測鮮度 + 端末側エンジンの実行状況を1画面に。
// 意図的な無効(JPリアルタイム/逆日歩/銘柄別空売り)は障害として扱わない。

interface Console {
  overallStatus: string; overallStatusJa: string;
  ownerReadableSummaryJa: string; topIssuesJa: string[]; nextChecksJa: string[];
  sourceHealth: { sourceName: string; status: string; freshnessBucket: string;
    lastSuccessAt: string | null; ownerReadableStatusJa: string;
    ownerReadableImpactJa: string; nextStepJa: string; isExpectedDisabled: boolean }[];
  engineHealth: { engineName: string; status: string; lastRunAt: string | null;
    ownerReadableImpactJa: string }[];
  bridgeHealth: Record<string, unknown> & { jpRealtimeNoteJa?: string | null };
  jpReadiness?: { jpRealtimeStatus: string; jpPermissionStatus: string;
    lastJPQuotePushAt: string | null; jpFallbackActive: boolean;
    usOnlyOverrideActive: boolean; activationReady: boolean | 'unknown';
    showActivationSteps: boolean; reasonJa: string | null; safeModeJa: string | null;
    activationConditionJa: string; ownerReadableStatusJa: string;
    nextStepJa: string; guardJa: string | null;
    // v12.0.4: moomoo側メンテナンス認知(オーナー確認済み事実のみ)
    jpApiMaintenanceSuspected?: boolean | 'unknown';
    jpFullBoardAppSubscriptionKnown?: boolean | 'unknown';
    jpOpenDOrderBookReady?: boolean | 'unknown';
    fullBoardNoteJa?: string | null; contextAsOf?: string | null;
    // v12.0.5: サポート正式確認+復旧情報
    jpApiMaintenanceConfirmed?: boolean | 'unknown';
    additionalSubscriptionRequired?: boolean | 'unknown';
    additionalSubscriptionNoteJa?: string | null;
    recoveryEtaJa?: string | null; postRecoveryActionJa?: string | null };
  osintHealth?: { geminiProviderConfigured: boolean; gptProviderConfigured: boolean;
    agentQueueDepth: number; lastDeepDiveAt: string | null; lastAgentsRunAt: string | null;
    canaryStatus: string; canaryMissedByArgus: number; canaryNoteJa: string; noteJa: string;
    // v12.1.1: 優位性/ベンチ/メモリ/パーサ
    superiorityLatest?: string; unresolvedGeminiOnlyTotal?: number;
    benchmarkWarnJa?: string | null; memoryRecords?: number;
    memoryPersisted?: boolean; parserWarnings?: number;
    capReachedCount?: number; benchmarkVerdictJa?: string;
    // v12.1.3: Research Power最新値+ソースユニバース(unavailableも可視)
    researchPowerLatest?: { symbol: string; status: string; statusJa: string;
      argusScore: number; geminiBaselineScore: number; ratio: number | null;
      displayJa: string } | null;
    sourceUniverse?: { total: number; live: number; viaAgents: number; unavailable: number;
      categories: { key: string; labelJa: string; availability: string; noteJa: string }[] };
    // v12.1.6: Gemini基準の校正状態
    geminiBaseline?: { baselineType: string; labelJa: string; runCount: number;
      medianScore: number | null; variance: number | null; confidence: string;
      lastCalibrationAt: string | null; twoXClaimAllowed: boolean; noteJa: string };
    // v12.1.7: 校正計画+2x準備レポート+ベンチ実行
    calibrationPlan?: { requiredCases: number; requiredRuns: number;
      currentCasesCovered: number; currentRuns: number; remainingRuns: number;
      estimatedCompletionJa: string; baselineConfidence: string;
      canClaim2x: boolean; progressPct: number; variance: number | null };
    twoXReadiness?: { overallStatus: string; overallJa: string;
      currentRatio: number | null; calibratedRatio: number | null;
      weakCases: { caseId: string; status: string; weakPillars: string[] }[];
      weakPillars: string[]; topBlockersJa: string[];
      fastestPathTo2xJa: string[]; recommendedNextEngineeringTasks: string[] };
    benchmarkRunsSummary?: { total: number; running: boolean; lastAt: string | null;
      recent: { caseId: string; status: string; ownerReadableJa: string | null }[];
      budget: { maxCasesPerInvocation: number; maxCostLabel: string } } };
  rebootSafety?: { systemRestartRequired: boolean | 'unknown';
    opendAutostartConfigured: boolean | 'unknown';
    bridgeAutostartConfigured: boolean | 'unknown';
    rebootSafe: boolean | 'unknown'; ownerReadableRiskJa: string; nextStepJa: string };
  expectedDisabled: { sourceName: string; reasonJa: string }[];
  privacyHealth: { publicLeakSafe: boolean; noteJa: string };
  publicLeakSafe: boolean;
  scheduledMission?: { lastScheduledTick: string | null; nextExpectedTick: string | null;
    lastDelaySeconds: number | null; lastDelayClassification: string;
    lastMissedWindowCount: number;
    currentMissionWindow: string | null; lastMissionWindowId: string | null;
    duplicateSuppressed: number; windowCount: number; scheduleOffsetMinute: number };
  buildSoak?: { soakId: string | null; state?: string; status: string;
    elapsedHours: number; requiredHours: number; heartbeatCount?: number;
    lastHeartbeatAt?: string | null; lastHeartbeatSource?: string | null;
    blockerJa?: string | null; ownerReadableJa: string };
  remoteJournalVerification?: { remoteCommitSha: string | null;
    committedAt: string | null; readBackAt: string | null; readBackVerified: boolean;
    pendingCount: number; acknowledgedCount: number; errorClass: string | null };
  outcomeRetry?: { unresolvedCount: number; nextRetryAt: string | null;
    retryCount: number; policyIntervalSeconds: number; expirySeconds: number;
    missingPriceIsZero: boolean };
}

const OVERALL_TONE: Record<string, string> = {
  ok: 'var(--value-positive)', degraded: 'var(--accent)', partial: 'var(--accent)',
  warning: 'var(--amber, #fbbf24)', critical: 'var(--value-negative)',
  unknown: 'var(--text-faint)',
};
const STATUS_TONE: Record<string, string> = {
  ok: 'var(--value-positive)', stale: 'var(--amber, #fbbf24)',
  degraded: 'var(--accent)', failed: 'var(--value-negative)',
  disabled_expected: 'var(--text-faint)', disabled_problem: 'var(--value-negative)',
  unknown: 'var(--text-faint)', stale_input: 'var(--amber, #fbbf24)', disabled: 'var(--text-faint)',
};
const BUCKET_JA: Record<string, string> = {
  fresh: '新鮮', recent: '最近', stale: '古い', very_stale: 'かなり古い', unknown: '不明',
};
const DELAY_JA: Record<string, string> = {
  on_time: '予定内', delayed: '遅延', severely_delayed: '大幅遅延', missed: '未実行窓あり', unknown: '未確認',
};
const SOAK_JA: Record<string, string> = {
  not_started: '開始待ち', running: '実行中', scheduler_delayed: 'スケジューラ遅延',
  verification_gap: '継続性確認待ち', interrupted: '中断', completed: '72時間完了',
};

export const DataQualityPage: React.FC = () => {
  const { assets } = useAssets();
  const [c, setC] = React.useState<Console | null>(null);
  const [err, setErr] = React.useState(false);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;

  const load = React.useCallback(() => {
    if (!backend) { setErr(true); return; }
    fetch(backend.replace(/\/$/, '') + '/api/argus/data-quality')
      .then((r) => r.json())
      .then((d: Console) => {
        setC(d); setErr(false);
        publishDataQuality({ overallStatus: d.overallStatus, overallStatusJa: d.overallStatusJa,
          topIssuesJa: d.topIssuesJa ?? [],
          expectedDisabledJa: (d.expectedDisabled ?? []).map((x) => `${x.sourceName}: ${x.reasonJa}`),
          twoXReadinessJa: d.osintHealth?.twoXReadiness
            ? `${d.osintHealth.twoXReadiness.overallJa}${d.osintHealth.twoXReadiness.currentRatio != null ? `(現在比 ${d.osintHealth.twoXReadiness.currentRatio.toFixed(2)}x)` : ''}`
            : undefined });
      })
      .catch(() => setErr(true));
  }, [backend]);
  React.useEffect(() => { load(); }, [load]);

  // 端末側エンジン(サーバーは内容を知らない — 実行の有無だけここで表示)
  const device = [
    { name: 'portfolio_strategy / fire_core', ok: !!latestStrategy(),
      note: latestFireCore()?.positions.length ? '投信追跡あり' : '投信メタ未入力あり' },
    { name: 'entry_exit_planning / scenario', ok: latestPlans().length > 0 && latestScenarios().length > 0,
      note: 'Todayを開くと計算されます' },
    { name: 'backup_safety', ok: true,
      note: (() => { try { const b = assessBackupSafety(assets); return `保護状態: ${b.protectionLevelJa}`; }
        catch { return '判定保留'; } })() },
  ];

  return (
    <PageShell
      title="Data Quality"
      subtitle="今の判断は最新データに基づいているか — ソース鮮度・エンジン状態・bridge・漏洩ガードを1画面で点検。古いデータのレイヤーは判断の確度を割り引いて読む。運用点検であり売買機能ではない。"
    >
      {err && (
        <p style={{ color: 'var(--value-negative)', fontSize: 12 }}>
          サーバーに接続できません。ネットワーク/Renderの状態を確認してください(このページ自体が疎通チェックです)。
        </p>
      )}
      {c && (
        <>
          {/* 1. 総合ステータス */}
          <section>
            <div className="section-head">
              <span className="section-head__title">OVERALL</span>
              <span className="section-head__count">運用点検 · 売買機能ではない</span>
            </div>
            <div className="card cmd-alloc">
              <p className="cmd-alloc__note" style={{ fontSize: 13 }}>
                <b style={{ color: OVERALL_TONE[c.overallStatus] ?? 'var(--text-sub)',
                            border: `1px solid ${OVERALL_TONE[c.overallStatus]}`,
                            borderRadius: 999, padding: '0 10px' }}>
                  {c.overallStatusJa}
                </b>
                <span style={{ marginLeft: 8, color: 'var(--text-sub)' }}>{c.ownerReadableSummaryJa}</span>
              </p>
              {c.topIssuesJa.map((i) => (
                <p key={i.slice(0, 16)} className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)' }}>⚠ {i}</p>
              ))}
              {c.nextChecksJa.length > 0 && (
                <p className="cmd-alloc__note" style={{ fontSize: 10.5, color: 'var(--text-faint)' }}>
                  次の確認: {c.nextChecksJa.join(' / ')}
                </p>
              )}
              <button type="button" onClick={load}
                style={{ fontSize: 11, cursor: 'pointer', background: 'transparent',
                         color: 'var(--accent)', border: '1px solid var(--line)',
                         borderRadius: 6, padding: '2px 10px' }}>再読込</button>
            </div>
          </section>

          {(c.scheduledMission || c.buildSoak || c.remoteJournalVerification || c.outcomeRetry) && (
            <section>
              <div className="section-head">
                <span className="section-head__title">SCHEDULED OPERATIONS</span>
                <span className="section-head__count">30分tick · Build Soak · durable read-back</span>
              </div>
              <div className="card cmd-alloc">
                {c.scheduledMission && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                    <b>Scheduled Mission:</b>{' '}
                    {DELAY_JA[c.scheduledMission.lastDelayClassification] ?? '未確認'}
                    {' '}· 最終 {c.scheduledMission.lastScheduledTick ?? '未実行'}
                    {' '}· 次回予定 {c.scheduledMission.nextExpectedTick ?? '未確定'}
                    {' '}· 遅延 {c.scheduledMission.lastDelaySeconds ?? '—'}秒
                    {' '}· 欠落窓 {c.scheduledMission.lastMissedWindowCount}件
                    {' '}· 現在窓 {c.scheduledMission.currentMissionWindow ?? '未確定'}
                    {' '}· 重複抑止 {c.scheduledMission.duplicateSuppressed}回
                    {c.scheduledMission.lastDelayClassification !== 'on_time' &&
                      c.scheduledMission.lastDelayClassification !== 'unknown' && (
                        <span style={{ display: 'block', color: 'var(--amber, #fbbf24)' }}>
                          SCHEDULER DELAYED — 定期実行が遅れています。アプリ本体の停止は確認されていません。
                        </span>
                      )}
                  </p>
                )}
                {c.buildSoak && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                    <b>Build Soak:</b>{' '}
                    {SOAK_JA[c.buildSoak.state ?? c.buildSoak.status] ?? c.buildSoak.ownerReadableJa}
                    {' '}· ID {c.buildSoak.soakId ?? '未発行'}
                    {' '}· {c.buildSoak.elapsedHours}/{c.buildSoak.requiredHours}時間
                    {' '}· heartbeat {c.buildSoak.heartbeatCount ?? 0}回
                    {' '}· 最終 {c.buildSoak.lastHeartbeatAt ?? '未記録'}
                    {' '}· source {c.buildSoak.lastHeartbeatSource ?? '未記録'}
                    {c.buildSoak.state === 'verification_gap' && (
                      <span style={{ display: 'block', color: 'var(--amber, #fbbf24)' }}>
                        VERIFICATION GAP — 一部の継続性証拠が未確認です。
                      </span>
                    )}
                    {c.buildSoak.state === 'interrupted' && (
                      <span style={{ display: 'block', color: 'var(--value-negative)' }}>
                        INTERRUPTED — 継続稼働を証明できない重大な空白があります。
                      </span>
                    )}
                  </p>
                )}
                {c.remoteJournalVerification && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                    <b>Remote Journal:</b>{' '}
                    {c.remoteJournalVerification.readBackVerified ? 'read-back検証済み' : 'read-back待ち'}
                    {' '}· commit {c.remoteJournalVerification.committedAt ?? '未記録'}
                    {' '}· read-back {c.remoteJournalVerification.readBackAt ?? '未実施'}
                    {' '}· ack {c.remoteJournalVerification.acknowledgedCount}
                    {' '}· pending {c.remoteJournalVerification.pendingCount}
                  </p>
                )}
                {c.outcomeRetry && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                    <b>Outcome retry:</b> unresolved {c.outcomeRetry.unresolvedCount}件
                    {' '}· retry累計 {c.outcomeRetry.retryCount}
                    {' '}· 次回 {c.outcomeRetry.nextRetryAt ?? '対象なし'}
                    {' '}· 欠損価格は0として採点しません
                  </p>
                )}
              </div>
            </section>
          )}

          {/* 2. ソース健全性 / 鮮度 */}
          <section>
            <div className="section-head">
              <span className="section-head__title">SOURCE HEALTH / FRESHNESS</span>
              <span className="section-head__count">{c.sourceHealth.length}ソース</span>
            </div>
            <div className="card cmd-alloc">
              {c.sourceHealth.map((s) => (
                <p key={s.sourceName} className="cmd-alloc__note" style={{ margin: '3px 0 0' }}>
                  <b style={{ color: STATUS_TONE[s.status] ?? 'var(--text-sub)',
                              border: `1px solid ${STATUS_TONE[s.status] ?? 'var(--line)'}`,
                              borderRadius: 4, padding: '0 5px', fontSize: 10 }}>
                    {s.isExpectedDisabled ? '意図的に無効' : (BUCKET_JA[s.freshnessBucket] ?? s.status)}
                  </b>
                  <b style={{ marginLeft: 6 }}>{s.sourceName}</b>
                  <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--text-sub)' }}>{s.ownerReadableStatusJa}</span>
                  {s.ownerReadableImpactJa && (
                    <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>影響: {s.ownerReadableImpactJa}</span>
                  )}
                </p>
              ))}
              <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                鮮度はサーバーが実測できたタイムスタンプのみから判定(不明は「不明」— 捏造しません)。
                JPフォールバック価格は夜間/引け後delayedが正常です。
              </p>
            </div>
          </section>

          {/* 3. bridge / OpenD */}
          <section>
            <div className="section-head">
              <span className="section-head__title">BRIDGE / OPEND</span>
              <span className="section-head__count">US realtime · JPは意図的に無効</span>
            </div>
            <div className="card cmd-alloc">
              <p className="cmd-alloc__note">
                bridge: <b>{String(c.bridgeHealth.bridgeProcess ?? '不明')}</b>
                {' '}· OpenD: <b>{String(c.bridgeHealth.openDStatus ?? '不明')}</b>
                {' '}· US: <b>{String(c.bridgeHealth.usRealtimeStatus ?? '不明')}</b>
                {' '}· JP: <b>{String(c.bridgeHealth.jpRealtimeStatus ?? '不明')}</b>
                {c.bridgeHealth.heartbeatAgeSec != null && (
                  <> · heartbeat {String(c.bridgeHealth.heartbeatAgeSec)}秒前</>
                )}
              </p>
              {c.bridgeHealth.jpRealtimeNoteJa && (
                <p className="cmd-alloc__note" style={{ color: 'var(--text-faint)' }}>{c.bridgeHealth.jpRealtimeNoteJa}</p>
              )}
              <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                ※ bridgeVersionはEC2ブリッジスクリプトの版で、アプリ本体の版とは別管理です(不一致は異常ではありません)。
              </p>
            </div>
          </section>

          {/* v12.0.2: JP Realtime Readiness — 権限の事実と復帰条件。手順は準備OK時のみ表示 */}
          {c.jpReadiness && (
            <section>
              <div className="section-head">
                <span className="section-head__title">JP REALTIME READINESS</span>
                <span className="section-head__count">moomoo権限依存 · アプリ側では直せません</span>
              </div>
              <div className="card cmd-alloc">
                <p className="cmd-alloc__note" style={{ fontSize: 12.5 }}>
                  <b style={{ color: c.jpReadiness.activationReady === true ? 'var(--value-positive)'
                    : c.jpReadiness.jpPermissionStatus === 'no_permission' ? 'var(--value-negative)'
                      : c.jpReadiness.jpPermissionStatus === 'maintenance_or_no_permission'
                        || c.jpReadiness.jpPermissionStatus === 'maintenance_confirmed' ? 'var(--amber, #fbbf24)'
                        : 'var(--text-faint)' }}>
                    {c.jpReadiness.ownerReadableStatusJa}
                  </b>
                </p>
                {c.jpReadiness.reasonJa && <p className="cmd-alloc__note">{c.jpReadiness.reasonJa}</p>}
                {/* v12.0.4: フル板契約済みでもOpenD側はまだret=-1(オーナー確認済み事実) */}
                {c.jpReadiness.fullBoardNoteJa && (
                  <p className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)' }}>
                    {c.jpReadiness.fullBoardNoteJa}
                  </p>
                )}
                {c.jpReadiness.safeModeJa && (
                  <p className="cmd-alloc__note" style={{ color: 'var(--text-sub)' }}>{c.jpReadiness.safeModeJa}</p>
                )}
                <p className="cmd-alloc__note" style={{ color: 'var(--text-sub)' }}>
                  現在の安全運用: USリアルタイム + 日本株代替データ(J-Quants/Yahoo)。
                </p>
                <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                  権限: <b>{c.jpReadiness.jpPermissionStatus === 'no_permission' ? '権限なし'
                    : c.jpReadiness.jpPermissionStatus === 'maintenance_confirmed' ? 'メンテナンス確認済み(moomooサポート)'
                      : c.jpReadiness.jpPermissionStatus === 'maintenance_or_no_permission' ? 'メンテナンス/権限未反映'
                        : c.jpReadiness.jpPermissionStatus === 'ready' ? 'あり(ret=0確認)' : '未テスト'}</b>
                  {' '}· JP最終push: {c.jpReadiness.lastJPQuotePushAt ?? 'なし'}
                  {' '}· フォールバック: {c.jpReadiness.jpFallbackActive ? '稼働中' : '—'}
                  {' '}· US-only override: {c.jpReadiness.usOnlyOverrideActive ? '有効' : '解除'}
                </p>
                <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                  フル板(アプリ内契約): <b>{c.jpReadiness.jpFullBoardAppSubscriptionKnown === true ? '契約済み'
                    : c.jpReadiness.jpFullBoardAppSubscriptionKnown === false ? 'なし' : '不明'}</b>
                  {' '}· ORDER_BOOK(API): <b>{c.jpReadiness.jpOpenDOrderBookReady === true ? 'ret=0'
                    : c.jpReadiness.jpOpenDOrderBookReady === false ? 'ret=-1(利用不可)' : '未テスト'}</b>
                  {c.jpReadiness.contextAsOf ? ` · 確認日: ${c.jpReadiness.contextAsOf}` : ''}
                </p>
                {/* v12.0.5: サポート正式確認の復旧情報(追加申込・時期・復旧後アクション) */}
                {(c.jpReadiness.additionalSubscriptionNoteJa || c.jpReadiness.recoveryEtaJa
                  || c.jpReadiness.postRecoveryActionJa) && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                    {c.jpReadiness.additionalSubscriptionNoteJa && (
                      <>追加申込: <b>{c.jpReadiness.additionalSubscriptionNoteJa}</b></>
                    )}
                    {c.jpReadiness.recoveryEtaJa && <>{' '}· 復旧時期: <b>{c.jpReadiness.recoveryEtaJa}</b></>}
                    {c.jpReadiness.postRecoveryActionJa && (
                      <span style={{ display: 'block', marginTop: 2 }}>
                        復旧後: {c.jpReadiness.postRecoveryActionJa}
                      </span>
                    )}
                  </p>
                )}
                <p className="cmd-alloc__note" style={{ fontSize: 11, color: 'var(--text-sub)' }}>
                  フル板/ORDER_BOOKも ret=0 になるまで板情報はAPIで使えません。
                </p>
                <p className="cmd-alloc__note" style={{ fontSize: 11, color: 'var(--text-sub)' }}>
                  復帰条件: {c.jpReadiness.activationConditionJa}
                </p>
                <p className="cmd-alloc__note" style={{ fontSize: 11, color: 'var(--text-faint)' }}>
                  権限テスト(EC2・安全): <code>bridge/scripts/check_opend_status.sh</code> →
                  moomoo APIのJP snapshotテスト(bridge/README.md参照・出力に秘密は含まれません)。
                </p>
                {c.jpReadiness.showActivationSteps ? (
                  <div className="cmd-alloc__note" style={{ border: '1px solid var(--value-positive)', borderRadius: 6, padding: 8 }}>
                    <b style={{ color: 'var(--value-positive)' }}>US-only解除手順(準備OKのため表示):</b>
                    <p style={{ margin: '3px 0 0', fontSize: 10.5 }}>
                      ① no-jp-quotes.conf(ARGUS_DISABLE_JP_QUOTES=1)を退避 → ② sudo systemctl daemon-reload →
                      ③ <code>bridge/scripts/restart_argus_bridge.sh</code> → ④ このページでJP pushとmode=fullを確認。
                    </p>
                  </div>
                ) : (
                  <p className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)', fontWeight: 700 }}>
                    {c.jpReadiness.guardJa ?? 'まだUS-onlyを外さないでください。'}
                  </p>
                )}
                <details>
                  <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>復帰に失敗した場合のロールバック(常設)</summary>
                  <p className="cmd-alloc__note" style={{ fontSize: 10.5 }}>
                    No permissionで失敗したら: ① no-jp-quotes.conf を復元(US-onlyへ戻す) →
                    ② sudo systemctl daemon-reload → ③ <code>bridge/scripts/restart_argus_bridge.sh</code> →
                    ④ <code>bridge/scripts/safe_public_bridge_status.sh</code> で mode=us_only を確認。秘密値は出ません。
                  </p>
                </details>
                <p className="cmd-alloc__note" style={{ fontSize: 10.5, color: 'var(--text-sub)' }}>
                  次の一歩: {c.jpReadiness.nextStepJa}
                </p>
              </div>
            </section>
          )}

          {/* v12.1.0: OSINTエンジン健全性(プロバイダ/キュー/canary) */}
          {c.osintHealth && (
            <section>
              <div className="section-head">
                <span className="section-head__title">OSINT AGENTS</span>
                <span className="section-head__count">外部AIは管理側実行のみ</span>
              </div>
              <div className="card cmd-alloc">
                <p className="cmd-alloc__note" style={{ fontSize: 12 }}>
                  Gemini: <b>{c.osintHealth.geminiProviderConfigured ? '設定済み' : '未設定(外部AIベンチマーク未実行)'}</b>
                  {' '}· GPT: <b>{c.osintHealth.gptProviderConfigured ? '設定済み' : '未設定(外部AIベンチマーク未実行)'}</b>
                  {' '}· スカウト待ち: {c.osintHealth.agentQueueDepth}件
                </p>
                <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                  最終深掘り: {c.osintHealth.lastDeepDiveAt ?? '未実行'}
                  {' '}· 最終スカウト実行: {c.osintHealth.lastAgentsRunAt ?? '未実行'}
                </p>
                <p className="cmd-alloc__note" style={{ fontSize: 11,
                  color: c.osintHealth.canaryStatus === 'degraded' ? 'var(--amber, #fbbf24)' : 'var(--text-sub)' }}>
                  canary: {c.osintHealth.canaryStatus === 'degraded' ? 'OSINT監視に見落としの可能性' :
                    c.osintHealth.canaryStatus === 'ok' ? '正常' : '未実行'}
                  {c.osintHealth.canaryMissedByArgus > 0 && ` (ARGUS見落とし ${c.osintHealth.canaryMissedByArgus}件)`}
                  {' '}— {c.osintHealth.canaryNoteJa}
                </p>
                {/* v12.1.1: 優位性・ベンチ・恒久メモリ・パーサ健全性 */}
                <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                  優位性(最新): <b style={{ color: c.osintHealth.superiorityLatest === 'below_gemini'
                    ? 'var(--amber, #fbbf24)' : 'var(--text-sub)' }}>
                    {({ exceeds_gemini: 'Gemini超過', matches_gemini: 'Gemini同等',
                        below_gemini: 'Gemini未満', insufficient_data: '判定保留',
                        not_run: '未実行' } as Record<string, string>)[c.osintHealth.superiorityLatest ?? 'not_run'] ?? '未実行'}
                  </b>
                  {' '}· 未回収Gemini-only合計: {c.osintHealth.unresolvedGeminiOnlyTotal ?? 0}件
                  {' '}· 恒久メモリ: {c.osintHealth.memoryRecords ?? 0}件{c.osintHealth.memoryPersisted ? '(永続化済み)' : ''}
                  {' '}· パーサ警告: {c.osintHealth.parserWarnings ?? 0}
                </p>
                {c.osintHealth.benchmarkVerdictJa && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11,
                    color: (c.osintHealth.benchmarkVerdictJa || '').includes('未達') ? 'var(--amber, #fbbf24)'
                      : (c.osintHealth.benchmarkVerdictJa || '').includes('上回') ? 'var(--value-positive)'
                      : 'var(--text-sub)' }}>
                    {c.osintHealth.benchmarkVerdictJa}
                    {(c.osintHealth.capReachedCount ?? 0) > 0 && ` · 検証上限到達 累計${c.osintHealth.capReachedCount}件`}
                  </p>
                )}
                {c.osintHealth.benchmarkWarnJa && (
                  <p className="cmd-alloc__note" style={{ color: 'var(--amber, #fbbf24)' }}>
                    ⚠ {c.osintHealth.benchmarkWarnJa}
                  </p>
                )}
                {/* v12.1.3: Research Power最新値(Gemini基準比) */}
                {c.osintHealth.researchPowerLatest && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11,
                    color: c.osintHealth.researchPowerLatest.status === 'below_gemini'
                      ? 'var(--amber, #fbbf24)'
                      : c.osintHealth.researchPowerLatest.status.startsWith('exceeds')
                        ? 'var(--value-positive)' : 'var(--text-sub)' }}>
                    Research Power(最新 {c.osintHealth.researchPowerLatest.symbol}):{' '}
                    <b>{c.osintHealth.researchPowerLatest.statusJa}</b>
                    {' '}— {c.osintHealth.researchPowerLatest.displayJa}
                  </p>
                )}
                {/* v12.1.6: Gemini基準の校正状態(2x主張の可否) */}
                {c.osintHealth.geminiBaseline && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11,
                    color: c.osintHealth.geminiBaseline.twoXClaimAllowed
                      ? 'var(--value-positive)' : 'var(--text-sub)' }}>
                    Gemini基準: <b>{c.osintHealth.geminiBaseline.labelJa}</b>
                    {' '}· run {c.osintHealth.geminiBaseline.runCount}回
                    {c.osintHealth.geminiBaseline.medianScore != null &&
                      ` · 中央値 ${c.osintHealth.geminiBaseline.medianScore}`}
                    {c.osintHealth.geminiBaseline.variance != null &&
                      ` · 分散 ${c.osintHealth.geminiBaseline.variance}`}
                    {' '}· 信頼度 {c.osintHealth.geminiBaseline.confidence}
                    {' '}· 2x判定 {c.osintHealth.geminiBaseline.twoXClaimAllowed ? '有効' : '不可'}
                    <span style={{ display: 'block', fontSize: 10, color: 'var(--text-faint)' }}>
                      {c.osintHealth.geminiBaseline.noteJa}
                      {c.osintHealth.geminiBaseline.lastCalibrationAt &&
                        ` 最終校正: ${c.osintHealth.geminiBaseline.lastCalibrationAt}`}
                    </span>
                  </p>
                )}
                {/* v12.1.7: 校正進捗+2x準備レポート */}
                {c.osintHealth.calibrationPlan && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11 }}>
                    校正進捗: <b>{c.osintHealth.calibrationPlan.progressPct}%</b>
                    (run {c.osintHealth.calibrationPlan.currentRuns}/{c.osintHealth.calibrationPlan.requiredRuns}
                    ・ケース {c.osintHealth.calibrationPlan.currentCasesCovered}/{c.osintHealth.calibrationPlan.requiredCases})
                    {' '}· {c.osintHealth.calibrationPlan.estimatedCompletionJa}
                    <span style={{ display: 'block', height: 4, background: 'var(--line)',
                                   borderRadius: 2, marginTop: 2 }}>
                      <span style={{ display: 'block', height: 4, borderRadius: 2,
                                     width: `${c.osintHealth.calibrationPlan.progressPct}%`,
                                     background: c.osintHealth.calibrationPlan.canClaim2x
                                       ? 'var(--value-positive)' : 'var(--accent)' }} />
                    </span>
                  </p>
                )}
                {c.osintHealth.twoXReadiness && (
                  <p className="cmd-alloc__note" style={{ fontSize: 11,
                    color: c.osintHealth.twoXReadiness.overallStatus === 'calibrated_2x'
                      ? 'var(--value-positive)' : 'var(--text-sub)' }}>
                    2x準備: <b>{c.osintHealth.twoXReadiness.overallJa}</b>
                    {c.osintHealth.twoXReadiness.currentRatio != null &&
                      ` · 現在比 ${c.osintHealth.twoXReadiness.currentRatio.toFixed(2)}x`}
                    {c.osintHealth.twoXReadiness.weakPillars.length > 0 &&
                      ` · 弱い柱: ${c.osintHealth.twoXReadiness.weakPillars.join('/')}`}
                    {c.osintHealth.twoXReadiness.topBlockersJa.length > 0 && (
                      <span style={{ display: 'block', color: 'var(--amber, #fbbf24)', fontSize: 10 }}>
                        blocker: {c.osintHealth.twoXReadiness.topBlockersJa.join(' / ')}
                      </span>
                    )}
                    {c.osintHealth.twoXReadiness.fastestPathTo2xJa.length > 0 && (
                      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-faint)' }}>
                        {c.osintHealth.twoXReadiness.fastestPathTo2xJa.join(' / ')}
                      </span>
                    )}
                    {c.osintHealth.twoXReadiness.recommendedNextEngineeringTasks.length > 0 && (
                      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-faint)' }}>
                        推奨タスク: {c.osintHealth.twoXReadiness.recommendedNextEngineeringTasks.join(' / ')}
                      </span>
                    )}
                  </p>
                )}
                {c.osintHealth.benchmarkRunsSummary && (
                  <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                    ベンチ実行: 累計{c.osintHealth.benchmarkRunsSummary.total}回
                    {c.osintHealth.benchmarkRunsSummary.running && '(実行中)'}
                    {' '}· 予算 {c.osintHealth.benchmarkRunsSummary.budget.maxCostLabel}
                    {c.osintHealth.benchmarkRunsSummary.recent.slice(-2).map((r) => (
                      <span key={r.caseId + r.status} style={{ display: 'block' }}>
                        {r.caseId}: {r.status}{r.ownerReadableJa ? ` — ${r.ownerReadableJa}` : ''}
                      </span>
                    ))}
                  </p>
                )}
                {/* v12.1.3: ソースユニバース(unavailableも沈黙省略せず可視化) */}
                {c.osintHealth.sourceUniverse && (
                  <details style={{ fontSize: 10.5 }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--text-sub)' }}>
                      探索ソースユニバース: 全{c.osintHealth.sourceUniverse.total}カテゴリ
                      (稼働{c.osintHealth.sourceUniverse.live}
                      ・スカウト経由{c.osintHealth.sourceUniverse.viaAgents}
                      ・利用不可{c.osintHealth.sourceUniverse.unavailable})
                    </summary>
                    {c.osintHealth.sourceUniverse.categories.map((u) => (
                      <p key={u.key} className="cmd-alloc__note" style={{ margin: '1px 0 0',
                        fontSize: 10, color: u.availability === 'live' ? 'var(--text-sub)'
                          : u.availability === 'via_agents' ? 'var(--text-faint)'
                          : 'var(--amber, #fbbf24)' }}>
                        {u.labelJa}: {({ live: '稼働', via_agents: 'スカウト経由',
                          agents_not_configured: 'スカウト未設定',
                          unavailable: '利用不可' } as Record<string, string>)[u.availability] ?? u.availability}
                        {u.noteJa ? ` — ${u.noteJa}` : ''}
                      </p>
                    ))}
                  </details>
                )}
                <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                  {c.osintHealth.noteJa}
                </p>
              </div>
            </section>
          )}

          {/* v12.0.2: Reboot Safety — OpenD自動復旧が未検証の間は再起動非推奨 */}
          {c.rebootSafety && (
            <section>
              <div className="section-head">
                <span className="section-head__title">REBOOT SAFETY (EC2)</span>
                <span className="section-head__count">検証まで再起動しない</span>
              </div>
              <div className="card cmd-alloc">
                <p className="cmd-alloc__note">
                  再起動安全: <b style={{ color: c.rebootSafety.rebootSafe === true ? 'var(--value-positive)'
                    : c.rebootSafety.rebootSafe === false ? 'var(--value-negative)' : 'var(--amber, #fbbf24)' }}>
                    {c.rebootSafety.rebootSafe === true ? '準備OK' : c.rebootSafety.rebootSafe === false ? '不可' : '未確認'}
                  </b>
                  {' '}· OpenD自動起動: {String(c.rebootSafety.opendAutostartConfigured) === 'true' ? '設定済み'
                    : String(c.rebootSafety.opendAutostartConfigured) === 'false' ? '未設定' : '不明'}
                  {' '}· bridge自動起動: {String(c.rebootSafety.bridgeAutostartConfigured) === 'true' ? '設定済み'
                    : String(c.rebootSafety.bridgeAutostartConfigured) === 'false' ? '未設定' : '不明'}
                  {' '}· OS再起動要求: {String(c.rebootSafety.systemRestartRequired) === 'true' ? 'あり'
                    : String(c.rebootSafety.systemRestartRequired) === 'false' ? 'なし' : '不明'}
                </p>
                <p className="cmd-alloc__note" style={{ fontSize: 10, color: 'var(--text-faint)' }}>
                  実測はEC2で <code>bridge/scripts/check_reboot_readiness.sh</code>(秘密ゼロ)。
                  ブリッジ更新(git pull+restart)後はheartbeatが自動起動状態を自己申告し、この表示が実測になります。
                </p>
                <p className="cmd-alloc__note" style={{ color: 'var(--text-sub)' }}>{c.rebootSafety.ownerReadableRiskJa}</p>
                <p className="cmd-alloc__note" style={{ fontSize: 10.5, color: 'var(--text-faint)' }}>{c.rebootSafety.nextStepJa}</p>
              </div>
            </section>
          )}

          {/* 4. エンジン健全性(サーバー側+端末側) */}
          <section>
            <div className="section-head">
              <span className="section-head__title">ENGINE HEALTH</span>
              <span className="section-head__count">server + device</span>
            </div>
            <div className="card cmd-alloc">
              {c.engineHealth.map((e) => (
                <p key={e.engineName} className="cmd-alloc__note" style={{ margin: '2px 0 0', fontSize: 11.5 }}>
                  <b style={{ color: STATUS_TONE[e.status] ?? 'var(--text-sub)' }}>{e.status}</b>
                  <span style={{ marginLeft: 6 }}>{e.engineName}</span>
                  {e.ownerReadableImpactJa && (
                    <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>{e.ownerReadableImpactJa}</span>
                  )}
                </p>
              ))}
              <p className="cmd-alloc__note" style={{ margin: '6px 0 0', fontSize: 11.5, fontWeight: 700 }}>この端末:</p>
              {device.map((d) => (
                <p key={d.name} className="cmd-alloc__note" style={{ margin: '2px 0 0', fontSize: 11.5 }}>
                  <b style={{ color: d.ok ? 'var(--value-positive)' : 'var(--text-faint)' }}>{d.ok ? 'ok' : '未計算'}</b>
                  <span style={{ marginLeft: 6 }}>{d.name}</span>
                  <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>{d.note}</span>
                </p>
              ))}
            </div>
          </section>

          {/* 5. 既知の無効(仕様) */}
          <section>
            <div className="section-head">
              <span className="section-head__title">KNOWN DISABLED / 仕様上の未取得</span>
              <span className="section-head__count">障害ではありません</span>
            </div>
            <div className="card cmd-alloc">
              {c.expectedDisabled.map((x) => (
                <p key={x.sourceName} className="cmd-alloc__note" style={{ margin: '2px 0 0' }}>
                  <b>{x.sourceName}</b>
                  <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--text-sub)' }}>{x.reasonJa}</span>
                </p>
              ))}
            </div>
          </section>

          {/* 6. 漏洩ガード + 7. オペレーター手順 */}
          <section>
            <div className="section-head">
              <span className="section-head__title">PRIVACY GUARD / OPERATOR ACTIONS</span>
            </div>
            <div className="card cmd-alloc">
              <p className="cmd-alloc__note">
                公開漏洩ガード: <b style={{ color: c.publicLeakSafe ? 'var(--value-positive)' : 'var(--value-negative)' }}>
                  {c.publicLeakSafe ? '正常(leak-safe)' : '異常 — 即時確認'}
                </b>
                <span style={{ marginLeft: 6, fontSize: 10.5, color: 'var(--text-faint)' }}>{c.privacyHealth.noteJa}</span>
              </p>
              <p className="cmd-alloc__note" style={{ marginTop: 6, fontWeight: 700 }}>異常時の安全な手順(秘密値は出ません):</p>
              <p className="cmd-alloc__note" style={{ fontSize: 10.5, color: 'var(--text-faint)' }}>
                ① このページを再読込 → ② Backupページで保護状態と復元ドリルを確認 →
                ③ bridge疑いはEC2で <code>bridge/scripts/check_opend_status.sh</code> /
                <code> bridge/scripts/check_bridge_status.sh</code> →
                ④ 復旧は <code>bridge/scripts/restart_argus_bridge.sh</code>(bridge/README.mdのランブック参照) →
                ⑤ 公開状態の確認は <code>bridge/scripts/safe_public_bridge_status.sh</code>。
              </p>
            </div>
          </section>
        </>
      )}
    </PageShell>
  );
};

export default DataQualityPage;

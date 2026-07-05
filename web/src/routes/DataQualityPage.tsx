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
  expectedDisabled: { sourceName: string; reasonJa: string }[];
  privacyHealth: { publicLeakSafe: boolean; noteJa: string };
  publicLeakSafe: boolean;
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
          expectedDisabledJa: (d.expectedDisabled ?? []).map((x) => `${x.sourceName}: ${x.reasonJa}`) });
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
            </div>
          </section>

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

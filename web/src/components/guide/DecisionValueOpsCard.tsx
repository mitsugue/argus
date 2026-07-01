import '../dashboard/Dashboard.css';
import React from 'react';

// Decision Value Shadow Operations (v10.195) — public-safe status: phase + per-policy
// n + sample stage ONLY (real netR stays owner-gated). Reports the exact blockers.
interface DVSummary {
  phase?: string;
  status?: string;
  blockersJa?: string | null;
  shadow?: {
    policies?: Record<string, { n?: number; sampleStage?: string }>;
    noTrade?: Record<string, { n?: number; sampleStage?: string }>;
    scoredCount?: number;
    note?: string;
  } | null;
}

const STATUS_JA: Record<string, string> = {
  blocked_pending_private_store: 'ブロック中(private store未設定)',
  engine_ready_no_records_yet: 'エンジン準備完了・記録待ち',
  phase1_shadow_recording_active: 'Phase1 シャドー記録 稼働中',
};

export const DecisionValueOpsCard: React.FC = () => {
  const [d, setD] = React.useState<DVSummary | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    const load = () => fetch(backend.replace(/\/$/, '') + '/api/argus/decision-value/summary')
      .then((r) => r.json()).then((j) => { if (alive) setD(j); }).catch(() => {});
    load();
    const iv = setInterval(load, 5 * 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  if (!d) return null;
  const pol = d.shadow?.policies || {};
  const nt = d.shadow?.noTrade || {};
  return (
    <section className="dvops">
      <div className="section-head">
        <span className="section-head__title">Decision Value — Shadow Operations（仮想・発注なし）</span>
        <span className="section-head__count">{STATUS_JA[d.status ?? ''] ?? d.status ?? '—'}</span>
      </div>
      <div className="card dvops__card">
        <p className="dvops__lead">
          「校正が良い ≠ 儲かる」を測る別台帳。<b>仮想(shadow)シミュレーションのみ・発注は一切なし</b>。優位性(edge)は
          十分なサンプルが貯まるまで「証明済み」とは表示しません。
        </p>
        {d.blockersJa && <p className="dvops__blocker">ブロッカー: {d.blockersJa}</p>}
        {(Object.keys(pol).length > 0 || Object.keys(nt).length > 0) ? (
          <div className="dvops__policies">
            {Object.entries(pol).map(([pid, v]) => (
              <div className="dvops__row" key={pid}>
                <span className="dvops__pid">{pid}</span>
                <span className="dvops__n">n={v.n ?? 0} · {v.sampleStage ?? '—'}</span>
              </div>
            ))}
            {Object.entries(nt).map(([pid, v]) => (
              <div className="dvops__row dvops__row--nt" key={pid}>
                <span className="dvops__pid">{pid}(no-trade)</span>
                <span className="dvops__n">n={v.n ?? 0} · {v.sampleStage ?? '—'}</span>
              </div>
            ))}
            {typeof d.shadow?.scoredCount === 'number' && (
              <div className="dvops__scored">採点済み: {d.shadow.scoredCount}件</div>
            )}
          </div>
        ) : (
          <p className="dvops__pending">まだシャドー記録はありません。{d.status === 'engine_ready_no_records_yet' ? '次回の実行(毎営業日16:05)で記録が始まります。' : ''}</p>
        )}
        <p className="dvops__note">純R・実価格はオーナー限定(private store)。ここには件数とサンプル段階のみ表示。</p>
      </div>
    </section>
  );
};

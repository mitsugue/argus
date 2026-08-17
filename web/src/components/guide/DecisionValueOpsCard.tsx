import '../dashboard/Dashboard.css';
import React from 'react';

// Decision Value Shadow Operations (v11.0.4) — now consumes the AUTHORITATIVE status
// endpoint /api/argus/decision-value/status. Public-safe: phase + counts + sampleStage
// ONLY (real netR / prices / holdings stay owner-gated). Never says "recording" unless
// the phase actually is shadow_recording_active / scoring_active.
interface DVStatus {
  schemaVersion?: string;
  phase?: 'not_configured' | 'engine_ready_no_records_yet' | 'shadow_recording_active' | 'scoring_active';
  privateStoreConfigured?: boolean;
  lastShadowRunAt?: string | null;
  totalRecords?: number;
  recordedToday?: number | null;
  pendingOutcomeCount?: number;
  scoredCount?: number;
  sampleStage?: string;
  reasonJa?: string;
  disclaimer?: string;
}

const PHASE: Record<string, { ja: string; tone: string }> = {
  not_configured: { ja: '未設定（private store無し）', tone: 'var(--text-muted)' },
  engine_ready_no_records_yet: { ja: 'エンジン準備完了・記録なし', tone: 'var(--amber,#fbbf24)' },
  shadow_recording_active: { ja: 'シャドー記録中', tone: 'var(--value-positive,#34d399)' },
  scoring_active: { ja: '採点中', tone: 'var(--value-positive,#34d399)' },
};

export const DecisionValueOpsCard: React.FC = () => {
  const [d, setD] = React.useState<DVStatus | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    const load = () => fetch(backend.replace(/\/$/, '') + '/api/argus/decision-value/status')
      .then((r) => r.json()).then((j) => { if (alive) setD(j); }).catch(() => {});
    load();
    const iv = setInterval(load, 5 * 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  if (!d) return null;
  const ph = PHASE[d.phase ?? ''] ?? { ja: d.phase ?? '—', tone: 'var(--text-muted)' };
  const recording = d.phase === 'shadow_recording_active' || d.phase === 'scoring_active';
  return (
    <section className="dvops">
      <div className="section-head">
        <span className="section-head__title">Decision Value — Shadow Operations（仮想・発注なし）</span>
        <span className="section-head__count" style={{ color: ph.tone }}>{ph.ja}</span>
      </div>
      <div className="card dvops__card">
        <p className="dvops__lead">
          「校正が良い ≠ 儲かる」を測る別台帳。<b>仮想(shadow)シミュレーションのみ・発注は一切なし</b>。優位性(edge)は
          十分なサンプルが貯まるまで「証明済み」とは表示しません。
        </p>

        {d.phase === 'not_configured' && (
          <p className="dvops__pending">private store が未設定のため、記録は行われていません。{d.reasonJa || ''}</p>
        )}
        {d.phase === 'engine_ready_no_records_yet' && (
          <p className="dvops__pending">エンジンは準備完了ですが、記録はまだ0件です。次回の実行(毎営業日16:05)で記録が始まります。</p>
        )}
        {recording && (
          <div className="dvops__policies">
            <div className="dvops__row"><span className="dvops__pid">総記録</span>
              <span className="dvops__n">{d.totalRecords ?? 0}件{typeof d.recordedToday === 'number' ? ` · 本日 ${d.recordedToday}件` : ''}</span></div>
            <div className="dvops__row"><span className="dvops__pid">採点済み</span>
              <span className="dvops__n">{d.scoredCount ?? 0}件</span></div>
            <div className="dvops__row"><span className="dvops__pid">結果待ち</span>
              <span className="dvops__n">{d.pendingOutcomeCount ?? 0}件</span></div>
            <div className="dvops__row"><span className="dvops__pid">サンプル段階</span>
              <span className="dvops__n">{d.sampleStage ?? '—'}</span></div>
          </div>
        )}

        <p className="dvops__note">
          {d.disclaimer || '純R・実価格はオーナー限定(private store)。ここには件数とサンプル段階のみ表示。'}
        </p>
      </div>
    </section>
  );
};

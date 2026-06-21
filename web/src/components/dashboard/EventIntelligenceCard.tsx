import React from 'react';
import { useEventsActive, type ActiveEvent } from '../../hooks/useEventsActive';
import './EventIntelligenceCard.css';

const TYPE_JA: Record<string, string> = {
  LIMIT_UP: 'ストップ高(S高)', LIMIT_DOWN: 'ストップ安(S安)',
  LIMIT_UP_PROXIMITY: 'S高接近(値幅上限)', LIMIT_DOWN_PROXIMITY: 'S安接近(値幅下限)',
  PRICE_SPIKE: '急騰', PRICE_CRASH: '急落',
  VOLUME_ANOMALY: '出来高急増', FLOW_ANOMALY: '大口フロー異常',
};
const POSTURE_JA: Record<string, string> = {
  LIMIT_UP_RISK: 'S高リスク', LIMIT_DOWN_RISK: 'S安リスク', AVOID_CHASING: '高値追い回避',
  INVESTIGATE: '要調査', WATCH: '監視',
};

function sevColor(s: number): string {
  return s >= 5 ? 'var(--red, #f87171)' : s >= 4 ? 'var(--amber, #fbbf24)' : 'var(--text-sub, #8b98a7)';
}

function EventRow({ e }: { e: ActiveEvent }) {
  return (
    <div className="ei-row">
      <span className="ei-row__dot" style={{ background: sevColor(e.severity) }} />
      <span className="ei-row__sym">{e.symbol}</span>
      <span className="ei-row__type" style={{ color: sevColor(e.severity) }}>
        {TYPE_JA[e.eventType] ?? e.eventType}
      </span>
      <span className="ei-row__reason">{e.reasonJa}</span>
      <span className="ei-row__posture">{POSTURE_JA[e.recommendedPosture] ?? e.recommendedPosture}</span>
    </div>
  );
}

export const EventIntelligenceCard: React.FC = () => {
  const { events, status, loading } = useEventsActive();
  const [testMsg, setTestMsg] = React.useState<string | null>(null);
  const [testing, setTesting] = React.useState(false);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  async function sendTest() {
    if (!backend) return;
    setTesting(true); setTestMsg(null);
    try {
      const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/event-test-notify', { method: 'POST' });
      const d = await r.json();
      setTestMsg(d.noteJa ?? (d.sent ? '送信しました。' : '送信できませんでした。'));
    } catch {
      setTestMsg('送信に失敗しました(時間をおいて再試行)。');
    } finally {
      setTesting(false);
      window.setTimeout(() => setTestMsg(null), 6000);
    }
  }

  if (loading && !status) return null;
  const enabled = status?.enabled;
  const inSession = status?.sessionJp || status?.sessionUs;
  // Honest wording (GPT review #2D): detection is LIVE only during JP/US market
  // sessions. Off-hours is idle — no PTS, crypto-24/7 not wired yet.
  const sessionJa = status?.sessionJp ? '東京市場 取引時間中 — 検知 稼働中'
    : status?.sessionUs ? '米国市場 取引時間中 — 検知 稼働中'
    : '市場時間外 — 銘柄検知は次の取引時間から';

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">24/7 Event Intelligence</span>
        <span className="section-head__count" style={{ color: enabled ? 'var(--green, #34d399)' : 'var(--text-muted)' }}>
          {enabled ? '監視中' : 'OFF'}
        </span>
      </div>
      <div className="card ei-card">
        <div className="ei-status">
          <span className="ei-status__dot" style={{ background: enabled ? 'var(--green, #34d399)' : 'var(--text-muted)' }} />
          {sessionJa}
          {status && !status.ntfyConfigured && (
            <span className="ei-status__warn"> · 通知未設定(RenderにNTFY_TOPIC)</span>
          )}
        </div>
        {events.length === 0 ? (
          <div className="ei-empty">
            {inSession ? '現在アラートはありません(S高/急変/フロー異常を検知中)。'
              : '市場時間外。次の取引時間(東京/米国)に銘柄検知を再開します。深夜・週末の常時監視(暗号資産/ニュース)は今後対応。'}
          </div>
        ) : (
          <div className="ei-rows">
            {events.slice(0, 8).map((e) => <EventRow key={e.eventId} e={e} />)}
          </div>
        )}
        <div className="ei-actions">
          <button className="ei-test-btn" onClick={sendTest} disabled={testing}>
            {testing ? '送信中…' : '🔔 通知テスト'}
          </button>
          {testMsg && <span className="ei-test-msg">{testMsg}</span>}
        </div>
        <div className="ei-foot">
          決定論的検知のみ(LLMなし)。値幅上限/下限への接近はTSE制限値幅で算出(取引所の特別気配フィールドではありません)。PTS・板(L2)・VWAPは未対応。
        </div>
      </div>
    </section>
  );
};

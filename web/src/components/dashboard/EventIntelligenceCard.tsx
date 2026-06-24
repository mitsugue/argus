import React from 'react';
import { useEventsActive, type ActiveEvent } from '../../hooks/useEventsActive';
import './EventIntelligenceCard.css';

const TYPE_JA: Record<string, string> = {
  LIMIT_UP: 'ストップ高(S高)', LIMIT_DOWN: 'ストップ安(S安)',
  LIMIT_UP_PROXIMITY: 'S高接近(値幅上限)', LIMIT_DOWN_PROXIMITY: 'S安接近(値幅下限)',
  PRICE_SPIKE: '急騰', PRICE_CRASH: '急落',
  VOLUME_ANOMALY: '出来高急増', FLOW_ANOMALY: '大口フロー異常', CRYPTO_SHOCK: '暗号資産ショック',
  MOMENTUM_ACCELERATION: '急加速(早期)', FLOW_REVERSAL: '大口フロー反転', VOLUME_ACCELERATION: '出来高加速(早期)',
  MARKET_MOVER: '全市場ムーバー(US)',
};
const POSTURE_JA: Record<string, string> = {
  LIMIT_UP_RISK: 'S高リスク', LIMIT_DOWN_RISK: 'S安リスク', AVOID_CHASING: '高値追い回避',
  INVESTIGATE: '要調査', WATCH: '監視', HIGH_ALERT: '高警戒', OBSERVE: '様子見', VERIFY: '確認中',
  PRE_MARKET_REVIEW_REQUIRED: '寄り前要再評価', GAP_RISK: 'ギャップ注意', NO_ACTION: '対応不要',
};
const LABEL_JA: Record<string, string> = {
  official_catalyst: '公式材料', flow_driven: '需給(フロー)', sector_or_market: 'セクター/市場全体',
  technical_momentum: 'テクニカル/モメンタム', unknown: '不明',
  large_gap_up: '大幅ギャップアップ', gap_and_fade: 'ギャップ後失速', no_follow_through: '続かない',
  continued_weakness: '下落継続', rebound_attempt: '反発試行', stabilize: '下げ止まり',
  company_specific: '個別銘柄', market_wide: '市場全体', sector_wide: 'セクター', unconfirmed: '判定不可',
  ACCEPT: '妥当', CAUTION: '注意', REJECT: '却下',
};
const TRAP_JA: Record<string, string> = {
  gap_and_fade: 'ギャップ後失速', squeeze_exhaustion: '踏み上げ一巡', distribution_into_strength: '上昇中の売り抜け',
  overbought_gap_and_fade: '過熱→失速', falling_knife: '落ちるナイフ', dead_cat_bounce: '一時反発の罠',
};

function sevColor(s: number): string {
  return s >= 5 ? 'var(--red, #f87171)' : s >= 4 ? 'var(--amber, #fbbf24)' : 'var(--text-sub, #8b98a7)';
}

// Direction follows the app's convention (green=up, red=down — same as the
// movers board), so 急騰 and 急落 are instantly distinguishable.
const _UP = new Set(['LIMIT_UP', 'LIMIT_UP_PROXIMITY', 'PRICE_SPIKE']);
const _DOWN = new Set(['LIMIT_DOWN', 'LIMIT_DOWN_PROXIMITY', 'PRICE_CRASH']);
function eventDir(e: ActiveEvent): 'up' | 'down' | 'flat' {
  if (_UP.has(e.eventType)) return 'up';
  if (_DOWN.has(e.eventType)) return 'down';
  const r = e.reasonJa || '';
  if (/下落|急落|反転|流出|-\s?\d/.test(r)) return 'down';
  if (/急騰|上昇|加速|流入|\+\s?\d/.test(r)) return 'up';
  return 'flat';
}
function dirColor(d: 'up' | 'down' | 'flat'): string {
  return d === 'up' ? 'var(--green, #34d399)' : d === 'down' ? 'var(--red, #f87171)' : 'var(--amber, #fbbf24)';
}
// Advice that must stand out (high-stakes); others are calm.
const _STRONG_POSTURE = new Set(['AVOID_CHASING', 'LIMIT_UP_RISK', 'LIMIT_DOWN_RISK', 'HIGH_ALERT', 'GAP_RISK']);
function eventTime(e: ActiveEvent): string {
  if (!e.detectedAt) return '';
  try {
    const d = new Date(e.detectedAt);
    return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
  } catch { return ''; }
}

interface Dossier {
  researchPosture: string; researchConfidence: number; whatHappenedJa?: string;
  marketScope: string; reviewVerdict: string; reviewObjectionsJa: string[];
  probableCause: { label: string; probability: number }[];
  nextSessionScenarios: { label: string; probability: number }[];
  flowInference: Record<string, number>;
  trapRisks: string[]; invalidationConditions: string[]; missingData: string[];
  dataLimitations: string[]; evidence: unknown[]; disclaimerJa: string;
}

function Bars({ items }: { items: { label: string; probability: number }[] }) {
  return (
    <div className="dz-bars">
      {items.map((it) => (
        <div className="dz-bar" key={it.label}>
          <span className="dz-bar__label">{LABEL_JA[it.label] ?? it.label}</span>
          <span className="dz-bar__track"><span className="dz-bar__fill" style={{ width: `${Math.round(it.probability * 100)}%` }} /></span>
          <span className="dz-bar__pct">{Math.round(it.probability * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

function DossierDetail({ eventId }: { eventId: string }) {
  const [d, setD] = React.useState<Dossier | null>(null);
  const [err, setErr] = React.useState(false);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
  React.useEffect(() => {
    let alive = true;
    fetch(`${backend?.replace(/\/$/, '')}/api/argus/event-dossier?eventId=${encodeURIComponent(eventId)}`)
      .then((r) => r.json()).then((j) => { if (alive) { if (j.error) setErr(true); else setD(j); } })
      .catch(() => { if (alive) setErr(true); });
    return () => { alive = false; };
  }, [eventId, backend]);
  if (err) return <div className="dz dz--note">調査ドシエを取得できませんでした。</div>;
  if (!d) return <div className="dz dz--note">調査ドシエを生成中…</div>;
  return (
    <div className="dz">
      <div className="dz-head">
        <span className="dz-posture">{POSTURE_JA[d.researchPosture] ?? d.researchPosture}</span>
        <span className="dz-conf">証拠カバレッジ {Math.round(d.researchConfidence * 100)}%(未較正)</span>
        <span className="dz-scope">範囲: {LABEL_JA[d.marketScope] ?? d.marketScope}</span>
        <span className="dz-review">レビュー: {LABEL_JA[d.reviewVerdict] ?? d.reviewVerdict}</span>
      </div>
      <div className="dz-sec"><div className="dz-sec__t">推定原因</div><Bars items={d.probableCause} /></div>
      <div className="dz-sec"><div className="dz-sec__t">次セッションのシナリオ</div><Bars items={d.nextSessionScenarios} /></div>
      {d.trapRisks.length > 0 && (
        <div className="dz-sec"><div className="dz-sec__t">罠リスク</div>
          <div className="dz-chips">{d.trapRisks.map((t) => <span className="dz-chip dz-chip--warn" key={t}>{TRAP_JA[t] ?? t}</span>)}</div>
        </div>
      )}
      {d.reviewObjectionsJa.length > 0 && (
        <div className="dz-sec"><div className="dz-sec__t">反証(アドバーサリアル)</div>
          <ul className="dz-list">{d.reviewObjectionsJa.map((o, i) => <li key={i}>{o}</li>)}</ul></div>
      )}
      {d.invalidationConditions.length > 0 && (
        <div className="dz-sec"><div className="dz-sec__t">無効化条件</div>
          <ul className="dz-list">{d.invalidationConditions.map((o, i) => <li key={i}>{o}</li>)}</ul></div>
      )}
      {d.missingData.length > 0 && (
        <div className="dz-sec"><div className="dz-sec__t">欠損データ(正直な限界)</div>
          <ul className="dz-list dz-list--muted">{d.missingData.map((o, i) => <li key={i}>{o}</li>)}</ul></div>
      )}
      <div className="dz-disc">証拠 {d.evidence.length}件 · {d.disclaimerJa}</div>
    </div>
  );
}

export function EventRow({ e, open, onToggle }: { e: ActiveEvent; open: boolean; onToggle: () => void }) {
  const dir = eventDir(e);
  const dc = dirColor(dir);
  const t = eventTime(e);
  const strong = _STRONG_POSTURE.has(e.recommendedPosture);
  const posture = POSTURE_JA[e.recommendedPosture] ?? e.recommendedPosture;
  // Status line: reasonJa already contains the type word + % (e.g. "急騰 +10.79%"),
  // so we DON'T also print TYPE_JA — that was the duplicate ("急騰 / 急騰 +10%").
  const status = e.reasonJa || (TYPE_JA[e.eventType] ?? e.eventType);
  return (
    <div className={`ei-row${open ? ' ei-row--open' : ''}`}>
      <button className="ei-row__head" onClick={onToggle}>
        <span className="ei-row__l1">
          {t && <span className="ei-row__time">{t}</span>}
          {e.severity >= 5 && <span className="ei-row__sev">S{e.severity}</span>}
          <span className="ei-row__caret">{open ? '▾' : '▸'}</span>
        </span>
        <span className="ei-row__l2">
          <span className="ei-row__dot" style={{ background: dc }} />
          {e.nameJa ? `${e.nameJa}(${e.symbol})` : e.symbol}
        </span>
        <span className="ei-row__l3">
          <span className="ei-row__status" style={{ color: dc }}>
            {dir === 'up' ? '▲' : dir === 'down' ? '▼' : '・'} {status}
          </span>
          {posture && <span className={`ei-advice${strong ? ' ei-advice--strong' : ''}`}>{posture}</span>}
        </span>
      </button>
      {open && <DossierDetail eventId={e.eventId} />}
    </div>
  );
}

export const EventIntelligenceCard: React.FC = () => {
  const { events, status, loading } = useEventsActive();
  const [openId, setOpenId] = React.useState<string | null>(null);

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
            {inSession ? '現在アラートはありません(S高/急変/フロー異常を検知中)。暗号資産は24時間監視。'
              : '市場時間外。株式の銘柄検知は次の取引時間(東京/米国)に再開。暗号資産のショックは24時間監視中(約30分間隔)。'}
          </div>
        ) : (
          <div className="ei-rows">
            {events.slice()
              .sort((a, b) => new Date(b.detectedAt || 0).getTime() - new Date(a.detectedAt || 0).getTime())
              .slice(0, 8).map((e) => (
              <EventRow key={e.eventId} e={e} open={openId === e.eventId}
                        onToggle={() => setOpenId(openId === e.eventId ? null : e.eventId)} />
            ))}
          </div>
        )}
        <div className="ei-foot">
          決定論的検知のみ(LLMなし)。値幅上限/下限への接近はTSE制限値幅で算出(取引所の特別気配フィールドではありません)。PTS・板(L2)・VWAPは未対応。
        </div>
      </div>
    </section>
  );
};

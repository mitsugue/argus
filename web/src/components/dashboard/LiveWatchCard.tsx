import React from 'react';
import { jpIntradayJa } from '../../lib/regimeLabels';
import { useDownsideIncidents } from '../../hooks/useDownsideIncidents';
import { useEventsActive } from '../../hooks/useEventsActive';
import { IncidentRow } from './DownsideIncidentCard';
import { EventRow } from './EventIntelligenceCard';
import './DownsideIncidentCard.css';
import './EventIntelligenceCard.css';
import './LiveWatchCard.css';

// Live Watch (v10.139) — the Today page's real-time per-stock hub. MERGES the
// former "Downside Watch" (drops + cause + holder action) and "24/7 Event
// Intelligence" (timestamped S高/急騰/急落/出来高/フロー/movers) into ONE feed so
// the owner sees all live per-stock activity in one place. No functionality is
// dropped — the rich incident rows and the timestamped event rows are reused as-is.
// Decision-support only; no order/broker controls.

const DOWN_TYPES = new Set(['LIMIT_DOWN', 'LIMIT_DOWN_PROXIMITY', 'PRICE_CRASH']);

export const LiveWatchCard: React.FC = () => {
  const { data: downside } = useDownsideIncidents();
  const { events, status } = useEventsActive();
  const [openId, setOpenId] = React.useState<string | null>(null);

  const incidents = downside?.incidents ?? [];
  const incidentSyms = new Set(incidents.map((i) => String(i.symbol).toUpperCase()));
  // Keep 24/7 events EXCEPT a downward event already covered by a richer incident
  // for the same symbol (avoid showing the same drop twice). Up-moves / S高 /
  // movers / flow are always shown — incidents only cover drops.
  const liveEvents = (events ?? [])
    .filter((e) => !(incidentSyms.has(String(e.symbol).toUpperCase()) && DOWN_TYPES.has(e.eventType)))
    .slice()
    .sort((a, b) => new Date(b.detectedAt || 0).getTime() - new Date(a.detectedAt || 0).getTime())
    .slice(0, 10);

  const overlayActive = !!downside?.jpIntradayOverlay && downside.jpIntradayOverlay !== 'NORMAL';
  const enabled = !!status?.enabled;
  const inSession = !!(status?.sessionJp || status?.sessionUs);
  const nothing = incidents.length === 0 && liveEvents.length === 0 && !overlayActive;

  const sessionLabel = enabled
    ? (status?.sessionJp ? '東京 取引時間中 — 検知 稼働中'
      : status?.sessionUs ? '米国 取引時間中 — 検知 稼働中'
      : '市場時間外 — 検知は次の取引時間から(暗号資産は24h)')
    : 'OFF';

  return (
    <section className="lw-card" aria-label="Live Watch">
      <header className="lw-head">
        <h2>Live Watch <span className="lw-jp">リアルタイム監視 — 下落・急変・大口フロー</span></h2>
        <span className="lw-status">
          <span className="lw-dot" style={{ background: enabled ? 'var(--value-positive)' : 'var(--text-muted)' }} />
          <span style={{ color: enabled ? 'var(--value-positive)' : 'var(--text-muted)' }}>{enabled ? (inSession ? '稼働中' : '時間外') : 'OFF'}</span>
        </span>
      </header>

      {overlayActive && (
        <div className="lw-overlay">
          <span className={`dic-overlay dic-overlay--${downside?.jpIntradayOverlay === 'RISK_OFF_WATCH' ? 'red' : 'amber'}`}>
            日本ザラ場: {jpIntradayJa(downside?.jpIntradayOverlay)}
          </span>
          {downside?.overlay?.reasonJa && <p className="dic-overlay-reason">{downside.overlay.reasonJa}</p>}
        </div>
      )}
      {downside?.holderRiskOverlay === 'REVIEW_REQUIRED' && (
        <p className="dic-holder">保有銘柄が影響を受けています。通常のHOLDとして扱わず点検してください。</p>
      )}

      {/* 1) Drops with cause + holder action (Downside layer) */}
      {incidents.map((inc) => <IncidentRow key={inc.incidentId} inc={inc} />)}

      {/* 2) Live timestamped activity (24/7 backbone): 急騰/S高/出来高/フロー/movers */}
      {liveEvents.length > 0 && (
        <div className="ei-rows lw-events">
          {liveEvents.map((e) => (
            <EventRow key={e.eventId} e={e} open={openId === e.eventId}
                      onToggle={() => setOpenId(openId === e.eventId ? null : e.eventId)} />
          ))}
        </div>
      )}

      {nothing && (
        <p className="lw-empty">{inSession
          ? '現在アラートはありません(S高/急変/大口フロー・保有の下落を検知中)。'
          : '市場時間外 — 株式の銘柄検知は次の取引時間(東京/米国)から。暗号資産のショックは24時間監視中。'}</p>
      )}

      <footer className="lw-foot">
        <span>{sessionLabel}</span>
        <span>決定支援のみ・自動売買なし。検知は決定論(LLMなし)・PTS/板(L2)/VWAPは未対応。</span>
      </footer>
    </section>
  );
};

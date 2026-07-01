import React, { useMemo } from 'react';
import { LiveEventRow } from '../dashboard/LiveEventRow';
import { CaosEvents } from '../dashboard/CaosEvents';
import { useEventRadar } from '../../hooks/useEventRadar';
import type { CalendarEvent, Escalation, EventSource } from '../../types/events';

// Scheduled-event calendar + escalation policy. The crisis News Radar moved INTO the
// C.A.O.S. hub (v10.192) — the owner noted crisis-theme detection IS a C.A.O.S. role —
// so this page keeps "what's coming" next to "where we are now".

// Plain-Japanese proximity labels (was D-7/D-3/D-1 jargon) — the escalation policy
// itself is kept; only the cryptic window codes are made readable (v10.162).
const ESCALATION = [
  { when: '1週間前', label: '警戒(認識)',           note: '認識のみ。ポジション縮小は不要。' },
  { when: '数日前',   label: '新規エントリー抑制',     note: '新規の高確信サテライト・ポジションを避ける。' },
  { when: '前日',     label: '大きな新規ポジ禁止',     note: '現金保持。イベントウィンドウ内の新規エントリーなし。' },
  { when: '当日',     label: '発表まで様子見',         note: 'ポジションを動かさず。発表後 30 分以内に再評価。' },
  { when: '翌日',     label: '解消 / 押し目買い判定', note: 'リスク解消なら再エントリー、押し目なら段階買い。' },
];

const ESC_RANK: Record<Escalation, number> = {
  D: 0, 'D-1': 1, 'D-3': 2, 'D-7': 3, 'D+1': 4, normal: 5,
};

const SOURCE_DOT: Record<string, string> = {
  live: 'var(--green)', partial: 'var(--amber)', error: 'var(--red)', mock: 'var(--amber)',
};

const SourceStrip: React.FC<{ sources: EventSource[] }> = ({ sources }) => (
  <div className="evt-sources">
    {sources.map((s) => (
      <span className="evt-sources__item" key={s.name}>
        <span className="evt-sources__dot" style={{ background: SOURCE_DOT[s.status] ?? 'var(--text-muted)' }} />
        {s.name} <span className="evt-sources__status">{s.status}</span>
      </span>
    ))}
  </div>
);

export const MarketEventsSections: React.FC = () => {
  const { data, phase, attempt } = useEventRadar();

  const sorted = useMemo<CalendarEvent[]>(() => {
    const events = data?.events ?? [];
    return events.slice().sort(
      (a, b) => (ESC_RANK[a.escalation] - ESC_RANK[b.escalation]) || (a.daysUntil - b.daysUntil),
    );
  }, [data]);

  const statusLabel =
    phase === 'connecting' ? (attempt > 1 ? `waking backend · try ${attempt}` : 'connecting') : phase;
  const asOfDate = data?.asOf ? data.asOf.slice(0, 10) : null;

  return (
    <>
      {/* C.A.O.S. pre/post-event analysis — the prose read that sits with the calendar. */}
      <CaosEvents />

      <section>
        <div className="section-head">
          <span className="section-head__title">Upcoming events</span>
          <span className={`watch-status watch-status--${phase}`}>{statusLabel}</span>
          {phase !== 'connecting' && asOfDate ? (
            <span className="section-head__count">{phase} · as of {asOfDate}</span>
          ) : (
            <span className="section-head__count">{sorted.length}</span>
          )}
        </div>
        {data && <SourceStrip sources={data.sources} />}
        <div className="card event-list">
          {sorted.map((e) => (
            <LiveEventRow key={e.id} event={e} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Escalation policy</span>
        </div>
        <div className="card event-list">
          {ESCALATION.map((row) => (
            <div className="event-row" key={row.when}>
              <span className="event-row__when">{row.when}</span>
              <span className="event-row__title">{row.label}</span>
              <span />
              <span />
              <span className="event-row__note">{row.note}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
};

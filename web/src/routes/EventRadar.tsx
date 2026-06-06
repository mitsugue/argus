import React from 'react';
import { PageShell } from './PageShell';
import { EventRow } from '../components/dashboard/EventRow';
import { upcomingEvents } from '../mock/dashboard';
import '../components/dashboard/Dashboard.css';

// Window labels stay short English (D-7..D+1) — they're structural.
// Stage label + note in JP for the user's transition phase.
const ESCALATION = [
  { window: 'D-7', label: '警戒(認識)',           note: '認識のみ。ポジション縮小は不要。' },
  { window: 'D-3', label: '新規エントリー抑制',     note: '新規の高確信サテライト・ポジションを避ける。' },
  { window: 'D-1', label: '大きな新規ポジ禁止',     note: '現金保持。イベントウィンドウ内の新規エントリーなし。' },
  { window: 'D',   label: '発表まで様子見',         note: 'ポジションを動かさず。発表後 30 分以内に再評価。' },
  { window: 'D+1', label: '解消 / 押し目買い判定', note: 'リスク解消なら再エントリー、押し目なら段階買い。' },
];

export const EventRadar: React.FC = () => {
  const sorted = upcomingEvents.slice().sort((a, b) => a.at - b.at);
  return (
    <PageShell
      title="Event Radar"
      subtitle="Scheduled and unscheduled events that drive the action labels."
    >
      <section>
        <div className="section-head">
          <span className="section-head__title">Upcoming</span>
          <span className="section-head__count">{sorted.length}</span>
        </div>
        <div className="card event-list">
          {sorted.map((e) => (
            <EventRow key={e.id} event={e} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Escalation policy</span>
        </div>
        <div className="card event-list">
          {ESCALATION.map((row) => (
            <div className="event-row" key={row.window}>
              <span className="event-row__when">{row.window}</span>
              <span className="event-row__title">{row.label}</span>
              <span />
              <span />
              <span className="event-row__note">{row.note}</span>
            </div>
          ))}
        </div>
      </section>
    </PageShell>
  );
};

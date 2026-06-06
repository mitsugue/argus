import React from 'react';
import { PageShell } from './PageShell';
import { EventRow } from '../components/dashboard/EventRow';
import { upcomingEvents } from '../mock/dashboard';
import '../components/dashboard/Dashboard.css';

const ESCALATION = [
  { window: 'D-7', label: 'Caution',                     note: 'Awareness; no scaling-down required.' },
  { window: 'D-3', label: 'Reduce aggressive entries',   note: 'Avoid new high-conviction satellite positions.' },
  { window: 'D-1', label: 'Avoid large new positions',   note: 'Hold cash; no event-window entries.' },
  { window: 'D',   label: 'Wait until release',          note: 'Sit out. Reassess within 30 minutes after print.' },
  { window: 'D+1', label: 'Evaluate cleared / dip-buy',  note: 'Either risk cleared → re-engage, or opportunity → phased buy.' },
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

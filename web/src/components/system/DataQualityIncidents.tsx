import React from 'react';
import type { DataQualityIncident } from '../../domain/dataQualityIncidents';
import './SystemDecision.css';

export const DataQualityIncidents: React.FC<{ incidents: DataQualityIncident[] }> = ({ incidents }) => (
  <section className="dq-incidents" aria-labelledby="active-incidents">
    <div className="section-head">
      <span className="section-head__title" id="active-incidents">ACTIVE INCIDENTS</span>
      <span className="section-head__count">{incidents.length} actionable</span>
    </div>
    {!incidents.length ? <div className="card dq-incidents__quiet">
      判断へ影響するactive incidentはありません。
    </div> : <div className="dq-incidents__table" role="table" aria-label="Actionable data incidents">
      {incidents.map((incident) => <article key={incident.id} role="row" data-severity={incident.severity}>
        <b>{incident.severity.toUpperCase()}</b>
        <strong>{incident.feature}</strong>
        <span><em>IMPACT</em>{incident.impact}</span>
        <span><em>LAST SUCCESS</em>{incident.lastSuccess}</span>
        <span><em>STATE</em>{incident.currentState}</span>
        <span><em>NEXT RETRY</em>{incident.nextRetry}</span>
        <span><em>OWNER ACTION</em>{incident.ownerAction}</span>
      </article>)}
    </div>}
  </section>
);

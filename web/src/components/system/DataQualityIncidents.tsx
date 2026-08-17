import React from 'react';
import type { DataQualityIncident } from '../../domain/dataQualityIncidents';
import './SystemDecision.css';

export const DataQualityIncidents: React.FC<{ incidents: DataQualityIncident[] }> = ({ incidents }) => (
  <section className="dq-incidents" aria-labelledby="active-incidents">
    <div className="section-head">
      <span className="section-head__title" id="active-incidents">ACTIVE INCIDENTS</span>
      <span className="section-head__count">
        {incidents.length} actionable
        {incidents.some((item) => item.severity === 'critical')
          ? ` · ${incidents.filter((item) => item.severity === 'critical').length} critical` : ''}
      </span>
    </div>
    {!incidents.length ? <div className="card dq-incidents__quiet">
      判断へ影響するactive incidentはありません。
    </div> : <div className="dq-incidents__table-wrap">
      <table className="dq-incidents__table" aria-label="Actionable data incidents">
        <thead><tr>
          <th>SEVERITY</th><th>FEATURE</th><th>IMPACT</th><th>LAST SUCCESS</th>
          <th>STATE</th><th>NEXT RETRY</th><th>OWNER ACTION</th>
        </tr></thead>
        <tbody>{incidents.map((incident) => (
          <tr key={incident.id} data-severity={incident.severity}>
            <td data-label="SEVERITY"><b>{incident.severity.toUpperCase()}</b></td>
            <td data-label="FEATURE"><strong>{incident.feature}</strong></td>
            <td data-label="IMPACT">{incident.impact}</td>
            <td data-label="LAST SUCCESS">{incident.lastSuccess}</td>
            <td data-label="STATE">{incident.currentState}</td>
            <td data-label="NEXT RETRY">{incident.nextRetry}</td>
            <td data-label="OWNER ACTION">{incident.ownerAction}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>}
  </section>
);

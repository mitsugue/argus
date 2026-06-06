import React from 'react';
import { PageShell } from './PageShell';
import { AlertCard } from '../components/dashboard/AlertCard';
import { CoreRow } from '../components/dashboard/CoreRow';
import { actionAlerts, indexFundStatus } from '../mock/dashboard';
import '../components/dashboard/Dashboard.css';

export const ActionAlerts: React.FC = () => {
  return (
    <PageShell
      title="Action Alerts"
      subtitle="One judgment per asset class. Satellites first; index funds at the bottom."
    >
      <section>
        <div className="section-head">
          <span className="section-head__title">Satellites</span>
          <span className="section-head__count">
            {actionAlerts.length} classes
          </span>
        </div>
        <div className="alert-grid">
          {actionAlerts.map((c) => (
            <AlertCard key={c.assetClass} card={c} />
          ))}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Index Funds</span>
          <span className="section-head__count">
            {indexFundStatus.length} positions
          </span>
        </div>
        <div className="card core-list">
          {indexFundStatus.map((p) => (
            <CoreRow key={p.symbol} position={p} />
          ))}
        </div>
      </section>
    </PageShell>
  );
};

import React from 'react';
import { PageShell } from './PageShell';
import { CoreRow } from '../components/dashboard/CoreRow';
import { indexFundStatus } from '../mock/dashboard';
import '../components/dashboard/Dashboard.css';

export const CorePortfolio: React.FC = () => {
  return (
    <PageShell
      title="Core Portfolio"
      subtitle="Long-term index accumulation. Calm vocabulary — no daily trade triggers."
    >
      <section>
        <div className="section-head">
          <span className="section-head__title">Positions</span>
          <span className="section-head__count">{indexFundStatus.length}</span>
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

import React from 'react';
import type { PortfolioCommandView } from '../../domain/assetDesk';

export const AssetPortfolioCommand: React.FC<{ command: PortfolioCommandView }> =
({ command }) => (
  <section className="ad-command" aria-labelledby="asset-portfolio-command">
    <div className="ad-command__copy">
      <span className="ad-command__eyebrow" id="asset-portfolio-command">
        TODAY&apos;S PORTFOLIO COMMAND
      </span>
      <strong>{command.primaryCommandJa}</strong>
      <small>{command.supportingSummaryJa}</small>
    </div>
    <div className="ad-command__counters" aria-label="資産判断の集計">
      {command.counters.map((counter) => (
        <span key={counter.key} data-command-counter={counter.key}>
          <b>{counter.count}</b>{counter.labelJa}
        </span>
      ))}
    </div>
  </section>
);

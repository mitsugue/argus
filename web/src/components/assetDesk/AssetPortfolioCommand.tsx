import React from 'react';
import type { PortfolioCommandView } from '../../domain/assetDesk';

interface Props {
  command: PortfolioCommandView;
  onSelect?: (key: PortfolioCommandView['counters'][number]['key']) => void;
  activeKey?: string;
}

export const AssetPortfolioCommand: React.FC<Props> = ({ command, onSelect, activeKey }) => (
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
        <button type="button" key={counter.key} data-command-counter={counter.key}
          className={activeKey === counter.key ? 'is-active' : ''}
          aria-pressed={activeKey === counter.key}
          onClick={() => onSelect?.(counter.key)}>
          <b>{counter.count}</b>{counter.labelJa}
        </button>
      ))}
    </div>
  </section>
);

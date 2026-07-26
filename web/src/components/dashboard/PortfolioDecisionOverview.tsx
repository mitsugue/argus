import React from 'react';
import type { PortfolioDecisionOverview as Overview } from '../../domain/portfolioDecisionView';
import { SignedValue } from '../common/SignedValue';
import './PortfolioDecisionOverview.css';

const fmtJpy = (value: number) => `¥${Math.round(value).toLocaleString('ja-JP')}`;

export const PortfolioDecisionOverview: React.FC<{ view: Overview }> = ({ view }) => (
  <section className="cp-overview" aria-labelledby="portfolio-command">
    <div className="cp-overview__command">
      <span>PORTFOLIO COMMAND</span>
      <h2 id="portfolio-command">{view.command}</h2>
    </div>
    <div className="cp-overview__grid">
      <article>
        <span>TOTAL EXPOSURE</span>
        <strong>{view.exposure.valueJpy == null ? '未算出' : fmtJpy(view.exposure.valueJpy)}</strong>
        <small>
          {view.exposure.plJpy == null ? '損益未算出'
            : <>損益 <SignedValue value={view.exposure.plJpy} digits={0} />円</>}
          {' · '}{view.exposure.pricedCount} priced / {view.exposure.unpricedCount} unpriced
        </small>
      </article>
      <article>
        <span>TOP RISKS</span>
        {view.topRisks.length ? view.topRisks.map((risk) => (
          <p key={risk.label} data-severity={risk.severity}><b>{risk.label}</b>{risk.value}</p>
        )) : <small>計算可能な集中リスクなし</small>}
      </article>
      <article className="cp-overview__queue">
        <span>ACTION QUEUE</span>
        {view.actionQueue.length ? view.actionQueue.map((item) => (
          <p key={`${item.symbol}-${item.action}`} data-severity={item.severity}>
            <b>{item.symbol}</b>{item.action}
          </p>
        )) : <small>緊急調整なし</small>}
      </article>
      <article>
        <span>STRESS</span>
        {view.stressConditions.map((condition) => <p key={condition}>{condition}</p>)}
      </article>
      <article>
        <span>NEXT PORTFOLIO CHECK</span>
        {view.nextChecks.map((check) => <p key={check}>{check}</p>)}
      </article>
    </div>
  </section>
);

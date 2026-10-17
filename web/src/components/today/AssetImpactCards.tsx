import React from 'react';
import type { TodayHoldingInput } from '../../domain/argusTodayView';
import '../common/AssetReadingCard.css';
import './AssetImpactCards.css';

const IMPACT_JA = { Good: '追い風', Bad: '逆風', Neutral: '中立' } as const;

export const AssetImpactCards: React.FC<{
  items: TodayHoldingInput[];
  onNavigateToAsset?: (symbol: string) => void;
}> = ({ items, onNavigateToAsset }) => (
  <div className="at-asset-impact-list">
    {items.map((item) => {
      const impact = item.impact ?? 'Neutral';
      const content = <>
        <span className="at-asset-impact__head">
          <b>{item.name?.trim() || item.symbol}</b>
          <mark className={`is-${impact.toLowerCase()}`}>{IMPACT_JA[impact]}</mark>
        </span>
        <span className="at-asset-impact__meta">
          <span>{item.symbol}</span><span>{item.isHeld ? '保有' : '登録'}</span>
          {item.statusJa && item.statusJa !== item.actionJa && <span>{item.statusJa}</span>}
        </span>
        {(item.actionJa || item.statusJa) && <strong className="at-asset-impact__action">{item.actionJa || item.statusJa}</strong>}
        <span className="at-asset-impact__reason">{item.reasonJa}</span>
        <span className="at-asset-impact__next"><b>次の確認</b><span>{item.checkNextJa || '根拠の更新待ち'}</span></span>
        {item.whatWouldChangeJa && <span className="at-asset-impact__next"><b>見方を変える条件</b><span>{item.whatWouldChangeJa}</span></span>}
        {onNavigateToAsset && <span className="at-asset-impact__open" aria-hidden="true">銘柄の詳細へ <span>→</span></span>}
      </>;
      return onNavigateToAsset
        ? <button type="button" className="asset-reading-card at-asset-impact" key={item.symbol}
            aria-label={`${item.name?.trim() || item.symbol}の詳細を見る`}
            onClick={() => onNavigateToAsset(item.symbol)}>{content}</button>
        : <div className="asset-reading-card at-asset-impact" key={item.symbol}>{content}</div>;
    })}
  </div>
);

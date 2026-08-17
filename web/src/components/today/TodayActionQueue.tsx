import React from 'react';
import type { TodayActionView } from '../../domain/todayOverview';
import './Today.css';

// V12.2.11 — Action Queue: Session Brief / Action Priority / Position Plan の
// **表示**をひとつに統合(計算とpublishは既存のまま)。最大3件・重複排除済み。
// 免責はこのセクション末尾に1回だけ。

export const TodayActionQueue: React.FC<{
  actions: TodayActionView[];
  /** V12.2.12: 銘柄付きアクション→Asset Deskの当該カードを開く。 */
  onOpenAsset?: (symbol: string) => void;
}> = ({ actions, onOpenAsset }) => (
  <section className="tcard tg-span-8" aria-label="Action queue">
    <div className="tcard__head">
      <span className="tcard__title">Action Queue</span>
    </div>
    {actions.length === 0 ? (
      <p className="tq__empty">今日の緊急アクションはありません。定例の巡回で十分です。</p>
    ) : (
      <div className="tq">
        {actions.map((a) => (
          <div className="tq__row" key={a.id}>
            <span className={`tq__timing${a.timing === 'NOW' ? ' tq__timing--now' : ''}`}>
              {a.timing}
            </span>
            <span className="tq__action">
              {a.targetJa && (a.symbol && onOpenAsset ? (
                <button type="button" className="tq__target tq__target--link"
                        title="Asset Deskでこの銘柄を開く"
                        onClick={() => onOpenAsset(a.symbol!)}>{a.targetJa} ↗</button>
              ) : (
                <span className="tq__target">{a.targetJa}</span>
              ))}
              {a.actionJa}
              {a.priorityRank && (a.priorityRank === 'P0' || a.priorityRank === 'P1') && (
                <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}
                  title={a.priorityRank === 'P0' ? 'P0 = 最優先確認' : 'P1 = 今日の優先'}>
                  {a.priorityRank === 'P0' ? '最優先' : '優先'}
                </span>
              )}
            </span>
            <p className="tq__reason">
              {a.reasonJa}
              {a.conditionJa && <span className="tq__cond"> — 条件: {a.conditionJa}</span>}
            </p>
          </div>
        ))}
      </div>
    )}
    <p className="tq__note">注意配分と計画の統合表示 — 売買指示ではなく、判断は利用者本人が行います。</p>
  </section>
);

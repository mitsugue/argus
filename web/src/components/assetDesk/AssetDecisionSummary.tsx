import React, { useEffect, useState } from 'react';
import { useTachibanaLiveDocument } from '../../hooks/useDecisionEvidence';
import { tachibanaCurrentRows, formatJpy } from '../../domain/tachibanaLive';
import type { DeskCardData } from './types';
import { SignedValue } from '../common/SignedValue';
import { quoteAsOf, quoteFreshnessJa } from '../../domain/liveQuote';

// V12.2.12 — 閉じたカード(§6): 開かなくても「何をどうするか」が分かる1枚。
// 主判断は検証済み Single Decision Authority の出力だけを表示する。

const GENRE_TAG: Record<string, string> = { jp: '日本株', us: '米国株', funds: '投信', crypto: '暗号資産' };

const ACTION_TONE = { BUY: 'var(--value-positive)', HOLD: 'var(--accent)',
  WAIT: 'var(--amber, #fbbf24)', REDUCE: 'var(--event-high)', EXIT: 'var(--value-negative)' };

export const AssetDecisionSummary: React.FC<{
  d: DeskCardData; open: boolean; onToggle: () => void; interactive?: boolean;
}> = ({ d, open, onToggle, interactive = true }) => {
  const view = d.decisionFirst;
  const liveDocument = useTachibanaLiveDocument();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (liveDocument?.displayApproved !== true) return;
    const timer = window.setInterval(() => setNow(Date.now()), 5_000);
    return () => window.clearInterval(timer);
  }, [liveDocument?.displayApproved]);
  // Display projection only: decisionFirst, its evidence and actions stay unchanged.
  const live = d.genre === 'jp' ? tachibanaCurrentRows(liveDocument, Math.max(now, Date.now())).get(view.symbol.toUpperCase()) : null;
  const shownChange = live?.changePct ?? view.changePct;
  const shownAction = ({ WAIT: '確認待ち', HOLD: '維持', REDUCE: '縮小を検討', EXIT: '売却を検討', BUY: '買い候補' } as Record<string, string>)[view.currentActionJa] ?? view.currentActionJa;
  const sigColor = ACTION_TONE[view.canonicalPrimaryAction ?? 'WAIT'];

  const content = <>
      <span className="ad-l1">
        {view.held ? <span className="ad-held">保有</span> : <span className="ad-watch">登録</span>}
        <span className="ad-sym">{view.symbol}</span>
        <span className="ad-name">{view.name}</span>
        <span className="ad-mkt">{GENRE_TAG[d.genre]}</span>
        <span className="ad-price">{live ? `${formatJpy(live.price)}円` : view.priceText}</span>
        <span className="ad-chg">{shownChange == null ? '—'
          : <SignedValue value={shownChange} suffix="%" arrow={false} />}</span>
        {interactive && <span className="ad-chevron" aria-hidden>{open ? '−' : '+'}</span>}
      </span>
      <span className="ad-l2">
        <span className="ad-cmd" style={{ color: sigColor }}>{shownAction}</span>
        {view.canonicalDecisionStatus && <span className="ad-data">
          {view.canonicalDecisionStatus === 'DATA_GATED' ? '判断に必要な条件を確認中' : '判断条件を評価済み'}
        </span>}
        <span className="ad-owner-state">
          {view.held
            ? `保有損益 ${view.pnlPct == null ? '未計算'
              : `${view.pnlPct >= 0 ? '+' : ''}${view.pnlPct.toFixed(1)}%`}`
            : ''}
        </span>
        <span className="ad-data">{view.dataStatus}</span>
      </span>
      {live && <span className="ad-quote-meta"><mark data-delay="LIVE">リアルタイム</mark><span>立花証券 · {new Date(live.sourceTimestamp!).toLocaleTimeString('ja-JP')}</span></span>}
      {!live && view.quoteTruth && <span className="ad-quote-meta" data-instrument-type={view.quoteTruth.instrumentType}>

        <mark data-delay={view.quoteTruth.delayClass}>{{ LIVE: 'リアルタイム', '15m': '15分遅延', '20m': '20分遅延', EOD: '終値', 'T-1': '前日', UNKNOWN: '時刻未確認', OFFLINE: '未取得' }[view.quoteTruth.delayClass]}</mark>
        {/* v13.5.62: one plain freshness line (kind · provider · as of); the exact
            source stamp stays reachable on long-press. */}
        <span title={quoteAsOf(view.quoteTruth)}>{quoteFreshnessJa(view.quoteTruth)}</span>
      </span>}
    </>;
  const label = `${view.symbol} ${view.name}, ${view.currentActionJa}`;
  return interactive ? (
    <button className="ad-head" onClick={onToggle} aria-expanded={open} aria-label={label}>
      {content}
    </button>
  ) : (
    <div className="ad-head" aria-label={label}>{content}</div>
  );
};

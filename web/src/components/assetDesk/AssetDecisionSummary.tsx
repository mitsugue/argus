import React, { useEffect, useState } from 'react';
import { useTachibanaLiveDocument } from '../../hooks/useDecisionEvidence';
import { tachibanaCurrentRows, tachibanaPriceReferenceRows, tachibanaPriceTime, formatJpy } from '../../domain/tachibanaLive';
import type { DeskCardData } from './types';
import { SignedValue } from '../common/SignedValue';
import { quoteAsOf, quoteFreshnessJa } from '../../domain/liveQuote';
import { useAnalystTargetState } from '../../hooks/useAnalystTargets';
import { AssetEarningsDate } from './AssetEarnings';
import { AssetOutlookSummary } from './AssetOutlookSummary';
import { cryptoPriceDisplay } from '../../domain/cryptoPriceDisplay';
import { fmtPrice } from './deskFormat';

// 登録銘柄の事実を先に表示する。旧保有判断は内部の制限・履歴に残す。

const GENRE_TAG: Record<string, string> = { jp: '日本株', us: '米国株', funds: '投信', crypto: '暗号資産' };

export const AssetDecisionSummary: React.FC<{
  d: DeskCardData; open: boolean; onToggle: () => void; interactive?: boolean;
}> = ({ d, open, onToggle, interactive = true }) => {
  const view = d.decisionFirst;
  const liveDocument = useTachibanaLiveDocument();
  const analyst = useAnalystTargetState();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (liveDocument?.displayApproved !== true) return;
    const timer = window.setInterval(() => setNow(Date.now()), 5_000);
    return () => window.clearInterval(timer);
  }, [liveDocument?.displayApproved]);
  // Display projection only: decisionFirst, its evidence and actions stay unchanged.
  const live = d.genre === 'jp' ? tachibanaCurrentRows(liveDocument, Math.max(now, Date.now())).get(view.symbol.toUpperCase()) : null;
  const reference = d.genre === 'jp'
    ? tachibanaPriceReferenceRows(liveDocument, Math.max(now, Date.now())).get(view.symbol.toUpperCase()) : null;
  const receivedCurrent = reference?.receivedAt && liveDocument?.providerHealth === 'AVAILABLE'
    && ['LIVE', 'DEGRADED', 'STALE', 'CLOSED'].includes(liveDocument.status ?? '')
    ? Math.max(now, Date.now()) - Date.parse(reference.receivedAt) <= 15_000 : false;
  const shownPrice = live?.price ?? reference?.price ?? null;
  const crypto = d.genre === 'crypto' ? cryptoPriceDisplay(d.cryptoDisplayQuote) : null;
  const shownChange = crypto ? crypto.changePct : live ? live.changePct : reference ? reference.changePct : view.changePct;
  const targetKey = `${d.asset.market}:${view.symbol.toUpperCase()}`;
  const currentPrice = shownPrice ?? (d.strat.status === 'mock' ? null : d.strat.price ?? d.card?.price ?? null);

  const content = <>
      <span className="ad-l1">
        {view.held ? <span className="ad-held">保有</span> : <span className="ad-watch">登録</span>}
        <span className="ad-sym">{view.symbol}</span>
        <span className="ad-name">{view.name}</span>
        <span className="ad-mkt">{GENRE_TAG[d.genre]}</span>
        <span className="ad-price">{crypto ? fmtPrice('CRYPTO', crypto.priceUsd) : shownPrice != null ? `${formatJpy(shownPrice)}円` : view.priceText === '—' ? '価格未取得' : view.priceText}</span>
        <span className="ad-chg">{shownChange == null ? '—'
          : <SignedValue value={shownChange} suffix="%" arrow={false} />}</span>
        {interactive && <span className="ad-chevron" aria-hidden>{open ? '−' : '+'}</span>}
      </span>
      <span className="ad-l2">
        <span className="ad-owner-state">
          {view.held
            ? `保有損益 ${view.pnlPct == null ? '未計算'
              : `${view.pnlPct >= 0 ? '+' : ''}${view.pnlPct.toFixed(1)}%`}`
            : ''}
        </span>
        {!crypto && <span className="ad-data">{reference ? '分析の価格基準は保存時点' : view.dataStatus}</span>}
      </span>
      {live && <span className="ad-quote-meta"><mark data-delay="LIVE">リアルタイム</mark><span>{tachibanaPriceTime(live)}</span></span>}
      {!live && reference && <span className="ad-quote-meta" data-price-reference="TACHIBANA">
        <mark data-delay="UNKNOWN">{receivedCurrent
          ? reference.marketStatus === 'CLOSED' ? '市場クローズ・受信価格' : '受信価格・参考'
          : liveDocument?.priceRecordsRetained ? '受信停止・保存価格' : '保存価格'}</mark>
        <span>価格 {tachibanaPriceTime(reference)}</span>
      </span>}
      {crypto && <span className="ad-quote-meta" data-instrument-type="CRYPTO">
        <mark data-delay={crypto.delay}>{d.cryptoRefreshFailed ? '更新失敗・保存価格' : crypto.label}</mark>
        <span title={crypto.title}>{crypto.detail}</span>
      </span>}
      {!live && !reference && !crypto && view.quoteTruth && <span className="ad-quote-meta" data-instrument-type={view.quoteTruth.instrumentType}>

        <mark data-delay={view.quoteTruth.delayClass}>{{ LIVE: 'リアルタイム', '15m': '15分遅延', '20m': '20分遅延', EOD: '終値', 'T-1': '前日', UNKNOWN: '時刻未確認', OFFLINE: '未取得' }[view.quoteTruth.delayClass]}</mark>
        {/* v13.5.62: one plain freshness line (kind · provider · as of); the exact
            source stamp stays reachable on long-press. */}
        <span title={quoteAsOf(view.quoteTruth)}>{quoteFreshnessJa(view.quoteTruth)}</span>
      </span>}
      <AssetEarningsDate market={d.asset.market} row={analyst.earnings?.[targetKey]} loading={analyst.loading} refreshFailed={analyst.refreshFailed} />
      <AssetOutlookSummary market={d.asset.market} target={analyst.items[targetKey]}
        targetStatus={analyst.availability[targetKey]?.status} loading={analyst.loading}
        refreshFailed={analyst.refreshFailed} currentPrice={currentPrice} supply={d.sdg} />
    </>;
  const label = `${view.symbol} ${view.name}, 銘柄の情報`;
  return interactive ? (
    <button className="ad-head" onClick={onToggle} aria-expanded={open} aria-label={label}>
      {content}
    </button>
  ) : (
    <div className="ad-head" aria-label={label}>{content}</div>
  );
};

import React, { useEffect, useState } from 'react';
import { useTachibanaLiveDocument } from '../../hooks/useDecisionEvidence';
import { tachibanaCurrentRows, tachibanaPriceReferenceRows, tachibanaPriceTime, formatJpy } from '../../domain/tachibanaLive';
import type { DeskCardData } from './types';
import { SignedValue } from '../common/SignedValue';
import { useAnalystTargetState } from '../../hooks/useAnalystTargets';
import { earningsShortDate } from '../../domain/assetEarnings';
import { cryptoPriceDisplay } from '../../domain/cryptoPriceDisplay';
import { fmtPrice } from './deskFormat';

// 2026-10-25 (owner): two lines a stock. The name and price, then the one
// thing to notice (a drop, a price that is not current, or the next results
// date) and the day's change. Colour is used for a warning only.

const PRICE_PROBLEM: Record<string, string> = { UNKNOWN: '時刻未確認', OFFLINE: '未取得', 'T-1': '前日の値' };

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
  const at = Math.max(now, Date.now());
  const live = d.genre === 'jp' ? tachibanaCurrentRows(liveDocument, at).get(view.symbol.toUpperCase()) : null;
  const reference = d.genre === 'jp' ? tachibanaPriceReferenceRows(liveDocument, at).get(view.symbol.toUpperCase()) : null;
  const shownPrice = live?.price ?? reference?.price ?? null;
  const crypto = d.genre === 'crypto' ? cryptoPriceDisplay(d.cryptoDisplayQuote) : null;
  const shownChange = crypto ? crypto.changePct : live ? live.changePct : reference ? reference.changePct : view.changePct;
  const price = crypto ? fmtPrice('CRYPTO', crypto.priceUsd) : shownPrice != null ? `${formatJpy(shownPrice)}円`
    : view.priceText === '—' ? '価格未取得' : view.priceText;
  const drop = d.incident && d.incident.severity !== 'low'
    ? `急落${d.incident.changePct != null ? ` ${d.incident.changePct.toFixed(1)}%` : ''}` : null;
  // A received real-time price shows its time beside the change; a received
  // price that is no longer current says so in one word with its time.
  const receivedCurrent = !!reference?.receivedAt && liveDocument?.providerHealth === 'AVAILABLE'
    && ['LIVE', 'DEGRADED', 'STALE', 'CLOSED'].includes(liveDocument.status ?? '')
    && at - Date.parse(reference.receivedAt) <= 15_000;
  const referenceWord = !live && reference
    ? `${receivedCurrent && reference.marketStatus === 'CLOSED' ? '引け後' : receivedCurrent ? '参考価格' : '受信停止'} ${tachibanaPriceTime(reference)}`
    : null;
  const priceProblem = crypto ? (d.cryptoRefreshFailed ? '更新失敗' : null)
    : referenceWord ?? (!live && !reference && view.quoteTruth ? PRICE_PROBLEM[view.quoteTruth.delayClass] ?? null : null);
  const earnings = earningsShortDate(analyst.earnings?.[`${d.asset.market}:${view.symbol.toUpperCase()}`]);
  const note = drop ?? priceProblem ?? (earnings ? `決算 ${earnings}` : null);

  const content = <>
    <span className="ad-l1">
      <span className="ad-sym">{view.symbol}</span>
      <span className="ad-name">{view.name}</span>
      <span className="ad-price">{price}</span>
      {interactive && <span className="ad-chevron" aria-hidden>{open ? '−' : '+'}</span>}
    </span>
    <span className="ad-l2">
      <span className={`ad-note${drop || (priceProblem && !referenceWord?.startsWith('引け後')) ? ' is-warning' : ''}`}>{note}</span>
      <span className="ad-chg">{shownChange == null ? '—' : <SignedValue value={shownChange} suffix="%" arrow={false} />}
        {live && <span className="ad-time" data-quote="LIVE">{tachibanaPriceTime(live)}</span>}</span>
    </span>
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

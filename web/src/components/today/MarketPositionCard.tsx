import React from 'react';
import type { MarketBrief, MarketPosition, MarketPositionTheme } from '../../lib/marketBrief';
import { marketWording, hasSubstantiveView } from '../../lib/marketWording';
import { friendlyEventText } from '../../lib/todayDecision';
import './MarketPositionCard.css';

// 13.8 §3-1 (owner direction 2026-10-03): before the numbers, where the market
// stands — the themes investors are watching, the measured pricing, the last
// release reading and the next check. Entries come from the server memory;
// nothing here is a forecast.
const statusLabel: Record<string, string> = { ACTIVE: '更新あり', QUIET: '更新待ち', EMPTY: '記録なし' };
const statusDescription: Record<string, string> = { ACTIVE: '14日以内に記録あり', QUIET: '14日間、新しい記録なし', EMPTY: 'このテーマの記録はまだありません' };
// A theme the server added because related news kept arriving (not one of the fixed seven).
const emergingDescription = '7日間で重要なニュースが続いた話題';
const breakingDescription = '重大な速報の話題';
const kindLabel: Record<string, string> = { NEWS: 'ニュース', RELEASE_REACTION: '発表の反応', PRICING: '織り込み', AI_VIEW: '見立て', RELEASE_RESULT: '公式結果', NEWS_CONTEXT: '関連報道' };
const jst = (iso?: string | null) => iso && Number.isFinite(Date.parse(iso))
  ? new Date(iso).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';

function ThemeRow({ theme }: { theme: MarketPositionTheme }) {
  const lead = theme.recent.find(row => row.kind !== 'AI_VIEW')?.textJa || theme.lastReaction?.textJa || '';
  const expectation = hasSubstantiveView(theme.view?.expectationJa) ? theme.view!.expectationJa : '';
  const fear = hasSubstantiveView(theme.view?.fearJa) ? theme.view!.fearJa : '';
  const chip = theme.emerging ? '新しい話題' : statusLabel[theme.status] ?? '確認中';
  const description = theme.emerging
    ? (theme.emergingBasis === 'BREAKING' ? breakingDescription : emergingDescription)
    : statusDescription[theme.status];
  return <details className="mp-theme" data-theme={theme.themeId} data-status={theme.status}
    data-emerging={theme.emerging ? 'true' : undefined}>
    <summary>
      <span className="mp-content"><span className="mp-heading"><b>{theme.labelJa}</b>
        <span className={`mp-chip is-${theme.status.toLowerCase()}`} title={description}>
          <i aria-hidden="true" />{chip}</span></span>
        {(expectation || lead) && <small>{marketWording(expectation || lead)}</small>}
        {theme.pricing?.ffImpliedRatePct != null && <small>政策金利の予想(FF先物) {theme.pricing.ffImpliedRatePct.toFixed(3)}%</small>}
        {fear && <small className="mp-fear">警戒: {marketWording(fear)}</small>}
        {theme.view && !expectation && !fear && <small className="mp-pending">期待・警戒の判断材料が不足しています</small>}
        {theme.nextEvent && <small>次: {friendlyEventText(theme.nextEvent.title)} {jst(theme.nextEvent.eventTimeUtc)}</small>}
      </span>
    </summary>
    {theme.view && (theme.view.expectationJa || theme.view.fearJa || theme.view.triggerJa) && <dl className="mp-view" data-view-kind={theme.view.kind ?? ''}>
      {theme.view.expectationJa && <><dt>市場の期待</dt><dd>{marketWording(theme.view.expectationJa)}</dd></>}
      {theme.view.fearJa && <><dt>市場の警戒</dt><dd>{marketWording(theme.view.fearJa)}</dd></>}
      {theme.view.triggerJa && <><dt>次の確認点</dt><dd>{marketWording(theme.view.triggerJa)}</dd></>}
      {theme.view.at && <dd className="mp-view-note">{jst(theme.view.at)}</dd>}
    </dl>}
    <p className="mp-empty">{description}{theme.lastUpdatedAt ? ` · 最終記録 ${jst(theme.lastUpdatedAt)}` : ''}</p>
    {theme.recent.length > 0 ? <ol className="mp-entries">
      {theme.recent.map(row => <li key={row.entryId} data-kind={row.kind} data-severity={row.severity}>
        <span>{jst(row.at)}</span><em>{kindLabel[row.kind] ?? row.kind}</em>{marketWording(row.textJa)}</li>)}
    </ol> : <p className="mp-empty">このテーマの記録はまだありません。</p>}
  </details>;
}

/** The market's position memory, themes with entries first. */
export function MarketPositionCard({ brief }: { brief: MarketBrief }) {
  const raw = brief.marketPosition as MarketPosition | undefined;
  if (!raw || !Array.isArray(raw.themes) || typeof raw.entryCount !== 'number') return <section
    className="mp-card card" aria-label="市場の現在位置" data-argus-contract="market-position-pending-v1">
    <div className="at-head"><b>MARKET POSITION</b><span>更新待ち</span></div>
    <p role="status">{raw && 'status' in raw && raw.status === 'UNAVAILABLE'
      ? '現在位置の読み込みを完了できませんでした。次の更新を待っています。'
      : '現在位置の記録はまだ届いていません。次の見立てが届くと表示します。'}</p>
  </section>;
  const position: MarketPosition = raw;
  const themes = [...position.themes].sort((a, b) => Number(b.entryCount > 0) - Number(a.entryCount > 0));
  const active = themes.filter(t => t.status === 'ACTIVE').length;
  return <section className="mp-card card" aria-label="市場の現在位置" data-argus-contract="market-position-v1"
    data-entry-count={position.entryCount}>
    <div className="at-head"><b>MARKET POSITION</b><span>{active > 0 ? `${themes.length}テーマ中 ${active}件に更新` : '更新待ち'}</span></div>
    {themes.map(theme => <ThemeRow key={theme.themeId} theme={theme} />)}
  </section>;
}

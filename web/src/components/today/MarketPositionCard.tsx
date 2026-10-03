import React from 'react';
import type { MarketBrief, MarketPosition, MarketPositionTheme } from '../../lib/marketBrief';
import './MarketPositionCard.css';

// 13.8 §3-1 (owner direction 2026-10-03): before the numbers, where the market
// stands — the themes investors are watching, the measured pricing, the last
// release reading and the next check. Entries come from the server memory;
// nothing here is a forecast.
const statusLabel: Record<string, string> = { ACTIVE: '動いている', QUIET: '最近の動きなし', EMPTY: '記録なし' };
const kindLabel: Record<string, string> = { NEWS: 'ニュース', RELEASE_REACTION: '発表の反応', PRICING: '織り込み' };
const jst = (iso?: string | null) => iso && Number.isFinite(Date.parse(iso))
  ? new Date(iso).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';

function ThemeRow({ theme }: { theme: MarketPositionTheme }) {
  const lead = theme.lastReaction?.textJa || theme.recent[0]?.textJa || '';
  return <details className="mp-theme" data-theme={theme.themeId} data-status={theme.status}>
    <summary>
      <span className={`mp-chip is-${theme.status.toLowerCase()}`}>{statusLabel[theme.status] ?? theme.status}</span>
      <span><b>{theme.labelJa}</b>
        {lead && <small>{lead}</small>}
        {theme.pricing?.ffImpliedRatePct != null && <small>政策金利の予想(FF先物) {theme.pricing.ffImpliedRatePct.toFixed(3)}%</small>}
        {theme.view?.fearJa && <small className="mp-fear">警戒: {theme.view.fearJa}</small>}
        {theme.nextEvent && <small>次: {theme.nextEvent.title} {jst(theme.nextEvent.eventTimeUtc)}</small>}
      </span>
    </summary>
    {theme.view && (theme.view.expectationJa || theme.view.fearJa || theme.view.triggerJa) && <dl className="mp-view" data-view-kind={theme.view.kind ?? ''}>
      {theme.view.expectationJa && <><dt>市場の期待</dt><dd>{theme.view.expectationJa}</dd></>}
      {theme.view.fearJa && <><dt>市場の警戒</dt><dd>{theme.view.fearJa}</dd></>}
      {theme.view.triggerJa && <><dt>読みが変わる引き金</dt><dd>{theme.view.triggerJa}</dd></>}
      <dd className="mp-view-note">ARGUSの整理(推論){theme.view.at ? `・${jst(theme.view.at)}` : ''}。根拠は下の記録です。</dd>
    </dl>}
    {theme.recent.length > 0 ? <ol className="mp-entries">
      {theme.recent.map(row => <li key={row.entryId} data-kind={row.kind} data-severity={row.severity}>
        <span>{jst(row.at)}</span><em>{kindLabel[row.kind] ?? row.kind}</em>{row.textJa}</li>)}
    </ol> : <p className="mp-empty">このテーマの記録はまだありません。</p>}
  </details>;
}

/** The market's position memory, themes with entries first. */
export function MarketPositionCard({ brief }: { brief: MarketBrief }) {
  const raw = brief.marketPosition as MarketPosition | undefined;
  if (!raw || !Array.isArray(raw.themes) || typeof raw.entryCount !== 'number') return null;
  const position: MarketPosition = raw;
  const themes = [...position.themes].sort((a, b) => Number(b.entryCount > 0) - Number(a.entryCount > 0));
  const active = themes.filter(t => t.status === 'ACTIVE').length;
  return <section className="mp-card card" aria-label="市場の現在位置" data-argus-contract="market-position-v1"
    data-entry-count={position.entryCount}>
    <div className="at-head"><b>市場の現在位置</b><span>{active > 0 ? `動いているテーマ ${active}` : '蓄積中'}</span></div>
    <p className="mp-note">投資家が今見ているテーマと、測った織り込み・直近の発表の読み・次の予定。重要ニュースと発表の反応から積み上げた記録で、予測ではありません。</p>
    {themes.map(theme => <ThemeRow key={theme.themeId} theme={theme} />)}
  </section>;
}

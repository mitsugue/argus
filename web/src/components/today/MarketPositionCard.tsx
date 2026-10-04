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
const kindLabel: Record<string, string> = { NEWS: 'ニュース', RELEASE_REACTION: '発表の反応', PRICING: '織り込み', AI_VIEW: '見立て' };
const jst = (iso?: string | null) => iso && Number.isFinite(Date.parse(iso))
  ? new Date(iso).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';

function ThemeRow({ theme }: { theme: MarketPositionTheme }) {
  const lead = theme.lastReaction?.textJa || theme.recent.find(row => row.kind !== 'AI_VIEW')?.textJa || '';
  const expectation = hasSubstantiveView(theme.view?.expectationJa) ? theme.view!.expectationJa : '';
  const fear = hasSubstantiveView(theme.view?.fearJa) ? theme.view!.fearJa : '';
  return <details className="mp-theme" data-theme={theme.themeId} data-status={theme.status}>
    <summary>
      <span className="mp-content"><span className="mp-heading"><b>{theme.labelJa}</b>
        <span className={`mp-chip is-${theme.status.toLowerCase()}`} title={statusDescription[theme.status]}>
          <i aria-hidden="true" />{statusLabel[theme.status] ?? '確認中'}</span></span>
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
      <dd className="mp-view-note">ARGUSの整理(推論){theme.view.at ? `・${jst(theme.view.at)}` : ''}。根拠は下の記録です。</dd>
    </dl>}
    <p className="mp-empty">{statusDescription[theme.status]}{theme.lastUpdatedAt ? ` · 最終記録 ${jst(theme.lastUpdatedAt)}` : ''}</p>
    {theme.recent.length > 0 ? <ol className="mp-entries">
      {theme.recent.map(row => <li key={row.entryId} data-kind={row.kind} data-severity={row.severity}>
        <span>{jst(row.at)}</span><em>{kindLabel[row.kind] ?? row.kind}</em>{marketWording(row.textJa)}</li>)}
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
    <div className="at-head"><b>市場の現在位置</b><span>{active > 0 ? `${themes.length}テーマ中 ${active}件に更新` : '更新待ち'}</span></div>
    {themes.map(theme => <ThemeRow key={theme.themeId} theme={theme} />)}
  </section>;
}

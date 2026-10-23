import type { DashboardReleaseReaction, EventNewsContext } from '../../lib/dashboardEventState';

/** Fixed facts first. Long, previously saved analysis remains in details. */
export function compactResultHeadline(text?: string | null): string {
  return (text || '公式結果を取得中').replace(/^消費者物価指数\s*/, '')
    .replace(/総合CPI\s*/, '総合 ')
    .replace(/（季節調整済み）/g, '').replace(/（季節調整なし）/g, '')
    .replace(/コア前月比/g, 'コア前月比');
}
const fields: [string, string, string][] = [
  ['ffImpliedRateMoveBp', '政策金利予想', 'bp'], ['usdJpyMovePct', 'ドル円', '%'],
  ['nikkeiFuturesMovePct', '日経先物', '%'], ['nasdaqFuturesMovePct', 'ナスダック先物', '%'],
  ['spFuturesMovePct', 'S&P先物', '%'], ['vixMovePct', 'VIX', '%'],
  ['us2yFuturesMovePct', '米2年債先物', '%'], ['us10yFuturesMovePct', '米10年債先物', '%'],
];
export function measuredReaction(rr?: DashboardReleaseReaction | null): string {
  if (rr?.basis !== 'PRE_RELEASE_BASELINE' || !rr.latestWindow) return '未取得';
  const entries = fields.flatMap(([key, label, unit]) => {
    const v = rr.moves?.[key];
    return typeof v === 'number' && Number.isFinite(v) ? [`${label} ${v >= 0 ? '+' : ''}${v.toFixed(unit === 'bp' ? 1 : 2)}${unit}`] : [];
  });
  return entries.length ? `${rr.latestWindow}・発表直前比 ${entries.join(' / ')}` : '未取得';
}
export function EventResultBrief({ headline, available, reaction, verdict, reading, next, newsContext }: {
  headline?: string | null; available: boolean; reaction?: DashboardReleaseReaction | null;
  verdict?: string; reading?: string; next?: string; newsContext?: EventNewsContext;
}) {
  const measured = measuredReaction(reaction);
  return <div className="ie-result-brief" data-argus-contract="event-result-brief-v1">
    <p><span className="ie-k">結果</span><strong>{available ? compactResultHeadline(headline) : '公式結果を取得中'}</strong></p>
    <p><span className="ie-k">予想比較</span>{newsContext?.comparisonJa || '未確認'}</p>
    {(newsContext?.articles || []).length > 0 && <div data-argus-contract="event-news-context-v1">
      {(newsContext?.articles || []).slice(0, 2).map(article => <p key={article.sourceRefSha256}>
        <span className="ie-k">報道</span>{(article.facts.length ? article.facts.slice(0, 2).join(' / ') : article.headline).slice(0, 180)}
        <small> · {article.sourceUrl ? <a href={article.sourceUrl} target="_blank" rel="noopener noreferrer">{article.source}</a> : article.source}{article.scope === 'PUBLIC_HEADLINE_ONLY' ? '（見出しのみ）' : ''}</small>
      </p>)}
      {newsContext?.storyStatus === 'ARTICLE_EVIDENCE_INCOMPLETE' && <p><span className="ie-k">不足</span>記事根拠が不足</p>}
    </div>}
    <details><summary>事前予想との照合</summary>{verdict || '未採点'}</details>
    <p><span className="ie-k">実測</span>{measured}</p>
    <p><span className="ie-k">判断</span>{reading && reading.length <= 80 ? reading : 'データ待ち'}</p>
    {next && next.length <= 80 && <p><span className="ie-k">次の確認</span>{next}</p>}
  </div>;
}

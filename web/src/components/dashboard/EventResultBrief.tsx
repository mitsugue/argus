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
  if (rr?.basis !== 'PRE_RELEASE_BASELINE' || !rr.latestWindow) return '比較可能な価格が未取得';
  const entries = fields.flatMap(([key, label, unit]) => {
    const v = rr.moves?.[key];
    return typeof v === 'number' && Number.isFinite(v) ? [`${label} ${v >= 0 ? '+' : ''}${v.toFixed(unit === 'bp' ? 1 : 2)}${unit}`] : [];
  });
  return entries.length ? `${rr.latestWindow}・発表直前比 ${entries.join(' / ')}` : '比較可能な価格が未取得';
}
export function EventResultBrief({ headline, available, reaction, verdict, reading, next, newsContext }: {
  headline?: string | null; available: boolean; reaction?: DashboardReleaseReaction | null;
  verdict?: string; reading?: string; next?: string; newsContext?: EventNewsContext;
}) {
  const measured = measuredReaction(reaction);
  return <div className="ie-result-brief" data-argus-contract="event-result-brief-v1">
    <p><span className="ie-k">結果</span><strong>{available ? compactResultHeadline(headline) : '公式結果を取得中'}</strong></p>
    <p><span className="ie-k">予想比較</span>{newsContext?.comparisonJa || '市場予想との数値比較は未確認'}</p>
    {(newsContext?.articles || []).length > 0 && <div data-argus-contract="event-news-context-v1">
      {(newsContext?.articles || []).slice(0, 2).map(article => <p key={article.sourceRefSha256}>
        <span className="ie-k">報道</span>{(article.facts.length ? article.facts.slice(0, 2).join(' / ') : article.headline).slice(0, 180)}
        <small> · {article.sourceUrl ? <a href={article.sourceUrl} target="_blank" rel="noopener noreferrer">{article.source}</a> : article.source}{article.scope === 'PUBLIC_HEADLINE_ONLY' ? '（見出しのみ）' : '（受領記事の分析）'}</small>
      </p>)}
      {newsContext?.storyStatus === 'ARTICLE_EVIDENCE_INCOMPLETE' && <p><span className="ie-k">不足</span>市場が結果をどう受け止めたか、説明する記事根拠が不足</p>}
      <small>報道の説明と、実測した価格反応・下落原因の実証は別です。</small>
    </div>}
    <details><summary>ARGUSの事前予想との照合</summary>{verdict || '未採点'}</details>
    <p><span className="ie-k">実測</span>{measured}{measured.includes('未取得') ? '' : '（比較できた市場のみ）'}</p>
    <p><span className="ie-k">判断</span>{reading && reading.length <= 80 ? reading : '株式・金利への方向は、比較できる反応がそろってから確認'}</p>
    {next && next.length <= 80 && <p><span className="ie-k">次の確認</span>{next}</p>}
  </div>;
}

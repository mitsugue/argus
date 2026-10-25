import React from 'react';
import { useOsintInvestigation, type OsintRequestError } from '../../hooks/useOsintInvestigation';
import { publishOsintDeep } from '../../lib/positionExposureShare';

// 2026-10-25 (owner): one stock is researched only when the owner presses
// 「調べる」 (about 50k tokens a run; one turn per stock and five a Tokyo day).
// The panel shows the conclusion, up to three sources and when it ran.

const ERROR_JA: Record<OsintRequestError, string> = {
  no_key: '接続キーが未設定です(設定 → AI利用料)。',
  bad_key: '接続キーを確認してください。',
  daily_limit: '今日の上限(5回)に達しました。',
  already_today: 'この銘柄は今日調査済みです。',
  ai_stopped: 'AIが停止中です。',
  failed: '受け付けられませんでした。',
};

// Headlines arrive with HTML entities from some feeds (&quot; and the like).
const ENTITY: Record<string, string> = { quot: '"', amp: '&', apos: "'", lt: '<', gt: '>', '#39': "'" };
const plain = (text: string) => text.replace(/&(quot|amp|apos|lt|gt|#39);/g, (_, key: string) => ENTITY[key]);

// A source the check could not tie to the stock is not shown as its material.
const RELATED = new Set(['direct_company', 'sector_theme', 'value_chain']);

const stamp = (iso?: string | null) => {
  if (!iso) return '';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  return at.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit' });
};

const day = (iso?: string | null) => {
  if (!iso) return '';
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? '' : at.toLocaleDateString('ja-JP',
    { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric' });
};

export const OsintDeepDive: React.FC<{ symbol: string; market: string; name?: string }>
  = ({ symbol, market, name }) => {
  const { inv, owner, loading, error, requestError, research, reload } = useOsintInvestigation(symbol, market, name);
  const running = !!owner?.running;
  const doneToday = !!owner?.requestedToday && !running;
  const verdict = inv?.catalystVerdict;
  const failed = owner?.complete === false;
  const related = inv ? inv.verifiedSources.filter((source) => RELATED.has(source.directness ?? ''))
    .sort((a, b) => Number(!!b.primaryEligible) - Number(!!a.primaryEligible)) : [];
  // 2026-10-26 (owner): when nothing was tied to the stock, show what the
  // search found rather than an empty verdict.
  const sources = (related.length ? related : inv?.searchFindings ?? []).slice(0, 3);
  const headline = failed ? '調べられませんでした'
    : verdict && verdict.verdict !== 'unknown' ? verdict.verdictJa
      : sources.length ? '見つかった材料' : '材料は見つかりませんでした';

  React.useEffect(() => {
    if (!inv) return;
    publishOsintDeep({
      symbol: inv.symbol, summaryJa: verdict?.ownerReadableJa ?? inv.ownerReadableSummaryJa ?? '',
      coverageJa: '', reliabilityJa: '', benchmarkJa: '', disagreementJa: [],
      verifiedTitlesJa: inv.verifiedSources.map((v) => v.titleJa).slice(0, 5), missingAreasJa: [],
    });
  }, [inv, verdict]);

  const label = running ? '調査中…' : inv ? 'もう一度調べる' : '調べる';
  return (
    <div className="uac-sec osint-deep">
      {inv && (
        <>
          <p className="osint-deep__verdict">
            <b>{headline}</b>
            {!failed && verdict?.primaryCauseJa && <span> · {plain(verdict.primaryCauseJa)}</span>}
          </p>
          {sources.length > 0 && (
            <ul className="osint-deep__sources">
              {sources.map((source) => (
                <li key={`${source.url ?? ''}${source.titleJa}`}>
                  {source.url
                    ? <a href={source.url} target="_blank" rel="noopener noreferrer">{plain(source.titleJa)}</a>
                    : plain(source.titleJa)}
                  <span className="osint-deep__meta">
                    {[source.sourceName, day(source.publishedAt)].filter(Boolean).join(' · ')}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="osint-deep__meta">{stamp(owner?.completedAt ?? inv.asOf)} 調査</p>
        </>
      )}
      {error && !inv && (
        <p className="osint-deep__meta">読み込めませんでした。<button type="button" className="asset-mini" onClick={reload}>再取得</button></p>
      )}
      <p className="osint-deep__actions">
        <button type="button" className="asset-mini" disabled={(loading && !owner) || running || doneToday}
                onClick={() => { void research(); }}>{label}</button>
        {doneToday && <span className="osint-deep__meta">今日は調査済み</span>}
        {!running && !doneToday && owner && <span className="osint-deep__meta">今日あと{owner.remainingToday}回</span>}
      </p>
      {requestError && <p className="osint-deep__meta" role="status">{ERROR_JA[requestError]}</p>}
    </div>
  );
};

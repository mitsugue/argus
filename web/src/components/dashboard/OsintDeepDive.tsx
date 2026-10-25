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

export const OsintDeepDive: React.FC<{ symbol: string; market: string; held?: boolean }>
  = ({ symbol, market }) => {
  const { inv, owner, loading, error, requestError, research, reload } = useOsintInvestigation(symbol, market);
  const running = !!owner?.running;
  const doneToday = !!owner?.requestedToday && !running;
  const verdict = inv?.catalystVerdict;
  const sources = inv ? [...inv.verifiedSources]
    .sort((a, b) => Number(!!b.primaryEligible) - Number(!!a.primaryEligible)).slice(0, 3) : [];

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
      <div className="uac-sec-t">OSINT DEEP DIVE</div>
      {inv && (
        <>
          <p className="osint-deep__verdict">
            <b>{verdict && verdict.verdict !== 'unknown' ? verdict.verdictJa : '材料は見つかりませんでした'}</b>
            {verdict?.primaryCauseJa && <span> · {verdict.primaryCauseJa}</span>}
          </p>
          {sources.length > 0 && (
            <ul className="osint-deep__sources">
              {sources.map((source) => (
                <li key={`${source.url ?? ''}${source.titleJa}`}>
                  {source.url
                    ? <a href={source.url} target="_blank" rel="noopener noreferrer">{source.titleJa}</a>
                    : source.titleJa}
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

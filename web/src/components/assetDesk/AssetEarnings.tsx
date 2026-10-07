import React from 'react';
import { useAnalystTargetState } from '../../hooks/useAnalystTargets';
import { earningsAmount, earningsDateLabel, earningsPct, type AssetEarnings } from '../../domain/assetEarnings';
import { outlookDay } from '../../domain/assetOutlook';

export const AssetEarningsDate: React.FC<{ market: string; row?: AssetEarnings; loading?: boolean; refreshFailed?: boolean }> =
  ({ market, row, loading, refreshFailed }) => !['JP', 'US'].includes(market) ? null :
    <span className="ad-earnings-date" title={row ? `${row.source} · ${outlookDay(row.fetchedAt)}取得。予定は取得元の推定。米国は米国東部の日付。` : undefined}>{!row && loading ? '次回決算 確認中' : earningsDateLabel(row)}
      {(row?.acquisitionStatus === 'FETCH_FAILED' || refreshFailed) && <small> · 更新未確認{row ? '・保存値' : ''}</small>}</span>;

export const AssetEarningsDetails: React.FC<{ market: string; symbol: string }> = ({ market, symbol }) => {
  const state = useAnalystTargetState();
  if (!['JP', 'US'].includes(market)) return null;
  const row = state.earnings?.[`${market}:${symbol.toUpperCase()}`];
  const p = row?.previous, e = row?.estimate, c = row?.company;
  const amount = (value: number, unit: string | null | undefined) => earningsAmount(value, unit ?? null);
  const companyAmount = (value: number) => `${(value / 100_000_000).toLocaleString('ja-JP', { maximumFractionDigits: 2 })}億円`;
  return <section className="ad-earnings-details" aria-label="決算の実績と次回の見通し">
    <h4>前回の決算</h4>
    {c ? <p>{outlookDay(c.disclosedDate)}発表 · {c.periodEnd ? `${c.periodEnd}までの` : ''}
      {c.periodType === 'FY' ? '通期' : `${c.periodType}累計`} · {c.consolidated ? '連結' : '単体'}。
      営業利益は{companyAmount(c.operatingProfit)}。
      {c.forecastOperatingProfit !== null && c.forecastOperatingProfit > 0 && <>通期営業利益計画に対する進捗は{(c.operatingProfit / c.forecastOperatingProfit * 100).toFixed(1)}%。</>}</p> :
      p ? <p>{p.periodEnd}期の1株利益（EPS）は{amount(p.epsActual, p.currency)}。
        {p.epsEstimate !== null && <>市場予想{amount(p.epsEstimate, p.currency)}に対し、
          {p.surprisePct !== null ? `${earningsPct(p.surprisePct)}の差` : '予想がゼロのため差率は計算できません'}。</>}
        <small> 決算期末の日付です。発表日は未取得。</small></p> :
        <p>前回決算の実績は未取得です。関連ニュースだけで決算の結果を補いません。</p>}
    <h4>次回の注目点</h4>
    <p>{e?.eps !== null && e?.eps !== undefined ? <>1株利益が市場予想{amount(e.eps, e.epsCurrency)}（{e.analysts}人）を上回るか。
      {e.revenue !== null && <>売上高が市場予想{amount(e.revenue, e.revenueCurrency)}（{e.revenueAnalysts}人{e.revenueGrowthPct !== null && <>・前年同期比{earningsPct(e.revenueGrowthPct)}</>}）に届くか。</>}
      {c?.forecastOperatingProfit !== null && c?.forecastOperatingProfit !== undefined && <>会社の通期利益予想を維持・変更するか。</>}</> :
      c?.forecastOperatingProfit !== null && c?.forecastOperatingProfit !== undefined ? <>通期計画に対する利益の進捗と、会社予想の変更を確認します。</> :
      '比較に使う会社予想・市場予想が未取得のため、銘柄固有の注目点はまだ示せません。'}</p>
    <h4>見通し</h4>
    {e?.eps !== null && e?.eps !== undefined ? <p>{e.periodEnd}期のEPS市場予想は{e.epsGrowthPct !== null ? `前年同期比${earningsPct(e.epsGrowthPct)}` : '前年同期比の情報なし'}。
      {e.epsLow !== null && e.epsHigh !== null && e.epsLow <= e.epsHigh && <>予想の幅は{amount(e.epsLow, e.epsCurrency)}〜{amount(e.epsHigh, e.epsCurrency)}。</>}
      {e.epsCurrency && e.eps30DaysAgo !== null && <>30日前の予想{amount(e.eps30DaysAgo, e.epsCurrency)}から
        {e.eps === e.eps30DaysAgo ? '変化なし' : e.eps > e.eps30DaysAgo ? '上方修正' : '下方修正'}。</>}
      <small> 市場の業績予想であり、ARGUSの株価予測ではありません。</small></p> :
      c?.forecastOperatingProfit !== null && c?.forecastOperatingProfit !== undefined ?
        <p>{c.fiscalYearEnd ?? '当年度'}の会社予想は営業利益{companyAmount(c.forecastOperatingProfit)}。次の四半期だけの利益予想は未取得です。</p> :
        <p>根拠のある業績予想は未取得です。見通しを推測で補いません。</p>}
    {row && <p className="ad-detail-note">{c?.source ?? row.source} · {outlookDay(c?.receivedAt ?? row.fetchedAt)}取得
      {c && (p || e) && <> / 市場予想 {row.source} · {outlookDay(row.fetchedAt)}取得</>}
      {(state.refreshFailed || row.acquisitionStatus === 'FETCH_FAILED') && ' · 更新未確認・保存値'}</p>}
  </section>;
};

import React from 'react';
import type { MarketBrief } from '../../lib/marketBrief';
import './FiscalEnvironmentDetails.css';

const cases = { baseline: '現状投影', growth_1: '成長戦略実現①', growth_2: '成長戦略実現②' };
const reasons: Record<string, string> = {
  'MARKET:JGB': '長期・超長期国債の複数年限で金利上昇が続いています。',
  'MARKET:FX': 'ドル円の上昇が続いています。原因の特定はしていません。',
  'FISCAL:POSITIVE_MECHANICAL_PRESSURE': '財政収支を含む計算で、債務GDP比を押し上げる方向です。',
  'FISCAL:GROWTH_RATE_GAP_NARROWED': '成長率と実効金利の差が縮小しました。',
  'FISCAL:GROWTH_RATE_GAP_REVERSED': '成長率と実効金利の差が逆転しました。',
  'FISCAL:PRIMARY_BALANCE_DETERIORATED': '基礎的財政収支が悪化しました。',
  'FISCAL:GROWTH_FORECAST_REVISED_DOWN': '成長見通しが下方修正されました。',
  'FISCAL:EFFECTIVE_RATE_FORECAST_REVISED_UP': '実効金利の見通しが上方修正されました。',
};
const object = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
const number = (v: unknown, digits = 2) => typeof v === 'number' && Number.isFinite(v)
  ? v.toLocaleString('ja-JP', { maximumFractionDigits: digits }) : '未確認';
const list = (v: unknown): string[] => Array.isArray(v) ? v.filter(x => typeof x === 'string').slice(0, 12) : [];
const stamp = (v: unknown) => typeof v === 'string' && Number.isFinite(Date.parse(v))
  ? new Date(v).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', year: 'numeric', month: 'numeric', day: 'numeric',
    ...(v.length > 10 ? { hour: '2-digit', minute: '2-digit' } as const : {}) }) : '未確認';
const sourceUrl = (v: unknown) => {
  if (typeof v !== 'string') return null;
  try { const u = new URL(v); return u.protocol === 'https:' && !u.username && !u.password ? v : null; }
  catch { return null; }
};

export function FiscalEnvironmentDetails({ brief }: { brief: MarketBrief }) {
  const doc = brief.unifiedContext?.fiscalEnvironment;
  if (!object(doc) || typeof doc.id !== 'string' || doc.actionAuthority !== false || !object(doc.cases)) return null;
  const rows = Object.entries(cases).flatMap(([key, label]) => object(doc.cases[key]) ? [{ key, label, row: doc.cases[key] }] : []);
  if (!rows.length) return null;
  const market = object(doc.market) ? doc.market : {};
  const series = object(market.series) ? market.series : {};
  const auctions = object(doc.auctions) && doc.auctions.actionAuthority === false ? doc.auctions : null;
  const auctionSeries = object(auctions?.series) ? auctions.series : {};
  return <details className="argus-editorial__evidence fiscal-evidence" data-fiscal-reference={doc.id}>
    <summary>日本の財政・金利の根拠</summary>
    {rows.map(({ key, label, row }) => {
      const fiscal = object(row.fiscal) ? row.fiscal : {};
      const definition = object(fiscal.definition) ? fiscal.definition : {};
      const values = object(fiscal.values) ? fiscal.values : {};
      const state = ({ WARNING: '警戒', WATCH: '注視', NO_TRIGGER: '現行条件の発動なし', UNKNOWN: 'データ待ち' } as Record<string,string>)[row.warningLevel] ?? '確認中';
      return <details key={key}><summary>{label} · {state}</summary>
        <p>{Number.isInteger(definition.year) ? definition.year : '未確認'}年度 · {({ FORECAST: '公式の将来見通し', ESTIMATE: '推計', ACTUAL: '実績' } as Record<string,string>)[definition.estimateType] ?? '区分未確認'} · {definition.governmentScope === 'CENTRAL_AND_LOCAL' ? '国・地方' : '政府範囲未確認'}</p>
        {fiscal.status === 'AVAILABLE' ? <dl>
          <dt>名目GDP成長率（前年比）</dt><dd>{number(values.growthPct)}%</dd>
          <dt>既存債務の実効金利</dt><dd>{number(values.effectiveRatePct)}%</dd>
          <dt>成長率 − 実効金利</dt><dd>{number(values.spreadPoints)}ポイント</dd>
          <dt>基礎的財政収支（黒字を正）</dt><dd>GDP比 {number(values.primarySurplusPct)}%</dd>
          <dt>前年度の公債等残高</dt><dd>GDP比 {number(values.priorDebtRatioPct)}%</dd>
          <dt>債務GDP比への計算上の圧力</dt><dd>{number(values.pressurePoints)}ポイント</dd>
        </dl> : <p>データ待ち</p>}
        {Array.isArray(fiscal.uncertainty?.pressurePointsRange) && <p>丸め幅：{number(fiscal.uncertainty.pressurePointsRange[0])}〜{number(fiscal.uncertainty.pressurePointsRange[1])}ポイント</p>}
        {list(row.currentReasons).map(reason => <p key={reason}>{reasons[reason] ?? '変化あり（未分類）'}</p>)}
        {row.previousWarningRetained && <p>前回の警戒を保持（データ不足）</p>}
        {fiscal.comparison?.status !== 'AVAILABLE' && <p>前回値なし</p>}
      </details>;
    })}
    <h3>市場金利</h3>
    <p>対象日 {typeof doc.expectedMarketSession === 'string' ? doc.expectedMarketSession : '不明'}</p>
    <dl>{[10, 20, 30, 40].map(tenor => {
      const row = object(series[`jp.market.jgb.${tenor}y`]) ? series[`jp.market.jgb.${tenor}y`] : {};
      return <React.Fragment key={tenor}><dt>{tenor}年国債</dt><dd>{row.status === 'AVAILABLE' ? `${number(row.latestValue, 3)}%` : 'データ待ち'}</dd></React.Fragment>;
    })}</dl>
    <details><summary>注視する条件と比較期間</summary>
      <p>4年限中2年限以上・{number(market.rule?.comparisonSessions, 0)}営業日前より上昇・直近{number(market.rule?.confirmationSessions, 0)}営業日連続上昇</p>
      <dl>{[10, 20, 30, 40].map(tenor => {
        const row = series[`jp.market.jgb.${tenor}y`];
        return object(row) && row.status === 'AVAILABLE' ? <React.Fragment key={tenor}>
          <dt>{tenor}年 · {stamp(row.comparisonFrom)} → {stamp(row.comparisonTo)}</dt>
          <dd>{number(row.change, 3)}ポイント · {row.adverse === true ? '該当' : '非該当'}</dd>
        </React.Fragment> : null;
      })}</dl>
    </details>
    {auctions && <section aria-label="日本国債の入札結果">
      <h3>国債入札への応募</h3>
      {auctions.acquisitionStatus !== 'AVAILABLE' && <p role="status">更新待ち・保存分</p>}
      {[10, 20, 30, 40].map(tenor => {
        const view = object(auctionSeries[String(tenor)]) ? auctionSeries[String(tenor)] : {};
        const result = object(view.latestResult) ? view.latestResult : null;
        return <details key={tenor}>
          <summary>{tenor}年国債 · {result ? `保存 ${typeof result.sessionDate === 'string' ? result.sessionDate.slice(5).replace('-', '/') : '日付未確認'} · 応募 ${number(result.bidToCover)}倍` : '結果未取得'}</summary>
          {view.status !== 'AVAILABLE' && <p>更新待ち{typeof view.expectedSessionDate === 'string' ? `（対象日 ${view.expectedSessionDate}）` : ''}</p>}
          {result && <>
            <p>保存した結果：{typeof result.sessionDate === 'string' ? result.sessionDate : '日付未確認'} · {result.auctionMethod === 'UNIFORM_YIELD' ? '単一利回りの入札' : '価格競争入札'}</p>
            <dl>
              <dt>応募額</dt><dd>{number(result.competitiveBidAmountJpy, 0)}円</dd>
              <dt>落札額</dt><dd>{number(result.competitiveAcceptedAmountJpy, 0)}円</dd>
              <dt>最高落札利回り</dt><dd>{number(result.highestAcceptedYieldPct, 3)}%</dd>
              {result.auctionMethod === 'PRICE_COMPETITIVE' ? <>
                <dt>平均落札利回り</dt><dd>{number(result.averageAcceptedYieldPct, 3)}%</dd>
                <dt>最高と平均の利回り差</dt><dd>{number(result.yieldTailBp)}bp</dd>
              </> : <><dt>平均利回り・利回り差</dt><dd>この方式では公表されません</dd></>}
            </dl>
            {sourceUrl(result.sourceUrl) && <p><a href={sourceUrl(result.sourceUrl)!} target="_blank" rel="noopener noreferrer">財務省の入札結果</a></p>}
          </>}
        </details>;
      })}
    </section>}
    {series['fx.usdjpy']?.status !== 'AVAILABLE' && <p>為替：未取得</p>}
    {(Array.isArray(doc.sources) ? doc.sources : []).filter(object).slice(0, 6).map((source, index) => <p key={index}>
      {sourceUrl(source.sourceUrl) && <a href={sourceUrl(source.sourceUrl)!} target="_blank" rel="noopener noreferrer">内閣府の原資料</a>}
      <small> 公表 {stamp(source.publishedDate)}</small>
    </p>)}
    {sourceUrl(series['jp.market.jgb.10y']?.sourceUrl) && <p><a href={sourceUrl(series['jp.market.jgb.10y'].sourceUrl)!} target="_blank" rel="noopener noreferrer">財務省の国債金利資料</a></p>}
  </details>;
}

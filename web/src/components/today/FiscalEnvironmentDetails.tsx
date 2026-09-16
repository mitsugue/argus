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
  return <details className="argus-editorial__evidence fiscal-evidence" data-fiscal-reference={doc.id}>
    <summary>日本の財政・金利の根拠</summary>
    <p>この説明に使った公式試算と市場金利です。財政の作用を点検する参考計算で、株価や財政危機の予測ではありません。</p>
    {rows.map(({ key, label, row }) => {
      const fiscal = object(row.fiscal) ? row.fiscal : {};
      const definition = object(fiscal.definition) ? fiscal.definition : {};
      const values = object(fiscal.values) ? fiscal.values : {};
      const state = ({ WARNING: '警戒', WATCH: '注視', NO_TRIGGER: '現行条件の発動なし', UNKNOWN: '判定に必要な情報を確認中' } as Record<string,string>)[row.warningLevel] ?? '確認中';
      return <details key={key}><summary>{label} · {state}</summary>
        <p>{Number.isInteger(definition.year) ? definition.year : '未確認'}年度 · {({ FORECAST: '公式の将来見通し', ESTIMATE: '推計', ACTUAL: '実績' } as Record<string,string>)[definition.estimateType] ?? '区分未確認'} · {definition.governmentScope === 'CENTRAL_AND_LOCAL' ? '国・地方' : '政府範囲未確認'}</p>
        {fiscal.status === 'AVAILABLE' ? <dl>
          <dt>名目GDP成長率（前年比）</dt><dd>{number(values.growthPct)}%</dd>
          <dt>既存債務の実効金利</dt><dd>{number(values.effectiveRatePct)}%</dd>
          <dt>成長率 − 実効金利</dt><dd>{number(values.spreadPoints)}ポイント</dd>
          <dt>基礎的財政収支（黒字を正）</dt><dd>GDP比 {number(values.primarySurplusPct)}%</dd>
          <dt>前年度の公債等残高</dt><dd>GDP比 {number(values.priorDebtRatioPct)}%</dd>
          <dt>債務GDP比への計算上の圧力</dt><dd>{number(values.pressurePoints)}ポイント</dd>
        </dl> : <p>入力の取得・定義確認が未完了のため、財政の計算は利用できません。</p>}
        {Array.isArray(fiscal.uncertainty?.pressurePointsRange) && <p>公表値の丸めを考慮した範囲：{number(fiscal.uncertainty.pressurePointsRange[0])}〜{number(fiscal.uncertainty.pressurePointsRange[1])}ポイント。ほかの資産・負債調整を含む実際の変化とは一致しない場合があります。</p>}
        {list(row.currentReasons).map(reason => <p key={reason}>{reasons[reason] ?? '追加確認が必要な変化を検出しています。'}</p>)}
        {row.previousWarningRetained && <p>比較に必要な情報が不足しているため、前回の警戒を保持しています。</p>}
        <p>{fiscal.comparison?.status === 'AVAILABLE' ? '比較できる前回の入力に対する変化を評価しています。' : '同じ定義で比較できる前回値は未確認です。'}</p>
        <p>国・地方の公債等残高を対象とし、一般政府の総債務・純債務とは別です。PBは復旧復興・GX・AI半導体支援の対象経費等を除く資料の定義に従います。その他の資産・負債調整は、この圧力計算に含めていません。</p>
      </details>;
    })}
    <h3>市場金利は別に確認しています</h3>
    <p>対象日 {typeof doc.expectedMarketSession === 'string' ? doc.expectedMarketSession : '未確認'}。市場金利の上昇が、既存債務全体の実効金利へ即時に同率で反映されるわけではありません。</p>
    <dl>{[10, 20, 30, 40].map(tenor => {
      const row = object(series[`jp.market.jgb.${tenor}y`]) ? series[`jp.market.jgb.${tenor}y`] : {};
      return <React.Fragment key={tenor}><dt>{tenor}年国債</dt><dd>{row.status === 'AVAILABLE' ? `${number(row.latestValue, 3)}%` : '更新・取得を確認中'}</dd></React.Fragment>;
    })}</dl>
    <details><summary>注視する条件と比較期間</summary>
      <p>4年限のうち2年限以上で、{number(market.rule?.comparisonSessions, 0)}観測営業日前からの上昇と、直近{number(market.rule?.confirmationSessions, 0)}営業日の連続上昇が、公表値の丸め幅を超えた場合に注視します。同じ国債市場の変化として1種類の材料に数えます。</p>
      <dl>{[10, 20, 30, 40].map(tenor => {
        const row = series[`jp.market.jgb.${tenor}y`];
        return object(row) && row.status === 'AVAILABLE' ? <React.Fragment key={tenor}>
          <dt>{tenor}年 · {stamp(row.comparisonFrom)} → {stamp(row.comparisonTo)}</dt>
          <dd>{number(row.change, 3)}ポイント · {row.adverse === true ? '注視条件に該当' : '連続上昇の条件には未該当'}</dd>
        </React.Fragment> : null;
      })}</dl>
      <small>計算ルール：{typeof market.rule?.version === 'string' ? market.rule.version : '未確認'}。丸め幅を超える変化の検出であり、危機や株価を予測できる閾値として検証していません。</small>
    </details>
    <p>警戒ルールと予測性能は未検証です。国債入札・借換構成は未接続。為替の判定は{series['fx.usdjpy']?.status === 'AVAILABLE' ? '取得済みの別系列を使用します。' : '未取得です。'}</p>
    <p>解除には、比較可能な財政入力と市場データがそろい、警戒条件の解消を確認する必要があります。取得障害だけで解除しません。</p>
    {(Array.isArray(doc.sources) ? doc.sources : []).filter(object).slice(0, 6).map((source, index) => <p key={index}>
      {sourceUrl(source.sourceUrl) && <a href={sourceUrl(source.sourceUrl)!} target="_blank" rel="noopener noreferrer">内閣府の原資料</a>}
      <small>公表日 {stamp(source.publishedDate)} · 公表時刻 {stamp(source.publishedAt)}<br/>取得 {stamp(source.knownAt)}（日本時間）</small>
    </p>)}
    {sourceUrl(series['jp.market.jgb.10y']?.sourceUrl) && <p><a href={sourceUrl(series['jp.market.jgb.10y'].sourceUrl)!} target="_blank" rel="noopener noreferrer">財務省の国債金利資料</a></p>}
  </details>;
}

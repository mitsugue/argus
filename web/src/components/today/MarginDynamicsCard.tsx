import React from 'react';

type Snapshot = { periodEnd: string; unit: 'UNITS'; longBalance: number; shortBalance: number; ratio: number };
type MarginDocument = {
  current: Snapshot; previous: Snapshot | null;
  change: { status: string; longContribution?: number; shortContribution?: number; ratioChange?: number; longBalanceChange?: number; shortBalanceChange?: number; isOneWeekChange?: boolean };
  lastSuccessfulAcquisitionAt: string; acquisitionStatus: string; sourceStatus: string;
  sourceRows: Array<{ periodEnd: string; seriesId: string; value: number; unit: string }>;
};
const object = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const snapshot = (v: unknown): v is Snapshot => object(v) && /^\d{4}-\d{2}-\d{2}$/.test(v.periodEnd)
  && v.unit === 'UNITS' && number(v.longBalance) && v.longBalance >= 0
  && number(v.shortBalance) && v.shortBalance > 0 && number(v.ratio);
export function validMarginDynamics(v: unknown): v is MarginDocument {
  return object(v) && v.schemaVersion === 'jp-market-dynamics-v1' && v.instrumentId === '1570'
    && v.balanceKind === 'WEEKLY_MARGIN' && v.actionAuthority === false
    && v.observedCoveringOrders === false && v.predictiveProbability === null
    && snapshot(v.current) && (v.previous === null || snapshot(v.previous))
    && typeof v.lastSuccessfulAcquisitionAt === 'string' && Number.isFinite(Date.parse(v.lastSuccessfulAcquisitionAt))
    && typeof v.acquisitionStatus === 'string' && typeof v.sourceStatus === 'string'
    && object(v.change) && typeof v.change.status === 'string'
    && (v.change.status !== 'AVAILABLE' || ['longContribution','shortContribution','ratioChange','longBalanceChange','shortBalanceChange'].every(k => number(v.change[k])))
    && Array.isArray(v.sourceRows) && v.sourceRows.length <= 60000
    && v.sourceRows.every((r: unknown) => object(r) && typeof r.periodEnd === 'string'
      && typeof r.seriesId === 'string' && number(r.value) && typeof r.unit === 'string');
}
const signed = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(4)}`;
const units = (v: number) => `${v.toLocaleString('ja-JP')}口`;

export function MarginDynamicsCard({ document, refreshFailed = false }: { document: unknown; refreshFailed?: boolean }) {
  if (!validMarginDynamics(document)) return <section className="card at-margin-dynamics" aria-label="日経レバの信用需給">
    <h3>日経レバの信用需給</h3><p>買残・売残と取得時刻がそろったデータをまだ確認できていません。</p>
  </section>;
  const { current, previous, change } = document;
  const failed = refreshFailed || !['AVAILABLE','PARTIAL'].includes(document.acquisitionStatus);
  const parts = document.sourceRows.filter(r => r.periodEnd === current.periodEnd && r.unit === 'UNITS');
  const component = (series: string) => { const r = parts.find(row => row.seriesId === series); return r ? units(r.value) : '未取得'; };
  return <section className="card at-margin-dynamics" aria-label="日経レバの信用需給">
    <h3>日経レバの信用需給</h3>
    <p>{current.periodEnd}時点 · 信用倍率 <strong>{current.ratio.toFixed(4)}倍</strong></p>
    <p>買残 {units(current.longBalance)} ／ 売残 {units(current.shortBalance)}</p>
    {change.status === 'AVAILABLE' && previous ? <>
      <p>{previous.periodEnd}からの{change.isOneWeekChange ? '前週差' : '期間差'}：{signed(change.ratioChange!)}倍</p>
      <p>買残の差 {change.longBalanceChange! >= 0 ? '+' : ''}{units(change.longBalanceChange!)} ／ 売残の差 {change.shortBalanceChange! >= 0 ? '+' : ''}{units(change.shortBalanceChange!)}</p>
      <p>買残の変化による寄与 {signed(change.longContribution!)}倍<br />売残の変化による寄与 {signed(change.shortContribution!)}倍</p>
    </> : <p>比較に必要な前回の残高が不足しています。</p>}
    <p>残高の変化です。実際の買い戻し注文を観測したものではなく、買いサインではありません。</p>
    {failed && <p role="status">更新に失敗しています。最後に取得できた残高を表示しています。</p>}
    {document.sourceStatus === 'PARTIAL' && <p role="status">取得は一部です。未取得ページまたは検証できない行があります。</p>}
    <details><summary>信用の内訳・出典と計算</summary>
      <p>制度信用：買残 {component('margin.standardized.long_balance')} ／ 売残 {component('margin.standardized.short_balance')}</p>
      <p>一般信用：買残 {component('margin.negotiable.long_balance')} ／ 売残 {component('margin.negotiable.short_balance')}</p>
      <p>日証金の貸借残とは別系列です。残高から個別建玉の返済期日を確定することはできません。</p>
      <p>倍率は買残÷売残。変化の寄与は、計算順序に偏らないよう両順序の平均で分解しています。</p>
      <p>最終取得：{new Date(document.lastSuccessfulAcquisitionAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST。公表時刻は未確認です。当時の改訂前データを証明する履歴ではありません。</p>
      <a href="https://www.jpx.co.jp/markets/other-data-services/j-quants-api/" target="_blank" rel="noreferrer">J-Quants データ提供元</a>
    </details>
  </section>;
}

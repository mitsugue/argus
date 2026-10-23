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
    <h3>MARGIN</h3><p>データ待ち</p>
  </section>;
  const { current, previous, change } = document;
  const failed = refreshFailed || !['AVAILABLE','PARTIAL'].includes(document.acquisitionStatus);
  const parts = document.sourceRows.filter(r => r.periodEnd === current.periodEnd && r.unit === 'UNITS');
  const component = (series: string) => { const r = parts.find(row => row.seriesId === series); return r ? units(r.value) : '未取得'; };
  // Daily balances from the 2026-09-25 application date (owner 2026-10-04):
  // the latest day and its change since the week end above, as a fact.
  const daily = (series: string, day: string) => document.sourceRows.find(r => r.periodEnd === day && r.seriesId === series && r.unit === 'UNITS');
  const latestDay = document.sourceRows.filter(r => r.seriesId === 'margin.long_balance' && r.unit === 'UNITS')
    .map(r => r.periodEnd).sort().at(-1);
  const latestLong = latestDay ? daily('margin.long_balance', latestDay) : undefined;
  const latestShort = latestDay ? daily('margin.short_balance', latestDay) : undefined;
  const showDaily = !!latestDay && latestDay > current.periodEnd && !!latestLong && !!latestShort && latestShort.value > 0;
  const diff = (v: number) => `${v >= 0 ? '+' : ''}${v.toLocaleString('ja-JP')}口`;
  return <section className="card at-margin-dynamics" aria-label="日経レバの信用需給">
    <h3>MARGIN</h3>
    <p className="at-context-lead">{change.status==='AVAILABLE'&&previous
      ? `買い残が${change.longBalanceChange!>0?'増え':change.longBalanceChange!<0?'減り':'横ばいで'}、売り残は${change.shortBalanceChange!>0?'増えています':change.shortBalanceChange!<0?'減っています':'横ばいです'}`
      : '前回値なし'}</p>
    <p className="at-context-date">{previous ? `${previous.periodEnd} → ` : ''}{current.periodEnd} · {change.isOneWeekChange?'前週との比較':'取得済み期間の比較'}</p>
    {change.status==='AVAILABLE'&&previous&&<div className="at-context-metrics">
      <article><span>信用買いの残高の変化</span><strong>{diff(change.longBalanceChange!)}</strong></article>
      <article><span>信用売りの残高の変化</span><strong>{diff(change.shortBalanceChange!)}</strong></article>
    </div>}
    {showDaily&&<div className="at-context-latest" data-margin-daily={latestDay}>
      <span>最新の日次残高 · {latestDay}</span><strong>{(latestLong!.value/latestShort!.value).toFixed(2)}<small>倍</small></strong>
      <p>買い残÷売り残</p></div>}
    {failed && <p role="status">更新失敗・最後に取得できた残高</p>}
    {document.sourceStatus === 'PARTIAL' && <p role="status">一部未取得</p>}
    <details><summary>信用の内訳</summary>
      <p>{current.periodEnd}時点 · 信用倍率 {current.ratio.toFixed(4)}倍</p>
      <p>買残 {units(current.longBalance)} ／ 売残 {units(current.shortBalance)}</p>
      {change.status === 'AVAILABLE' && previous ? <>
        <p>{previous.periodEnd}からの{change.isOneWeekChange ? '前週差' : '期間差'}：{signed(change.ratioChange!)}倍</p>
        <p>買残の変化による寄与 {signed(change.longContribution!)}倍<br />売残の変化による寄与 {signed(change.shortContribution!)}倍</p>
      </> : <p>前回値なし</p>}
      {showDaily && <p>最新(日次) {latestDay}：買残 {units(latestLong!.value)}（週末から{diff(latestLong!.value - current.longBalance)}）／ 売残 {units(latestShort!.value)}（週末から{diff(latestShort!.value - current.shortBalance)}）</p>}
      <p>制度信用：買残 {component('margin.standardized.long_balance')} ／ 売残 {component('margin.standardized.short_balance')}</p>
      <p>一般信用：買残 {component('margin.negotiable.long_balance')} ／ 売残 {component('margin.negotiable.short_balance')}</p>
      <p>最終取得 {new Date(document.lastSuccessfulAcquisitionAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}</p>
      <a href="https://www.jpx.co.jp/markets/other-data-services/j-quants-api/" target="_blank" rel="noreferrer">J-Quants データ提供元</a>
    </details>
  </section>;
}

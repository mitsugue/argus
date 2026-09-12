import React from 'react';

type Position = { longContracts: number; shortContracts: number; spreadContracts: number; netContracts: number };
type JpyPosition = {
  status: 'AVAILABLE' | 'STALE'; positionDate: string; previousPositionDate: string;
  current: Position; previous: Position; change: Position;
  receivedAt: string; publishedAt: string | null; positionAgeCalendarDays: number;
  sourceRef: string; acquisition?: { status?: string; persistenceStatus?: string };
};
const object = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
const position = (v: unknown): v is Position => object(v)
  && ['longContracts','shortContracts','spreadContracts','netContracts'].every(key => Number.isSafeInteger(v[key]))
  && v.netContracts === v.longContracts - v.shortContracts;
export function validJpyPosition(v: unknown): v is JpyPosition {
  return object(v) && v.schemaVersion === 'jp-market-jpy-position-v1'
    && ['AVAILABLE','STALE'].includes(v.status) && v.instrumentId === 'JPY'
    && v.contractCode === '097741' && v.contractSizeJpy === 12500000
    && v.reportType === 'LEGACY_FUTURES_ONLY' && v.traderCategory === 'NON_COMMERCIAL'
    && v.unit === 'CONTRACTS' && v.actionAuthority === false && v.observesCurrentLivePositions === false
    && position(v.current) && position(v.previous) && position(v.change)
    && ['longContracts','shortContracts','spreadContracts'].every(key => v.current[key] >= 0 && v.previous[key] >= 0)
    && ['longContracts','shortContracts','spreadContracts','netContracts'].every(key => v.current[key] - v.previous[key] === v.change[key])
    && /^\d{4}-\d{2}-\d{2}$/.test(v.positionDate) && /^\d{4}-\d{2}-\d{2}$/.test(v.previousPositionDate)
    && Number.isFinite(Date.parse(v.receivedAt)) && (v.publishedAt === null || Number.isFinite(Date.parse(v.publishedAt)))
    && Number.isSafeInteger(v.positionAgeCalendarDays) && v.positionAgeCalendarDays >= 0
    && v.sourceRef === 'https://www.cftc.gov/dea/futures/deacmesf.htm';
}
const count = (value: number) => value.toLocaleString('ja-JP');
const signed = (value: number) => `${value > 0 ? '+' : ''}${count(value)}`;
const time = (value: string) => new Date(value).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });

export function JpyPositionCard({ document }: { document: unknown }) {
  if (!validJpyPosition(document)) return <section className="card at-margin-dynamics" aria-label="円の投機ポジション">
    <h3>円の投機ポジション</h3><p>対象日・内訳・取得時刻がそろった公式データを確認中です。</p>
  </section>;
  const { current, change } = document;
  return <section className="card at-margin-dynamics" aria-label="円の投機ポジション">
    <h3>円の投機ポジション</h3>
    <p>{document.positionDate}時点 · 差引 <strong>{signed(current.netContracts)}枚</strong></p>
    <p>買い {count(current.longContracts)}枚 ／ 売り {count(current.shortContracts)}枚</p>
    <p>{document.previousPositionDate}からの差：買い {signed(change.longContracts)}枚、売り {signed(change.shortContracts)}枚</p>
    <p>週次公表のデータです。{document.positionAgeCalendarDays}日前の建玉で、現在の注文・建玉を直接観測したものではありません。</p>
    {document.acquisition?.status === 'FAILED' && <p role="status">更新に失敗したため、前回取得分を表示しています。</p>}
    {document.status === 'STALE' && <p role="status">対象日から時間が経過しています。新しい公式報告の確認待ちです。</p>}
    <details><summary>対象・内訳・出典を見る</summary>
      <p>CFTCの非商業取引者区分・円先物のみ。オプション合算の系列とは区別しています。</p>
      <p>スプレッド建玉 {count(current.spreadContracts)}枚（差 {signed(change.spreadContracts)}枚）。差引は買いから売りを引いた値です。</p>
      <p>買い越しになっても、売り建玉がなくなったという意味ではありません。</p>
      <p>取得 {time(document.receivedAt)} JST ／ 公表日時 {document.publishedAt ? `${time(document.publishedAt)} JST` : '未確認'}</p>
      <p>既存の市場台帳に記録します。{document.acquisition?.persistenceStatus !== 'VERIFIED' && '今回の保存・復旧の確認は未完了です。'}</p>
      <a href={document.sourceRef} target="_blank" rel="noreferrer">CFTCの公式報告を見る ↗</a>
      <p>このデータ単独では売買判断や予測確率を出しません。</p>
    </details>
  </section>;
}

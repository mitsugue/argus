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
  const { current, previous, change } = document;
  const switched = current.netContracts !== 0 && previous.netContracts !== 0 && Math.sign(current.netContracts) !== Math.sign(previous.netContracts);
  return <section className="card at-margin-dynamics" aria-label="円の投機ポジション">
    <h3>円の投機ポジション</h3>
    <p className="at-context-lead">{current.netContracts>0?'円買い':current.netContracts<0?'円売り':'買い・売りの残高は均衡'}{current.netContracts!==0&&(switched?'越しへ転換':`の偏りが${change.netContracts===0?'横ばい':Math.sign(change.netContracts)===Math.sign(current.netContracts)?'拡大':'縮小'}`)}</p>
    <p className="at-context-date">{document.positionDate}の週次報告 · {document.positionAgeCalendarDays}日前の建玉</p>
    <div className="at-context-metrics"><article><span>円買い − 円売り</span><strong>{signed(current.netContracts)}<small>枚</small></strong></article>
      <article><span>{document.previousPositionDate}からの差</span><strong>{signed(change.netContracts)}<small>枚</small></strong></article></div>
    <div className="at-context-use"><b>円相場が逆に動いた時の巻き戻しに注目</b>
      <p>{current.netContracts>0?'円買いに偏っています。円が下がると円買いの手じまいが、円安を強める可能性があります。':current.netContracts<0?'円売りに偏っています。円が上がると円売りの買い戻しが、円高を強める可能性があります。':'買い・売りの差はゼロです。偏りによる巻き戻しの方向は、この残高からは読み取れません。'}</p>
      <p>円高は輸出企業の利益に重し、円安は支えになりやすいため、実際のドル円の動きと合わせて見ます。</p>
      <small>週次の残高です。現在の注文・建玉を直接観測したものではありません。</small></div>
    {document.acquisition?.status === 'FAILED' && <p role="status">更新に失敗したため、前回取得分を表示しています。</p>}
    {document.status === 'STALE' && <p role="status">対象日から時間が経過しています。新しい公式報告の確認待ちです。</p>}
    <details><summary>対象・内訳・出典を見る</summary>
      <p>買い {count(current.longContracts)}枚 ／ 売り {count(current.shortContracts)}枚</p>
      <p>{document.previousPositionDate}からの差：買い {signed(change.longContracts)}枚、売り {signed(change.shortContracts)}枚</p>
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

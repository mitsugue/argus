import React from 'react';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';
import { SERIES_LABEL_JA, STATUS_JA } from '../../lib/seriesReconciliation';

const n = (v: number | null) => v === null ? '—' : v.toLocaleString('ja-JP');

export function SeriesReconciliationCard() {
  const state = useJapanMarketComparison(5);
  const doc = state.seriesReconciliation;
  return <section aria-label="分析に使う系列の欠けの照合">
    <div className="section-head"><span className="section-head__title">系列の欠けの照合</span></div>
    <div className="card cmd-alloc">
      {!doc ? <p className="cmd-alloc__note">{state.loading ? '読み込み中です。' : '照合結果はまだありません（次の収集で計算します）。'}</p> : <>
        <p className="cmd-alloc__note">期待される営業日（週次は週）と保存された日付を比べます。欠けや余分を見つけても自動では直しません。</p>
        <div style={{ overflowX: 'auto' }}><table className="at-reconciliation" style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}><thead><tr><th>系列</th><th>状態</th><th>期待</th><th>保存</th><th>欠け</th><th>余分</th><th>重複</th></tr></thead>
          <tbody>{Object.entries(doc.series).filter(([key]) => key in SERIES_LABEL_JA).map(([key, row]) => <tr key={key}>
            <td>{SERIES_LABEL_JA[key]}</td><td>{STATUS_JA[row.status]}</td><td>{n(row.expected)}</td><td>{n(row.actual)}</td>
            <td>{n(row.missing)}</td><td>{n(row.unexpected)}</td><td>{n(row.duplicated)}</td></tr>)}</tbody></table></div>
        {doc.measuredAt && <p className="cmd-alloc__note">計算 {new Date(doc.measuredAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST</p>}
      </>}
    </div>
  </section>;
}

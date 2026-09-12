import React from 'react';

const object = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const labels = { headlineCpiMoM: '総合・前月比', coreCpiMoM: 'コア・前月比',
  headlineCpiYoY: '総合・前年比', coreCpiYoY: 'コア・前年比' };
const stamp = (value: unknown) => typeof value === 'string' && /(Z|[+-]\d{2}:\d{2})$/.test(value)
  && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }) + ' JST' : '未確認';

export function cpiRows(result: unknown) {
  if (!object(result) || result.schemaVersion !== 'macro-cpi-result-v2' || !object(result.metrics)
    || !object(result.metricDefinitions) || !/^\d{4}-(0[1-9]|1[0-2])$/.test(result.metrics.referenceMonth)) return [];
  return Object.entries(labels).flatMap(([key, label]) => {
    const definition = result.metricDefinitions[key];
    const expectedAdjustment = key.endsWith('MoM') ? 'SA' : 'NSA';
    if (!object(definition) || definition.seasonalAdjustment !== expectedAdjustment
      || definition.unit !== 'PERCENT_CHANGE' || definition.referenceMonth !== result.metrics.referenceMonth) return [];
    return [{ key, label, adjustment: expectedAdjustment === 'SA' ? '季節調整済み' : '季節調整なし',
      value: finite(result.metrics[key]) ? result.metrics[key] : null,
      previous: object(result.previousMetrics) && finite(result.previousMetrics[key]) ? result.previousMetrics[key] : null }];
  });
}

export function MacroResultDetails({ result }: { result: unknown }) {
  const rows = cpiRows(result);
  if (!rows.length || !object(result)) return null;
  return <details className="ie-result-details">
    <summary>指標の定義・対象月・取得記録</summary>
    <p className="ie-data">対象月 {result.metrics.referenceMonth} · {result.referenceMatched === true ? 'イベント対象月と照合済み' : 'イベント対象月との照合は未確認'}</p>
    {rows.map(row => <p className="ie-line" key={row.key}>
      <span>{row.label}（{row.adjustment}）</span><br />
      <strong>{row.value === null ? '未取得' : `${row.value.toFixed(2)}%`}</strong>
      {row.previous !== null && <small> · 前回 {row.previous.toFixed(2)}%</small>}
    </p>)}
    <p className="ie-data">公式指数から計算した変化率です。公表文の丸め済み変化率とは区別します。</p>
    <p className="ie-data">公表日時 {stamp(result.releasedAt)}<br />取得日時 {stamp(result.receivedAt)}</p>
    <p className="ie-data">未取得の値や市場予想は補完していません。</p>
  </details>;
}

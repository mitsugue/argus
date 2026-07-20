import React, { useEffect, useMemo, useState } from 'react';
import { useMarketLedger } from '../../hooks/useMarketLedger';
import type { MarketLedgerHistoryPoint, MarketLedgerRow } from '../../types/marketLedger';
import './MarketLedgerPanel.css';

const SUMMARY_JA: Record<string, string> = { shortFuel: 'ショート燃料', creditBuyingPressure: '信用買い圧力',
  foreignFlow: '海外フロー', epsMomentum: 'EPSモメンタム', valuationBand: '評価帯', breadth: '市場の広がり' };
const VALUE_JA: Record<string, string> = { UNKNOWN: '未取得', HIGH: '高い', LOW: '低い', NORMAL: '中立',
  INFLOW: '買い越し', OUTFLOW: '売り越し', RISING: '上向き', FALLING: '低下', FLAT: '横ばい',
  HIGH_VALUATION_BAND: '高評価帯', OVERHEAT_CANDIDATE: '過熱候補', OVERSOLD_CANDIDATE: '売られすぎ候補', NEUTRAL: '中立' };
const STATUS_JA: Record<string, string> = { live: '更新済み', delayed: '遅延', missing: '未取得', revised: '改訂',
  licensed_redacted: '契約データ非公開', verified: '検証済み', not_verified: '未検証',
  not_present: 'リモート未反映', hash_mismatch: 'ハッシュ不一致' };
const DIR_JA: Record<string, string> = { up: '上向き', down: '下向き', flat: '横ばい' };
const ACQ_JA: Record<string, string> = { manual_csv: '手動CSV', jquants_or_manual: 'J-Quants契約またはCSV',
  nikkei_or_manual: '公式公開値またはCSV', official_or_manual: '公式公開値またはCSV', derived: '決定論的計算' };
const RANGE_DAYS: Record<string, number> = { '3M': 93, '1Y': 366, '3Y': 1096, '5Y': 1827, ALL: Infinity };

function fmt(value: number | null, unit: string) {
  if (value == null) return '—';
  if (unit === 'JPY') return `¥${Math.round(value).toLocaleString('ja-JP')}`;
  if (unit === 'percent') return `${value.toFixed(2)}%`;
  if (unit === 'ratio') return `${value.toFixed(2)}倍`;
  return value.toLocaleString('ja-JP');
}
function Spark({ points }: { points: MarketLedgerHistoryPoint[] }) {
  const values = points.map((p) => p.value).filter((v): v is number => v != null);
  if (values.length < 2) return <span className="ml-spark ml-spark--empty">—</span>;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 74},${22 - ((v - lo) / span) * 20}`).join(' ');
  return <svg className="ml-spark" viewBox="0 0 74 24" role="img" aria-label="推移"><polyline points={pts} /></svg>;
}
function rowMeaning(row: MarketLedgerRow) {
  if (row.status === 'licensed_redacted') return '契約データは公開APIへ返していません';
  if (row.seriesId === 'credit.short_balance' && row.thresholdDistance != null) {
    return `8,000億円との差 ${fmt(row.thresholdDistance, 'JPY')} · 閾値${row.thresholdSide === 'above' ? '上' : '下'} ${row.thresholdStreak ?? 0}週`;
  }
  if (row.seriesId.startsWith('flow.') && row.fourPeriodTotal != null) {
    const direction = (row.latestValue ?? 0) > 0 ? '買越' : (row.latestValue ?? 0) < 0 ? '売越' : '中立';
    return `4週累計 ${fmt(row.fourPeriodTotal, 'JPY')} · ${direction} ${row.consecutiveDirectionCount ?? 0}週`;
  }
  return ACQ_JA[row.acquisition] ?? row.acquisition;
}

export const MarketLedgerPanel: React.FC = () => {
  const { ledger, cost, loading, error } = useMarketLedger();
  const [range, setRange] = useState('1Y');
  const [series, setSeries] = useState('valuation.nikkei');
  const selected = ledger?.table.find((r) => r.seriesId === series) ?? ledger?.table[0];
  const history = useMemo(() => {
    const rows = selected?.history ?? [];
    if (range === 'ALL') return rows;
    const cutoff = Date.now() - RANGE_DAYS[range] * 86400000;
    return rows.filter((r) => Date.parse(r.periodEnd) >= cutoff);
  }, [selected, range]);
  const points = (ledger?.turningPoints ?? []).slice().reverse();
  useEffect(() => {
    if (!ledger) return;
    let target: string | null = null;
    try { target = sessionStorage.getItem('argus.scrollTo'); } catch { /* ignore */ }
    if (target !== 'market-ledger') return;
    const scroll = () => document.getElementById('market-ledger')?.scrollIntoView({ block: 'start' });
    const frame = requestAnimationFrame(scroll);
    // Re-anchor after asynchronous sections above the ledger settle.
    const settle = window.setTimeout(scroll, 250);
    const finish = window.setTimeout(() => {
      scroll();
      try { sessionStorage.removeItem('argus.scrollTo'); } catch { /* ignore */ }
    }, 900);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(settle);
      window.clearTimeout(finish);
    };
  }, [ledger]);
  return <section id="market-ledger" className="ml-panel regime-anchor" aria-label="Market Ledger">
    <div className="section-head"><span className="section-head__title">MARKET LEDGER</span>
      <span className="section-head__count">Phase 1 · {ledger?.observationCount ?? 0} observations</span></div>
    {error && <div className="card ml-empty">Market Ledger取得失敗。前回値があれば保持表示します。({error})</div>}
    {loading && !ledger && <div className="card ml-empty">市場履歴台帳を読み込み中…</div>}
    {ledger && <>
      <div className="card ml-ops-head">
        <div><b>SHO DAILY OPERATING SHEET</b><span>Phase 3 · deterministic · 16-point review</span></div>
        <ol>{ledger.phase3.sections.map((s) => <li key={s.order} className={s.status === 'available' ? 'is-live' : undefined}>
          <span>{s.order}</span>{s.name}
        </li>)}</ol>
      </div>
      <div className="card ml-daily"><div><b>DAILY CHANGES</b><span>前回更新から最大5件</span></div>
        {ledger.phase3.dailyChanges.length ? ledger.phase3.dailyChanges.map((change) => <div key={change.id}>
          <span>{change.status}</span><b>{change.summaryJa}</b><time>{change.effectiveFrom}</time>
        </div>) : <p>公表済み実データに新しい変化はありません。</p>}
      </div>
      <div className="ml-summary">
        {Object.entries(SUMMARY_JA).map(([key, label]) => <div className="card ml-summary__cell" key={key}>
          <span>{label}</span><b>{VALUE_JA[ledger.summary[key]] ?? '未取得'}</b></div>)}
      </div>
      <div className="card ml-valuation">
        <b>日経平均バリュエーション</b>
        <span>EPS前回差 {fmt(ledger.valuationSummary.epsPreviousChange, 'JPY')}</span>
        <span>EPS 5日変化 {fmt(ledger.valuationSummary.eps5Change, 'JPY')}</span>
        <span>EPS 20日変化 {fmt(ledger.valuationSummary.eps20Change, 'JPY')}</span>
        <span>18倍水準 {fmt(ledger.valuationSummary.per18Level, 'JPY')}</span>
        <span>21倍水準 {fmt(ledger.valuationSummary.per21Level, 'JPY')}</span>
        <span>21倍ピーク差 {fmt(ledger.valuationSummary.per21ChangeFromPeak, 'JPY')}</span>
        <small>{ledger.valuationSummary.labelJa}</small>
      </div>
      <div className="card ml-table-wrap"><table className="ml-table"><thead><tr>
        <th>項目</th><th>最新値</th><th>前回差</th><th>4週方向</th><th>過去順位</th><th>更新日</th><th>状態</th><th>推移</th>
      </tr></thead><tbody>{ledger.table.map((row) => <tr key={row.seriesId} title={rowMeaning(row)}>
        <td><b>{row.labelJa}</b><small>{rowMeaning(row)}</small></td><td>{fmt(row.latestValue, row.unit)}</td>
        <td>{fmt(row.previousChange, row.unit)}</td><td>{row.fourPeriodDirection ? DIR_JA[row.fourPeriodDirection] : '—'}</td>
        <td>{row.historicalPercentile == null ? '—' : `${row.historicalPercentile.toFixed(0)}%ile`}</td>
        <td>{row.periodEnd ?? '—'}</td><td>{STATUS_JA[row.status] ?? '確認中'}</td><td><Spark points={row.history.slice(-25)} /></td>
      </tr>)}</tbody></table></div>
      <div className="card ml-history" id="market-ledger-history">
        <div className="ml-controls"><label>履歴系列 <select value={series} onChange={(e) => setSeries(e.target.value)}>
          {ledger.table.filter((r) => r.history.length).map((r) => <option key={r.seriesId} value={r.seriesId}>{r.labelJa}</option>)}
        </select></label><div>{Object.keys(RANGE_DAYS).map((r) => <button type="button" key={r} className={range === r ? 'active' : ''} onClick={() => setRange(r)}>{r}</button>)}</div></div>
        <div className="ml-history__plot"><Spark points={history} /><span>{selected?.labelJa ?? '系列未取得'} · 単位 {selected?.unit ?? '—'} · {history.length}点</span></div>
        <p>単位の異なる系列は同一軸に重ねません。公表時刻より前の値は判断へ使用しません。</p>
      </div>
      <p className="ml-flow-caveat">{ledger.flowCaveatJa}</p>
      <div className="card ml-timeline" id="market-ledger-turning-points"><h3>TURNING POINT TIMELINE</h3>
        {points.length ? points.slice(0, 30).map((p) => <div className="ml-timeline__row" key={p.id}>
          <time>{p.effectiveFrom}</time><b>{p.facts.join(' / ')}</b><span>{p.detectionMode === 'live' ? 'ライブ検出' : '事後検出'}</span>
          <small>{p.classification === 'sho_heuristic' ? 'SHO経験則・単独売買判断には使用しない' : '複合判断の確認材料'} · その後: 未評価</small>
        </div>) : <p className="ml-empty">入力データ不足のため転換点はまだありません。</p>}
      </div>
      <div className="ml-phase3-grid">
        <div className="card ml-desk"><h3>ANOMALY DESK</h3>
          {ledger.phase3.anomalyDesk.length ? ledger.phase3.anomalyDesk.map((row) => <div key={row.id}>
            <b>{row.facts.join(' / ')}</b><span>想定: {row.expectedRelationship}</span>
            <span>観測: {row.observedRelationship}</span><small>原因未確認 · confidence {row.confidence}</small>
          </div>) : <p>確認できた関係崩れはありません。欠損値から原因を推定しません。</p>}
        </div>
        <div className="card ml-desk"><h3>WHAT CHANGES THE VIEW</h3>
          {ledger.phase3.decisionChangeConditions.map((row) => <div key={row.type}><b>{row.type}</b><span>{row.conditionJa}</span></div>)}
        </div>
      </div>
      <div className="card ml-rules"><h3>SHO RULE CARDS</h3><div>
        {ledger.heuristics.map((rule) => <article key={rule.ruleId}><b>{rule.ruleName}</b>
          <span>{rule.classification} · n={rule.sampleSize}</span><small>{rule.outcomeSummary} · {rule.methodVersion}</small>
        </article>)}
      </div><p>walk-forward · future leakageなし · n&lt;{ledger.backtestPolicy.minimumValidatedSamples}はvalidatedにしません。</p></div>
      <details className="card ml-sources"><summary>SOURCE OF TRUTH MATRIX</summary><div className="ml-table-wrap"><table className="ml-table"><thead><tr>
        <th>データ</th><th>Primary</th><th>Fallback</th><th>頻度</th><th>遅延</th><th>License</th><th>現在</th>
      </tr></thead><tbody>{ledger.sourceOfTruthMatrix.map((row) => <tr key={row.dataId}>
        <td>{row.dataId}</td><td>{row.primary}</td><td>{row.fallback}</td><td>{row.frequency}</td>
        <td>{row.delay}</td><td>{row.license}</td><td>{row.currentStatus}</td>
      </tr>)}</tbody></table></div></details>
    </>}
    <div className="card ml-cost" id="cost-policy"><h3>COST POLICY</h3>
      {cost ? <><div className="ml-cost__mode"><b>{cost.mode.replace('_', ' ')}</b><span>{cost.messageJa}</span></div>
        <div className="ml-cost__grid"><span>OpenAI 今日 <b>{cost.todayRuns.openai}</b></span><span>Gemini 今日 <b>{cost.todayRuns.gemini}</b></span>
          <span>Anthropic 今日 <b>{cost.todayRuns.anthropic}</b></span><span>今日推定 <b>${cost.todayEstimatedCostUsd.toFixed(4)}</b></span>
          <span>今月推定 <b>${cost.monthEstimatedCostUsd.toFixed(4)}</b></span><span>自動AI <b>{cost.automaticAiEnabled ? '有効' : '停止'}</b></span>
          <span>Event opt-in <b>{cost.eventOptIn ? '有効' : '無効'}</b></span><span>最終理由 <b>{cost.lastExecutionReason ?? '実行なし'}</b></span></div>
        <p>次に許可: {cost.nextAllowedAiExecution}</p></> : <p className="ml-empty">Cost Policyを確認中…</p>}
    </div>
    {ledger && <div className="card ml-quality"><b>DATA QUALITY</b><span>Remote read-back: {STATUS_JA[ledger.remoteReadBack.verificationStatus] ?? ledger.remoteReadBack.verificationStatus}</span>
      <span>最終検証: {ledger.remoteReadBack.lastVerifiedReadBackAt ?? '未検証'}</span><small>{ledger.noteJa}</small></div>}
  </section>;
};

export const MarketLedgerChanges: React.FC<{ onOpen: () => void }> = ({ onOpen }) => {
  const { ledger } = useMarketLedger();
  const rows = (ledger?.turningPoints ?? []).slice(-3).reverse();
  if (!rows.length) return null;
  return <section className="card ml-today"><div><b>Market Ledger changes</b><span>最大3件</span></div>
    {rows.map((p) => <button type="button" key={p.id} onClick={onOpen}><span>{p.effectiveFrom}</span>{p.facts[0]} ↗</button>)}</section>;
};

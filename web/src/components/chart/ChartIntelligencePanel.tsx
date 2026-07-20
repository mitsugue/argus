import React, { useMemo, useState } from 'react';
import { useChartIntelligence } from '../../hooks/useChartIntelligence';
import type { ChartBar, ChartIntelligencePayload } from '../../types/chartIntelligence';
import { useMarketLedger } from '../../hooks/useMarketLedger';
import './ChartIntelligencePanel.css';

const RANGE_COUNT: Record<string, number> = { '3M': 66, '6M': 132, '1Y': 264, '3Y': 792, '5Y': 1320, ALL: Infinity };
const RULE_JA: Record<string, string> = {
  TREND_STRUCTURE_BREAK: 'トレンド構造の崩れ', TREND_STRUCTURE_RECLAIM: 'トレンド構造の回復',
  RSI_DIVERGENCE: 'RSIダイバージェンス', RESISTANCE_CLUSTER_REJECTION: '抵抗帯クラスターで反落',
  RELATIVE_STRENGTH_TURN: '相対強弱の転換',
  EXTREME_DEVIATION: '極端な下方乖離', GOOD_NEWS_BAD_REACTION: '好材料に対する弱い反応',
  BAD_NEWS_RESILIENT_REACTION: '悪材料に対する底堅い反応', RELATIONSHIP_BREAK: '通常関係との不一致',
};
const STATUS_JA: Record<string, string> = { candidate: '候補', confirmed: '確認済み', invalidated: '無効化',
  active: '有効', broken: '下抜け', reclaimed: '回復', unconfirmed: '未確認',
  improving: '改善中', deteriorating: '悪化中', mixed: '方向混在', missing: '未取得',
  live: '更新済み', stale: '価格が古い', insufficient_data: 'データ不足',
  verified: '検証済み', not_verified: '未検証', not_present: 'リモート未反映', hash_mismatch: '不一致' };
const MISSING_JA: Record<string, string> = { stale_price: '価格履歴が古いため確認判定を停止',
  ohlcv_unavailable: 'OHLCV未取得', high_low_missing: '高値・安値の一部未取得',
  open_missing_close_used_for_display: '始値未取得（表示上は終値を使用）',
  duplicate_date_latest_kept: '同日重複を検出し最新行を採用', missing_date_or_close: '日付または終値が欠損' };
const RS_JA: Record<string, string> = { nikkei_sp500: 'NS倍率（日経÷S&P 500）', nikkei_usdjpy: '日経÷USDJPY',
  topix_nikkei: 'TOPIX÷日経', semiconductor_topix: '半導体÷TOPIX', growth_topix: 'グロース÷TOPIX',
  dollar_nikkei: 'ドル建て日経平均' };

function linePath(bars: ChartBar[], getter: (bar: ChartBar) => number | null,
                  x: (i: number) => number, y: (v: number) => number) {
  let started = false;
  return bars.map((bar, index) => {
    const value = getter(bar);
    if (value == null) { started = false; return ''; }
    const cmd = started ? 'L' : 'M'; started = true;
    return `${cmd}${x(index).toFixed(1)},${y(value).toFixed(1)}`;
  }).join(' ');
}

function valuationAt(history: Array<{ date: string; availableFrom: string; value: number }>, date: string) {
  const available = history.filter((point) => (point.availableFrom || point.date) <= date)
    .sort((a, b) => (a.availableFrom || a.date).localeCompare(b.availableFrom || b.date));
  return available.at(-1)?.value ?? null;
}

const PriceChart: React.FC<{ payload: ChartIntelligencePayload; range: string;
  showBB: boolean; showCloud: boolean; showLongMA: boolean }> = ({ payload, range, showBB, showCloud, showLongMA }) => {
  const all = payload.indicators.bars;
  const bars = all.slice(-(RANGE_COUNT[range] ?? 264));
  if (!bars.length) return <div className="ci-empty">価格履歴は未取得です。候補判定を停止しています。</div>;
  const zoneValues = payload.zones.flatMap((z) => [z.lower, z.upper]);
  const valuation = payload.valuationLevels.flatMap((level) => bars
    .map((bar) => valuationAt(level.history, bar.date)).filter((value): value is number => value != null));
  const values = bars.flatMap((b) => [b.high, b.low]).concat(zoneValues, valuation).filter(Number.isFinite);
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const x = (i: number) => 38 + (i / Math.max(1, bars.length - 1)) * 920;
  const y = (v: number) => 25 + (hi - v) / span * 285;
  const maxVol = Math.max(...bars.map((b) => b.volume ?? 0), 1);
  const candleWidth = Math.max(0.8, Math.min(6, 740 / bars.length));
  return <svg className="ci-chart" viewBox="0 0 1000 430" role="img" aria-label={`${payload.symbol} ローソク足チャート`}>
    <rect x="0" y="0" width="1000" height="430" className="ci-chart__bg" />
    {[0, 0.25, 0.5, 0.75, 1].map((p) => <g key={p}><line x1="38" x2="958" y1={25 + p * 285} y2={25 + p * 285} className="ci-grid" />
      <text x="963" y={29 + p * 285}>{(hi - span * p).toFixed(1)}</text></g>)}
    {payload.zones.filter((z) => z.status !== 'unconfirmed').slice(-10).map((z) => <rect key={z.id}
      x="38" width="920" y={y(z.upper)} height={Math.max(2, y(z.lower) - y(z.upper))}
      className={`ci-zone ci-zone--${z.status}`}><title>{`支持抵抗 ${z.lower.toFixed(2)}–${z.upper.toFixed(2)} · ${STATUS_JA[z.status]}`}</title></rect>)}
    {payload.valuationLevels.map((level) => <g key={level.multiple}>
      <path d={linePath(bars, (bar) => valuationAt(level.history, bar.date), x, y)} className="ci-line ci-per" />
      <text x="42" y={y(level.value) - 2} className="ci-per-label">PER{level.multiple} {level.labelJa}</text></g>)}
    {bars.map((bar, index) => { const cx = x(index); const up = bar.close >= bar.open; return <g key={bar.date}>
      <line x1={cx} x2={cx} y1={y(bar.high)} y2={y(bar.low)} className={up ? 'ci-up' : 'ci-down'} />
      <rect x={cx - candleWidth / 2} width={candleWidth} y={y(Math.max(bar.open, bar.close))}
        height={Math.max(1, Math.abs(y(bar.open) - y(bar.close)))} className={up ? 'ci-candle ci-up' : 'ci-candle ci-down'} />
      <rect x={cx - candleWidth / 2} width={candleWidth} y={414 - ((bar.volume ?? 0) / maxVol) * 72}
        height={((bar.volume ?? 0) / maxVol) * 72} className="ci-volume" />
    </g>; })}
    {(['5', '25', '75'] as const).map((w) => <path key={w} d={linePath(bars, (b) => b.ma[w], x, y)} className={`ci-line ci-ma${w}`} />)}
    {showLongMA && (['100', '200'] as const).map((w) => <path key={w} d={linePath(bars, (b) => b.ma[w], x, y)} className={`ci-line ci-ma${w}`} />)}
    {showBB && <><path d={linePath(bars, (b) => b.bollinger?.upper2 ?? null, x, y)} className="ci-line ci-bb" />
      <path d={linePath(bars, (b) => b.bollinger?.lower2 ?? null, x, y)} className="ci-line ci-bb" /></>}
    {showCloud && <><path d={linePath(bars, (b) => b.ichimoku.spanA, x, y)} className="ci-line ci-cloud" />
      <path d={linePath(bars, (b) => b.ichimoku.spanB, x, y)} className="ci-line ci-cloud" /></>}
    {payload.turningPoints.slice(-20).map((point) => { const idx = bars.findIndex((b) => b.date === point.effectiveFrom); if (idx < 0) return null;
      return <g key={point.id}><circle cx={x(idx)} cy={y(bars[idx].high) - 8} r="4" className={`ci-marker ci-marker--${point.status}`}>
        <title>{`${RULE_JA[point.ruleId] ?? point.ruleId}: ${point.facts.join(' / ')}`}</title></circle></g>; })}
    {payload.ledgerTurningPoints?.slice(-20).map((point) => { const idx = bars.findIndex((b) => b.date >= point.effectiveFrom); if (idx < 0) return null;
      return <g key={`ledger-${point.id}`}><circle cx={x(idx)} cy={y(bars[idx].low) + 8} r="4" className="ci-marker ci-marker--ledger">
        <title>{`Market Ledger: ${point.facts.join(' / ')}`}</title></circle></g>; })}
    {payload.eventMarkers?.slice(-30).map((event) => { const idx = bars.findIndex((b) => b.date >= event.date); if (idx < 0) return null;
      return <g key={`${event.id}-${event.date}`}><line x1={x(idx)} x2={x(idx)} y1="25" y2="310" className="ci-event-line" />
        <title>{event.labelJa}</title></g>; })}
    <text x="38" y="330">出来高</text><text x="38" y="427">{bars[0]?.date}</text><text x="895" y="427">{bars.at(-1)?.date}</text>
  </svg>;
};

const RelativePanel: React.FC<{ payload: ChartIntelligencePayload }> = ({ payload }) => {
  const rows = Object.entries(payload.relativeStrength ?? {});
  if (!rows.length) return null;
  return <details className="card ci-details" open><summary>RELATIVE STRENGTH / ROTATION MAP</summary>
    <div className="ci-rs-grid">{rows.map(([key, row]) => <div key={key} className="ci-rs-row">
      <b>{RS_JA[key] ?? key}</b><span>5日 {row.change5Pct == null ? '—' : `${row.change5Pct.toFixed(2)}%`}</span>
      <span>20日 {row.change20Pct == null ? '—' : `${row.change20Pct.toFixed(2)}%`}</span>
      <span>{row.directionTurn ? STATUS_JA[row.directionTurn] ?? row.directionTurn : '転換未確認'}</span>
      <small>{row.classification === 'sho_heuristic' ? 'SHO参考分類・単独判断には使用しない' : `${row.historicalPercentile ?? '—'}%ile`}</small>
    </div>)}</div>
    <div className="ci-rotation">{(payload.rotationMap ?? []).map((row) => <div key={row.label}>
      <b>{row.label}</b><span>5日 {row.relative5Pct == null ? '—' : `${row.relative5Pct.toFixed(1)}%`}</span>
      <span>20日 {row.relative20Pct == null ? '—' : `${row.relative20Pct.toFixed(1)}%`}</span>
      <em>{STATUS_JA[row.state]}</em></div>)}</div>
    <p className="ci-note">相対価格から資金循環候補を示します。「機関が買った／クジラが売った」とは断定しません。</p>
  </details>;
};

export const ChartIntelligencePanel: React.FC<{ scope: 'market' | 'asset'; symbol?: string; market?: string }> =
({ scope, symbol, market }) => {
  const [range, setRange] = useState('1Y');
  const [timeframe, setTimeframe] = useState<'daily' | 'weekly'>('daily');
  const [showBB, setShowBB] = useState(false), [showCloud, setShowCloud] = useState(false);
  const [showLongMA, setShowLongMA] = useState(false);
  const { data, loading, error } = useChartIntelligence({ scope, symbol, market, timeframe, enabled: true });
  return <section id={scope === 'market' ? 'chart-intelligence' : undefined} className="ci-panel">
    <div className="section-head"><span className="section-head__title">CHART INTELLIGENCE</span>
      <span className="section-head__count">deterministic · AI API 0</span></div>
    {loading && !data && <div className="card ci-empty">日足キャッシュを確認中…</div>}
    {error && <div className="card ci-empty">取得失敗。前回値があれば保持します。({error})</div>}
    {data && <>
      <div className="card ci-toolbar"><div>{Object.keys(RANGE_COUNT).map((item) => <button type="button" key={item}
        className={range === item ? 'active' : ''} onClick={() => setRange(item)}>{item}</button>)}</div>
        <div><button type="button" className={timeframe === 'daily' ? 'active' : ''} onClick={() => setTimeframe('daily')}>日足</button>
          <button type="button" className={timeframe === 'weekly' ? 'active' : ''} onClick={() => setTimeframe('weekly')}>週足</button></div>
        <label><input type="checkbox" checked={showBB} onChange={(e) => setShowBB(e.target.checked)} /> Bollinger</label>
        <label><input type="checkbox" checked={showCloud} onChange={(e) => setShowCloud(e.target.checked)} /> 一目</label>
        <label><input type="checkbox" checked={showLongMA} onChange={(e) => setShowLongMA(e.target.checked)} /> 100/200日線</label>
      </div>
      <div className="card ci-chart-wrap"><div className="ci-chart-head"><b>{data.displayNameJa ?? data.symbol}</b><span>{data.periodEnd ?? '未取得'}</span></div>
        <PriceChart payload={data} range={range} showBB={showBB} showCloud={showCloud} showLongMA={showLongMA} />
        {data.proxyDisclosureJa && <p className="ci-note">{data.proxyDisclosureJa}</p>}</div>
      {scope === 'market' && <RelativePanel payload={data} />}
      <div className="ci-summary-grid">
        <div className="card"><h3>最新転換点</h3>{data.turningPoints.length ? data.turningPoints.slice(-5).reverse().map((p) => <p key={p.id}>
          <b>{RULE_JA[p.ruleId] ?? 'テクニカル変化'}</b><span>{STATUS_JA[p.status]} · {p.detectionMode === 'live' ? 'ライブ検出' : '事後検出'}</span><small>{p.facts.join(' / ')}</small></p>)
          : <p className="ci-empty">データ不足または転換点未検出</p>}</div>
        <div className="card"><h3>テクニカル批評</h3>{data.critique.map((line) => <p key={line.label}><b>{line.label}</b><span>{line.text}</span></p>)}</div>
      </div>
      <details className="card ci-details"><summary>指標・反応異常・条件付きシナリオ</summary>
        <div className="ci-indicators">{(() => { const last = data.indicators.bars.at(-1); return last ? <>
          <span>RSI14 <b>{last.rsi14?.toFixed(1) ?? '—'}</b></span><span>MACD <b>{last.macd?.histogram.toFixed(2) ?? '—'}</b></span>
          <span>ATR14 <b>{last.atr14?.toFixed(2) ?? '—'}</b></span><span>出来高比 <b>{last.volumeRatio20?.toFixed(2) ?? '—'}</b></span></> : null; })()}</div>
        {[...data.reactionAnomalies, ...data.relationshipBreaks].map((x) => <p key={x.id}><b>{RULE_JA[x.ruleId] ?? '反応異常'}</b>
          <span>{x.facts.join(' / ')}</span></p>)}
        <div className="ci-scenarios">{data.scenarios.map((s) => <p key={s.label}><b>{s.label}</b><span>{s.text}</span></p>)}</div>
      </details>
      <div className="card ci-quality"><b>DATA QUALITY</b><span>状態: {STATUS_JA[data.status] ?? '確認中'}</span>
        <span>計算版: {data.methodVersion}</span><span>read-back: {STATUS_JA[data.persistence.verificationStatus] ?? '確認中'}</span>
        <small>{data.missingReasons.length ? `不足: ${data.missingReasons.map((x) => MISSING_JA[x] ?? '未確認事項あり').join(' / ')}` : 'OHLCV入力を検証済み'}</small>
        <small>{data.noteJa}</small></div>
    </>}
  </section>;
};

export const MarketIntelligenceChanges: React.FC<{ onOpen: () => void }> = ({ onOpen }) => {
  const { data } = useChartIntelligence({ scope: 'market', timeframe: 'daily', enabled: true });
  const { ledger } = useMarketLedger();
  const rows = useMemo(() => {
    const technical = (data?.turningPoints ?? []).filter((x) => x.status === 'confirmed' && x.ruleId === 'TREND_STRUCTURE_BREAK').slice(-3).reverse()
      .map((x) => ({ id: x.id, date: x.effectiveFrom, text: x.facts[0], priority: 1 }));
    const relation = (data?.relationshipBreaks ?? []).slice(-3).reverse()
      .map((x) => ({ id: x.id, date: data?.periodEnd ?? '', text: x.facts[0], priority: 2 }));
    const reaction = (data?.reactionAnomalies ?? []).slice(-3).reverse()
      .map((x) => ({ id: x.id, date: x.effectiveFrom, text: x.facts[0], priority: 3 }));
    const relative = (data?.turningPoints ?? []).filter((x) => x.status === 'confirmed' && x.ruleId === 'RELATIVE_STRENGTH_TURN').slice(-3).reverse()
      .map((x) => ({ id: x.id, date: x.effectiveFrom, text: x.facts[0], priority: 4 }));
    const reclaim = (data?.turningPoints ?? []).filter((x) => x.status === 'confirmed' && x.ruleId === 'TREND_STRUCTURE_RECLAIM').slice(-3).reverse()
      .map((x) => ({ id: x.id, date: x.effectiveFrom, text: x.facts[0], priority: 5 }));
    const market = (ledger?.turningPoints ?? []).slice(-3).reverse()
      .map((x) => ({ id: x.id, date: x.effectiveFrom, text: x.facts[0], priority: 6 }));
    return [...technical, ...relation, ...reaction, ...relative, ...reclaim, ...market]
      .sort((a, b) => a.priority - b.priority).slice(0, 3);
  }, [data, ledger]);
  if (!rows.length) return null;
  return <section className="card ci-today"><div><b>Market / Chart changes</b><span>最大3件</span></div>
    {rows.map((row) => <button type="button" key={row.id} onClick={onOpen}><span>{row.date}</span>{row.text} ↗</button>)}</section>;
};

import React, { useEffect, useMemo, useState } from 'react';
import { useChartIntelligence } from '../../hooks/useChartIntelligence';
import { useMarketLedger } from '../../hooks/useMarketLedger';
import type {
  ChartBar, ChartIntelligencePayload, MarketReplayContext, ReplayDistribution,
  ReplayLedgerSeries,
} from '../../types/chartIntelligence';
import './MarketContextReplay.css';

type Tab = 'OVERVIEW' | 'REPLAY' | 'LEDGER';
type Instrument = '1321' | '1306' | 'SPY' | 'QQQ';
type Horizon = 1 | 5 | 20;
type Range = '1M' | '3M' | '6M' | '1Y' | '5Y';
type ChartMode = 'CANDLE' | 'LINE';
type DrawTool = 'select' | 'horizontal' | 'trend' | 'zone' | 'arrow' | 'text';
type Point = { x: number; y: number };
type Drawing = { id: string; kind: Exclude<DrawTool, 'select'>; points: Point[]; text?: string };

interface DeepLink {
  schemaVersion?: string; selectedTab?: Tab; market?: 'JP' | 'US';
  instrumentId?: string; symbol?: Instrument; horizon?: Horizon;
  forecastId?: string; finalAction?: 'BUY' | 'WAIT' | 'SELL'; actionScore?: number;
  forecastAsOf?: string | null;
  directionProbabilities?: { UP: number; RANGE: number; DOWN: number } | null;
  priceLevels?: { current: number; upper: number; baseLow: number; baseHigh: number;
    lower: number; invalidation: number };
  brierSkill?: number | null; effectiveSample?: number;
}

const INSTRUMENTS: Record<Instrument, { market: 'JP' | 'US'; label: string; short: string }> = {
  '1321': { market: 'JP', label: '日経225 ETF（1321）', short: '1321' },
  '1306': { market: 'JP', label: 'TOPIX ETF（1306）', short: '1306' },
  SPY: { market: 'US', label: 'S&P 500 ETF（SPY）', short: 'SPY' },
  QQQ: { market: 'US', label: 'Nasdaq 100 ETF（QQQ）', short: 'QQQ' },
};
const RANGE_COUNT: Record<Range, number> = {
  '1M': 22, '3M': 66, '6M': 132, '1Y': 264, '5Y': 1320,
};
const TABS: Tab[] = ['OVERVIEW', 'REPLAY', 'LEDGER'];
const HORIZONS: Horizon[] = [1, 5, 20];
const DRAW_TOOLS: Array<{ id: DrawTool; label: string }> = [
  { id: 'select', label: '選択' }, { id: 'horizontal', label: '水平' },
  { id: 'trend', label: '線' }, { id: 'zone', label: '帯' },
  { id: 'arrow', label: '矢印' }, { id: 'text', label: 'メモ' },
];
const OVERLAY_DEFAULTS = {
  levels: true, zones: true, turning: true, events: false, news: false,
  short: false, credit: false, flow: false, breadth: false, relative: false,
  ma: false, bollinger: false, ichimoku: false, rsi: false, macd: false,
};
type OverlayKey = keyof typeof OVERLAY_DEFAULTS;

function readSession<T>(key: string): T | null {
  try { return JSON.parse(sessionStorage.getItem(key) ?? 'null') as T | null; } catch { return null; }
}
function readLocal<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) ?? '') as T; } catch { return fallback; }
}
function fmt(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return '未取得';
  return value.toLocaleString('ja-JP', { maximumFractionDigits: digits });
}
function pct(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return '未取得';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}
function path(values: Array<{ x: number; y: number }>) {
  return values.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
}

export interface ReplayPriceLabel {
  id: string; label: string; value: number; priority: number; tone: string;
}
export function layoutReplayPriceLabels(labels: ReplayPriceLabel[],
  toY: (value: number) => number, minY = 24, maxY = 400, gap = 20) {
  const placed: Array<ReplayPriceLabel & { y: number }> = [];
  [...labels].sort((a, b) => a.priority - b.priority).forEach((label) => {
    let y = Math.max(minY, Math.min(maxY, toY(label.value)));
    let guard = 0;
    while (placed.some((row) => Math.abs(row.y - y) < gap) && guard++ < labels.length + 2) {
      y += gap;
      if (y > maxY) y = Math.max(minY, y - gap * 2);
    }
    placed.push({ ...label, y });
  });
  return placed.sort((a, b) => a.y - b.y);
}

function useDrawings(instrument: Instrument) {
  const key = `argus.marketReplay.drawings.v1:${instrument}:daily`;
  const [drawings, setDrawingsState] = useState<Drawing[]>(() => readLocal(key, []));
  const [history, setHistory] = useState<Drawing[][]>([]);
  const [future, setFuture] = useState<Drawing[][]>([]);
  useEffect(() => {
    setDrawingsState(readLocal(key, [])); setHistory([]); setFuture([]);
  }, [key]);
  const setDrawings = (next: Drawing[]) => {
    setHistory((rows) => [...rows.slice(-29), drawings]);
    setFuture([]); setDrawingsState(next);
    try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* device-local best effort */ }
  };
  const undo = () => {
    const previous = history.at(-1); if (!previous) return;
    setFuture((rows) => [drawings, ...rows]); setHistory((rows) => rows.slice(0, -1));
    setDrawingsState(previous); try { localStorage.setItem(key, JSON.stringify(previous)); } catch { /* ignore */ }
  };
  const redo = () => {
    const next = future[0]; if (!next) return;
    setHistory((rows) => [...rows, drawings]); setFuture((rows) => rows.slice(1));
    setDrawingsState(next); try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* ignore */ }
  };
  return { drawings, setDrawings, undo, redo, canUndo: history.length > 0, canRedo: future.length > 0 };
}

const DrawingLayer: React.FC<{ drawings: Drawing[]; selected: string | null;
  onSelect: (id: string) => void }> = ({ drawings, selected, onSelect }) => (
  <g className="mr-my-layer" aria-label="MY drawings">
    <defs><marker id="mr-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4"
      orient="auto"><path d="M0,0 L8,4 L0,8 Z" /></marker></defs>
    {drawings.map((drawing) => {
      const [a, b = a] = drawing.points;
      const common = { onClick: (event: React.MouseEvent) => { event.stopPropagation(); onSelect(drawing.id); },
        className: selected === drawing.id ? 'is-selected' : '' };
      if (drawing.kind === 'horizontal') return <line key={drawing.id} {...common}
        x1="36" x2="882" y1={a.y} y2={a.y} />;
      if (drawing.kind === 'zone') return <rect key={drawing.id} {...common}
        x={Math.min(a.x, b.x)} y={Math.min(a.y, b.y)}
        width={Math.abs(a.x - b.x)} height={Math.abs(a.y - b.y)} />;
      if (drawing.kind === 'text') return <text key={drawing.id} {...common}
        x={a.x} y={a.y}>{drawing.text || 'memo'}</text>;
      return <line key={drawing.id} {...common} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
        markerEnd={drawing.kind === 'arrow' ? 'url(#mr-arrow)' : undefined} />;
    })}
  </g>
);

const MarketChart: React.FC<{ data: ChartIntelligencePayload; replay: MarketReplayContext | null;
  deep: DeepLink | null; range: Range; mode: ChartMode; overlays: typeof OVERLAY_DEFAULTS;
  drawings: Drawing[]; tool: DrawTool; selectedDrawing: string | null;
  onSelectDrawing: (id: string | null) => void; onCreateDrawing: (drawing: Drawing) => void;
  focusDate: string | null }> = ({ data, replay, deep, range, mode, overlays, drawings, tool,
    selectedDrawing, onSelectDrawing, onCreateDrawing, focusDate }) => {
  const bars = data.indicators.bars.slice(-RANGE_COUNT[range]);
  const [draft, setDraft] = useState<Point | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  if (!bars.length) return <div className="mr-empty">OHLCV確認待ち</div>;
  const priceValues = bars.flatMap((bar) => [bar.high, bar.low]);
  const forecast = deep?.priceLevels;
  if (forecast) priceValues.push(forecast.upper, forecast.lower, forecast.invalidation);
  const lo = Math.min(...priceValues), hi = Math.max(...priceValues), span = hi - lo || 1;
  const x = (index: number) => 38 + index / Math.max(1, bars.length - 1) * 662;
  const y = (value: number) => 24 + (hi - value) / span * 376;
  const maxVolume = Math.max(1, ...bars.map((bar) => bar.volume ?? 0));
  const current = bars.at(-1)!;
  const recent = bars.slice(-20);
  const swingHigh = Math.max(...recent.map((bar) => bar.high));
  const swingLow = Math.min(...recent.map((bar) => bar.low));
  const zones = data.zones.filter((zone) => zone.status !== 'broken').slice(-8);
  const supports = zones.filter((zone) => zone.center < current.close).sort((a, b) => b.center - a.center);
  const resistances = zones.filter((zone) => zone.center > current.close).sort((a, b) => a.center - b.center);
  const labels = layoutReplayPriceLabels([
    { id: 'current', label: data.quoteState ?? 'CLOSE', value: current.close, priority: 1, tone: 'current' },
    ...(forecast ? [
      { id: 'invalid', label: '無効', value: forecast.invalidation, priority: 2, tone: 'invalid' },
      { id: 'upper', label: '上限', value: forecast.upper, priority: 3, tone: 'upper' },
      { id: 'base', label: '本線', value: (forecast.baseLow + forecast.baseHigh) / 2, priority: 3, tone: 'base' },
      { id: 'lower', label: '下限', value: forecast.lower, priority: 3, tone: 'lower' },
    ] as ReplayPriceLabel[] : []),
    ...(supports[0] ? [{ id: 'support', label: '支持', value: supports[0].upper, priority: 4, tone: 'support' }] : []),
    ...(resistances[0] ? [{ id: 'resistance', label: '抵抗', value: resistances[0].lower, priority: 4, tone: 'resistance' }] : []),
    { id: 'high', label: '高値', value: swingHigh, priority: 5, tone: 'swing' },
    { id: 'low', label: '安値', value: swingLow, priority: 5, tone: 'swing' },
  ], y);
  const click = (event: React.MouseEvent<SVGSVGElement>) => {
    if (tool === 'select') { onSelectDrawing(null); return; }
    const rect = event.currentTarget.getBoundingClientRect();
    const point = { x: (event.clientX - rect.left) / rect.width * 940,
      y: (event.clientY - rect.top) / rect.height * 480 };
    if (tool === 'horizontal' || tool === 'text') {
      onCreateDrawing({ id: `my-${Date.now()}`, kind: tool, points: [point],
        text: tool === 'text' ? 'メモ' : undefined });
      return;
    }
    if (!draft) { setDraft(point); return; }
    onCreateDrawing({ id: `my-${Date.now()}`, kind: tool, points: [draft, point] });
    setDraft(null);
  };
  const lineValues = bars.map((bar, index) => ({ x: x(index), y: y(bar.close) }));
  return <div className="mr-chart-frame">
    <svg className="mr-chart" viewBox="0 0 940 480" role="img"
      aria-label={`${data.displayNameJa ?? data.symbol} Market Context chart`}
      onClick={click} onMouseLeave={() => setHover(null)}>
      <rect width="940" height="480" className="mr-chart-bg" />
      {[0, .25, .5, .75, 1].map((ratio) => <g key={ratio}>
        <line x1="38" x2="780" y1={24 + ratio * 376} y2={24 + ratio * 376} className="mr-grid" />
        <text x="786" y={29 + ratio * 376}>{fmt(hi - ratio * span)}</text>
      </g>)}
      {overlays.zones && zones.map((zone) => <rect key={zone.id} className="mr-zone"
        x="38" width="742" y={y(zone.upper)}
        height={Math.max(2, y(zone.lower) - y(zone.upper))}><title>{zone.strength} {fmt(zone.lower)}–{fmt(zone.upper)}</title></rect>)}
      {forecast && overlays.levels && <g className="mr-forecast">
        <line x1="700" x2="780" y1={y(forecast.invalidation)} y2={y(forecast.invalidation)} className="is-invalid" />
        <path d={`M700,${y(forecast.current)} L780,${y(forecast.baseHigh)} L780,${y(forecast.baseLow)} Z`} />
        <line x1="700" x2="780" y1={y(forecast.upper)} y2={y(forecast.upper)} className="is-up" />
        <line x1="700" x2="780" y1={y(forecast.lower)} y2={y(forecast.lower)} className="is-down" />
        <line x1="700" x2="700" y1="24" y2="400" className="is-boundary" />
        <text x="690" y="20">実績</text><text x="708" y="20">予測</text>
      </g>}
      {mode === 'CANDLE' ? bars.map((bar, index) => {
        const up = bar.close >= bar.open; const cx = x(index);
        const width = Math.max(1, Math.min(7, 520 / bars.length));
        return <g key={bar.date} onMouseEnter={() => setHover(index)}>
          <line x1={cx} x2={cx} y1={y(bar.high)} y2={y(bar.low)}
            className={up ? 'mr-up' : 'mr-down'} />
          <rect x={cx - width / 2} width={width} y={y(Math.max(bar.open, bar.close))}
            height={Math.max(1, Math.abs(y(bar.open) - y(bar.close)))}
            className={up ? 'mr-candle mr-up' : 'mr-candle mr-down'} />
        </g>;
      }) : <path d={path(lineValues)} className="mr-price-line" />}
      <circle cx={x(bars.length - 1)} cy={y(current.close)} r="4.5" className="mr-current-dot" />
      {bars.map((bar, index) => <rect key={`vol-${bar.date}`} x={x(index) - 1.5} width="3"
        y={462 - ((bar.volume ?? 0) / maxVolume) * 48}
        height={((bar.volume ?? 0) / maxVolume) * 48} className="mr-volume" />)}
      {overlays.ma && <path d={path(bars.map((bar, index) => ({
        x: x(index), y: y(bar.ma['25'] ?? bar.close),
      })))} className="mr-ma" />}
      {overlays.bollinger && <>{(['upper2', 'lower2'] as const).map((key) =>
        <path key={key} d={path(bars.map((bar, index) => ({
          x: x(index), y: y(bar.bollinger?.[key] ?? bar.close),
        })))} className="mr-bollinger" />)}</>}
      {overlays.turning && data.turningPoints.slice(-20).map((point) => {
        const index = bars.findIndex((bar) => bar.date >= point.effectiveFrom);
        return index < 0 ? null : <path key={point.id}
          d={`M${x(index) - 5},${y(bars[index].low) + 9} L${x(index)},${y(bars[index].low) + 1} L${x(index) + 5},${y(bars[index].low) + 9} Z`}
          className="mr-turn"><title>{point.facts.join(' / ')}</title></path>;
      })}
      {overlays.events && data.eventMarkers.filter((event) =>
        !/filing|disclosure|earnings/i.test(event.kind)).slice(-10).map((event) => {
        const index = bars.findIndex((bar) => bar.date >= event.date);
        return index < 0 ? null : <line key={event.id} x1={x(index)} x2={x(index)}
          y1="24" y2="400" className="mr-event"><title>{event.labelJa}</title></line>;
      })}
      {overlays.news && data.eventMarkers.filter((event) =>
        /filing|disclosure|earnings/i.test(event.kind)).slice(-10).map((event) => {
        const index = bars.findIndex((bar) => bar.date >= event.date);
        return index < 0 ? null : <circle key={`news-${event.id}`} cx={x(index)}
          cy={y(bars[index].high) - 7} r="4" className="mr-news"><title>{event.labelJa}</title></circle>;
      })}
      {replay && replay.extremes.events.filter((event) => {
        const series = String(event.seriesId ?? '').toLowerCase();
        return (overlays.short && series.includes('short'))
          || (overlays.credit && series.includes('credit'))
          || (overlays.flow && series.includes('flow'))
          || (overlays.breadth && series.includes('breadth'))
          || (overlays.relative && series.includes('relative'));
      }).slice(-30).map((event, markerIndex) => {
        const date = String(event.availableFrom ?? event.date ?? '').slice(0, 10);
        const index = bars.findIndex((bar) => bar.date >= date);
        return index < 0 ? null : <circle key={`ledger-${String(event.episodeId ?? markerIndex)}`}
          cx={x(index)} cy={y(bars[index].low) + 7} r="3.5" className="mr-ledger-marker">
          <title>{`${String(event.seriesId ?? 'ledger')} · ${String(event.family ?? '')}`}</title></circle>;
      })}
      {focusDate && (() => { const index = bars.findIndex((bar) => bar.date >= focusDate);
        return index < 0 ? null : <line x1={x(index)} x2={x(index)} y1="24" y2="400"
          className="mr-focus"><title>{focusDate} 類似局面</title></line>; })()}
      <DrawingLayer drawings={drawings} selected={selectedDrawing} onSelect={onSelectDrawing} />
      {draft && <circle cx={draft.x} cy={draft.y} r="6" className="mr-draft" />}
      {labels.map((label) => <g key={label.id} className={`mr-price-chip is-${label.tone}`}>
        <line x1="780" x2="816" y1={y(label.value)} y2={label.y} />
        <rect x="816" y={label.y - 9} width="120" height="18" rx="3" />
        <text x="821" y={label.y + 4}>{label.label} {fmt(label.value)}</text>
      </g>)}
      {hover != null && bars[hover] && <g className="mr-crosshair">
        <line x1={x(hover)} x2={x(hover)} y1="24" y2="462" />
        <rect x={Math.min(570, Math.max(42, x(hover) - 95))} y="28" width="205" height="72" rx="5" />
        <text x={Math.min(580, Math.max(52, x(hover) - 85))} y="44">{bars[hover].date} · 実績</text>
        <text x={Math.min(580, Math.max(52, x(hover) - 85))} y="61">O {fmt(bars[hover].open)} H {fmt(bars[hover].high)}</text>
        <text x={Math.min(580, Math.max(52, x(hover) - 85))} y="78">L {fmt(bars[hover].low)} C {fmt(bars[hover].close)}</text>
        <text x={Math.min(580, Math.max(52, x(hover) - 85))} y="94">V {fmt(bars[hover].volume, 0)} · {data.quoteState ?? 'CLOSE'}</text>
      </g>}
      <text x="38" y="476">{bars[0].date}</text><text x="624" y="476">{bars.at(-1)?.date}</text>
    </svg>
  </div>;
};

const DistributionChart: React.FC<{ label: string; data?: ReplayDistribution }> = ({ label, data }) => {
  if (!data || !data.count) return null;
  const max = Math.max(1, ...data.histogram.map((row) => row.count));
  return <div className="mr-dist"><div><b>{label}</b><span>n={data.count}</span></div>
    <svg viewBox="0 0 260 96" role="img" aria-label={`${label} distribution`}>
      {data.histogram.map((row, index) => <rect key={index} x={8 + index * 24} width="18"
        y={72 - row.count / max * 58} height={row.count / max * 58} />)}
      <line x1="8" x2="250" y1="72" y2="72" />
    </svg>
    <small>q10 {fmt(data.q10)}　中央値 {fmt(data.median)}　q90 {fmt(data.q90)}</small>
  </div>;
};

const EventStudy: React.FC<{ context: MarketReplayContext }> = ({ context }) => {
  const points = context.eventStudy.points.filter((point) => point.median != null);
  if (!points.length) return null;
  const values = points.flatMap((point) => [point.q10, point.q25, point.median, point.q75, point.q90])
    .filter((value): value is number => value != null);
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const x = (day: number) => 32 + (day + 20) / 40 * 440;
  const y = (value: number) => 16 + (hi - value) / span * 150;
  const line = (key: 'median' | 'q25' | 'q75') => path(points.map((point) => ({
    x: x(point.day), y: y(point[key] ?? 0),
  })));
  return <div className="card mr-event-study"><div className="mr-card-head"><b>EVENT STUDY</b><span>−20 → +20日</span></div>
    <svg viewBox="0 0 500 190" role="img" aria-label="類似局面 event study">
      <line x1={x(0)} x2={x(0)} y1="12" y2="168" className="event-zero" />
      <path d={`${line('q25')} ${[...points].reverse().map((point) => `L${x(point.day)},${y(point.q75 ?? 0)}`).join(' ')} Z`} className="event-band" />
      <path d={line('median')} className="event-median" />
      <text x="30" y="184">−20</text><text x={x(0) - 4} y="184">0</text><text x="455" y="184">+20</text>
    </svg>
  </div>;
};

const CalibrationCurve: React.FC<{ context: MarketReplayContext }> = ({ context }) => {
  const points = context.calibrationCurve.points;
  if (!points.length) return null;
  return <div className="card mr-calibration"><div className="mr-card-head"><b>CALIBRATION</b><span>past-only</span></div>
    <svg viewBox="0 0 250 210" role="img" aria-label="予測確率と実現頻度">
      <line x1="30" x2="220" y1="180" y2="20" className="ideal" />
      {points.map((point) => <g key={point.bin}>
        <circle cx={30 + point.predicted * 190} cy={180 - point.observed * 160}
          r={point.smallSample ? 3 : Math.min(9, 3 + point.sample / 3)}
          className={point.smallSample ? 'small' : ''}><title>予測 {Math.round(point.predicted * 100)}% / 実現 {Math.round(point.observed * 100)}% / n={point.sample}</title></circle>
      </g>)}
      <text x="84" y="204">予測確率 →</text><text x="2" y="18">実現</text>
    </svg>
  </div>;
};

function seriesGroup(seriesId: string) {
  const key = seriesId.toLowerCase();
  if (key.includes('credit') || key.includes('margin')) return 'CREDIT';
  if (key.includes('short')) return 'DAILY SHORT';
  if (key.includes('breadth') || key.includes('ratio_')) return 'BREADTH';
  if (key.includes('relative') || key.includes('nikkei') || key.includes('topix')) return 'RELATIVE';
  return 'INVESTOR FLOW';
}

const MiniSpark: React.FC<{ values: number[] }> = ({ values }) => {
  if (values.length < 2) return null;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  return <svg className="mr-spark" viewBox="0 0 90 26" aria-hidden><path d={path(values.map((value, index) => ({
    x: index / (values.length - 1) * 88 + 1, y: 24 - (value - lo) / span * 22,
  })))} /></svg>;
};

const LedgerGrid: React.FC<{ market: 'JP' | 'US'; replay: MarketReplayContext | null;
  data: ChartIntelligencePayload | null }> = ({ market, replay, data }) => {
  const { ledger } = useMarketLedger();
  const rich = replay?.extremes.series ?? [];
  const rows: ReplayLedgerSeries[] = rich.length ? rich : (ledger?.table ?? [])
    .filter((row) => row.latestValue != null)
    .map((row) => ({ seriesId: row.seriesId, labelJa: row.labelJa,
      unit: row.unit, currentValue: row.latestValue!, change1: row.previousChange,
      cumulative4: row.fourPeriodTotal, cumulative13: null,
      rollingPercentile: row.historicalPercentile ?? 0, zScore: 0,
      localPeak: false, localBottom: false, extremeFamily: null,
      history: row.history.filter((point) => point.value != null)
        .map((point) => ({ date: point.periodEnd, availableFrom: point.periodEnd, value: point.value! })) }));
  if (market === 'US') {
    const bars = data?.indicators.bars ?? [];
    return <div className="mr-us-ledger">
      <div className="mr-coverage"><b>DATA COVERAGE</b>
        {([['PRICE', 'HIGH'], ['BREADTH', 'MEDIUM'], ['FLOW', 'LOW'],
          ['SHORT', 'LOW'], ['MACRO', 'HIGH']] as const).map(([name, level]) =>
          <span key={name}>{name}<em className={`is-${level.toLowerCase()}`}>{level}</em></span>)}</div>
      <div className="card mr-ledger-row"><b>PRICE STRUCTURE</b><strong>{fmt(bars.at(-1)?.close)}</strong>
        <MiniSpark values={bars.slice(-30).map((bar) => bar.close)} /><small>USは取得済み価格・相対強弱のみ。JP固有需給を転用しません。</small></div>
      {(data?.relativeStrength ? Object.entries(data.relativeStrength) : []).slice(0, 4).map(([id, row]) =>
        <div className="card mr-ledger-row" key={id}><b>{id.toUpperCase()}</b><strong>{pct(row.change20Pct)}</strong>
          <MiniSpark values={row.history.slice(-30).map((point) => point.value)} /><small>{row.classification}</small></div>)}
    </div>;
  }
  const groups = ['CREDIT', 'DAILY SHORT', 'INVESTOR FLOW', 'BREADTH', 'RELATIVE'];
  return <div className="mr-ledger">
    {groups.map((group) => {
      const selected = rows.filter((row) => seriesGroup(row.seriesId) === group);
      if (!selected.length) return null;
      return <section key={group}><div className="mr-section-title"><b>{group}</b><span>{selected.length} series</span></div>
        <div className="mr-ledger-grid">{selected.slice(0, group === 'INVESTOR FLOW' ? 8 : 6).map((row) =>
          <div className="card mr-ledger-row" key={row.seriesId}>
            <b>{row.labelJa}</b><strong>{fmt(row.currentValue)} <small>{row.unit ?? ''}</small></strong>
            <MiniSpark values={row.history.slice(-30).map((point) => point.value)} />
            <div><span>1期 {fmt(row.change1)}</span><span>4期 {fmt(row.cumulative4)}</span>
              <span>{fmt(row.rollingPercentile, 0)}%ile</span></div>
            {(row.localPeak || row.localBottom) && <em>{row.localPeak ? '▲ PEAK' : '▼ BOTTOM'}</em>}
          </div>)}</div></section>;
    })}
  </div>;
};

export const MarketContextReplay: React.FC = () => {
  const initialDeep = useMemo(() => readSession<DeepLink>('argus.replayContext'), []);
  const mirror = useMemo(() => readSession<DeepLink>('argus.todayDecisionMirror'), []);
  const initialSymbol = initialDeep?.symbol ?? mirror?.symbol
    ?? readLocal<Instrument>('argus.marketReplay.instrument.v1', '1321');
  const [instrument, setInstrument] = useState<Instrument>(
    initialSymbol in INSTRUMENTS ? initialSymbol as Instrument : '1321');
  const [horizon, setHorizon] = useState<Horizon>(initialDeep?.horizon
    ?? readLocal<Horizon>('argus.marketReplay.horizon.v1', 5));
  const [tab, setTab] = useState<Tab>(() => initialDeep?.selectedTab
    ?? readLocal('argus.marketReplay.tab.v1', 'OVERVIEW'));
  const [range, setRange] = useState<Range>(() => readLocal('argus.marketReplay.range.v1', '1Y'));
  const [mode, setMode] = useState<ChartMode>('CANDLE');
  const [overlays, setOverlays] = useState(() => readLocal('argus.marketReplay.overlays.v1', OVERLAY_DEFAULTS));
  const [tool, setTool] = useState<DrawTool>('select');
  const [selectedDrawing, setSelectedDrawing] = useState<string | null>(null);
  const [focusDate, setFocusDate] = useState<string | null>(null);
  const info = INSTRUMENTS[instrument];
  const { data, loading, error } = useChartIntelligence({
    scope: 'market', symbol: instrument, market: info.market, timeframe: 'daily',
  });
  const replay = data?.marketReplay?.contexts?.[String(horizon)] ?? null;
  const draw = useDrawings(instrument);
  const action = initialDeep?.finalAction ?? mirror?.finalAction ?? null;
  const score = initialDeep?.actionScore ?? mirror?.actionScore ?? null;
  const deep = initialDeep?.symbol === instrument ? initialDeep : null;
  const probabilities = deep?.directionProbabilities
    ?? (data?.todayIntelligence?.calibration.horizons?.[String(horizon)]
      ?.probabilityEligibility?.eligible
      ? data.todayIntelligence.calibration.horizons[String(horizon)].directionProbabilities ?? null
      : null);
  const quality = replay?.probabilityQuality;
  const switchTab = (next: Tab) => {
    setTab(next); try { localStorage.setItem('argus.marketReplay.tab.v1', JSON.stringify(next)); } catch { /* ignore */ }
  };
  const switchRange = (next: Range) => {
    setRange(next); try { localStorage.setItem('argus.marketReplay.range.v1', JSON.stringify(next)); } catch { /* ignore */ }
  };
  const switchInstrument = (next: Instrument) => {
    setInstrument(next); setFocusDate(null);
    try { localStorage.setItem('argus.marketReplay.instrument.v1', JSON.stringify(next)); } catch { /* device-local */ }
  };
  const switchHorizon = (next: Horizon) => {
    setHorizon(next);
    try { localStorage.setItem('argus.marketReplay.horizon.v1', JSON.stringify(next)); } catch { /* device-local */ }
  };
  const toggleOverlay = (key: OverlayKey) => {
    const next = { ...overlays, [key]: !overlays[key] }; setOverlays(next);
    try { localStorage.setItem('argus.marketReplay.overlays.v1', JSON.stringify(next)); } catch { /* ignore */ }
  };
  const deleteDrawing = () => {
    if (!selectedDrawing) return;
    draw.setDrawings(draw.drawings.filter((row) => row.id !== selectedDrawing));
    setSelectedDrawing(null);
  };
  return <div className="market-replay">
    <header className="mr-header">
      <div><span>MARKET CONTEXT REPLAY</span><h2>{info.label}</h2>
        <small>{horizon}営業日 · {data?.periodEnd ?? 'データ確認中'} · 日足 · {data?.quoteState ?? 'CLOSE'}
          {data && data.status !== 'live' ? ' · 暫定' : ''}</small></div>
      <div className={`mr-decision is-${(action ?? 'unknown').toLowerCase()}`}>
        <span>TODAY MIRROR</span><strong>{action ?? '判断待ち'}</strong><b>{score == null ? '' : `${score}/7`}</b>
      </div>
    </header>
    <div className="mr-selectors">
      <div role="group" aria-label="Instrument">{(Object.keys(INSTRUMENTS) as Instrument[]).map((value) =>
        <button type="button" key={value} className={instrument === value ? 'active' : ''}
          onClick={() => switchInstrument(value)}>{value}</button>)}</div>
      <div role="group" aria-label="Forecast horizon">{HORIZONS.map((value) =>
        <button type="button" key={value} className={horizon === value ? 'active' : ''}
          onClick={() => switchHorizon(value)}>{value}D</button>)}</div>
    </div>
    <nav className="mr-tabs" aria-label="Market views">{TABS.map((value) =>
      <button type="button" key={value} aria-selected={tab === value}
        onClick={() => switchTab(value)}>{value}</button>)}</nav>
    {loading && !data && <div className="card mr-empty">キャッシュ取得中…</div>}
    {error && <div className="card mr-empty">前回値を保持 · {error}</div>}
    {data && tab === 'OVERVIEW' && <div className="mr-overview">
      <section className="mr-summary-row">
        <div className="mr-price"><span>{data.quoteState ?? 'CLOSE'}</span>
          <strong>{fmt(data.indicators.bars.at(-1)?.close)}</strong><small>{data.periodEnd}</small></div>
        <div className="mr-direction">{probabilities ? <>
          <span className="up">UP <b>{probabilities.UP}%</b></span>
          <span>RANGE <b>{probabilities.RANGE}%</b></span>
          <span className="down">DOWN <b>{probabilities.DOWN}%</b></span></>
          : <strong>方向性不明</strong>}</div>
        <div className="mr-skill"><span>予測Skill</span>
          <strong>{quality?.brierSkill != null && quality.brierSkill > 0 ? pct(quality.brierSkill * 100) : 'なし'}</strong>
          <small>実効n {quality?.effectiveSample ?? replay?.similarEpisodes.effectiveSampleCount ?? '待機'}</small></div>
      </section>
      <div className="card mr-chart-card">
        <div className="mr-chart-toolbar">
          <div>{(['1M', '3M', '6M', '1Y', '5Y'] as Range[]).map((value) =>
            <button type="button" key={value} className={range === value ? 'active' : ''}
              onClick={() => switchRange(value)}>{value}</button>)}</div>
          <div><button type="button" className={mode === 'CANDLE' ? 'active' : ''}
            onClick={() => setMode('CANDLE')}>Candlestick</button>
            <button type="button" className={mode === 'LINE' ? 'active' : ''}
              onClick={() => setMode('LINE')}>Line</button></div>
        </div>
        <MarketChart data={data} replay={replay} deep={deep} range={range} mode={mode}
          overlays={overlays} drawings={draw.drawings} tool={tool}
          selectedDrawing={selectedDrawing} onSelectDrawing={setSelectedDrawing}
          onCreateDrawing={(drawing) => draw.setDrawings([...draw.drawings, drawing])}
          focusDate={focusDate} />
        <div className="mr-drawing-tools" role="toolbar" aria-label="MY drawing tools">
          <span>MY</span>{DRAW_TOOLS.map((item) => <button type="button" key={item.id}
            className={tool === item.id ? 'active' : ''} onClick={() => setTool(item.id)}>{item.label}</button>)}
          <button type="button" disabled={!selectedDrawing} onClick={deleteDrawing}>削除</button>
          <button type="button" disabled={!draw.canUndo} onClick={draw.undo}>Undo</button>
          <button type="button" disabled={!draw.canRedo} onClick={draw.redo}>Redo</button>
          <label><input type="checkbox" disabled /> 判断条件に使用 OFF</label>
        </div>
        <details className="mr-overlays"><summary>OVERLAYS</summary><div>
          {(Object.keys(overlays) as OverlayKey[]).map((key) => <label key={key}>
            <input type="checkbox" checked={overlays[key]} onChange={() => toggleOverlay(key)} />{key}</label>)}
        </div></details>
      </div>
      <div className="mr-overview-grid">
        <div className="card mr-factors"><div className="mr-card-head"><b>ENGINE FACTORS</b><span>{replay?.currentRegime.trend ?? 'cache pending'}</span></div>
          {replay && Object.entries(replay.currentFeatures).slice(0, 5).map(([key, value]) =>
            <span key={key}>{key}<b>{value.toFixed(3)}</b></span>)}</div>
        <div className="card mr-changes"><div className="mr-card-head"><b>判断変更条件</b><span>最大3</span></div>
          {(replay?.changeConditions ?? []).map((row) => <div key={row.sourceId ?? row.triggerType}>
            <b>{row.triggerType.includes('upside') ? '上方向' : row.triggerType.includes('downside') ? '下方向' : '再評価'}</b>
            <span>{row.price == null ? row.event : `${fmt(row.price)} 終値確認`}</span></div>)}
          {!replay?.changeConditions.length && <small>background cache更新待ち</small>}</div>
      </div>
    </div>}
    {data && tab === 'REPLAY' && <div className="mr-replay">
      {!replay ? <div className="card mr-empty">自然tickでReplay indexを準備中。ページ操作では再計算しません。</div> : <>
        <section className="mr-replay-kpi"><span>類似局面 <b>{replay.similarEpisodes.rawOccurrenceCount}</b></span>
          <span>実効標本 <b>{replay.similarEpisodes.effectiveSampleCount}</b></span>
          <span>平均反応 <b>{fmt(replay.outcomeDistributions.reactionDelayDays?.median)}日</b></span></section>
        <div className="card mr-analogs"><div className="mr-card-head"><b>TOP ANALOGS</b><span>cooldown {replay.similarEpisodes.cooldownTradingDays}日</span></div>
          {replay.similarEpisodes.episodes.slice(0, 5).map((episode) =>
            <button type="button" key={episode.episodeId} onClick={() => { setFocusDate(episode.date); switchTab('OVERVIEW'); }}>
              <time>{episode.date}</time><strong>類似 {fmt(episode.similarityPct, 0)}%</strong>
              <span>{horizon}D {pct(episode.outcomes[String(horizon) as '1' | '5' | '20'])}</span>
              <em>{episode.outcomes.reactionDelayDays == null ? episode.outcomes.reactionClass
                : `${episode.outcomes.reactionDelayDays}日後`}</em></button>)}</div>
        <div className="mr-visual-grid"><EventStudy context={replay} />
          <CalibrationCurve context={replay} /></div>
        <div className="mr-distributions">{(['1', '5', '20', 'mfe', 'mae', 'reactionDelayDays'] as const)
          .map((key) => <DistributionChart key={key}
            label={key === 'reactionDelayDays' ? 'REACTION DELAY' : `${key.toUpperCase()}${/^[0-9]/.test(key) ? 'D RETURN' : ''}`}
            data={replay.outcomeDistributions[key]} />)}</div>
        {replay.extremes.events.length > 0 && <div className="mr-extreme-grid">
          {replay.extremes.events.slice(-6).reverse().map((event, index) => {
            const outcomes = (event.outcomes && typeof event.outcomes === 'object'
              ? event.outcomes : {}) as Record<string, unknown>;
            const value = (key: string) => typeof outcomes[key] === 'number'
              ? outcomes[key] as number : null;
            return <div className="card mr-extreme" key={String(event.episodeId ?? index)}>
              <div><b>{String(event.seriesId ?? 'LEDGER')}</b><em>{String(event.family ?? '')}</em></div>
              <strong>{fmt(typeof event.percentile === 'number' ? event.percentile : null, 0)}%ile</strong>
              <span>5D {pct(value('5'))}</span><span>MFE {pct(value('mfe'))}</span>
              <span>MAE {pct(value('mae'))}</span><small>反応 {fmt(value('reactionDelayDays'), 0)}日</small>
            </div>;
          })}</div>}
        <div className="card mr-regimes"><div className="mr-card-head"><b>REGIME</b><span>n≥20</span></div>
          {replay.regimeAnalysis.map((row) => <div key={row.regime}><b>{row.regime}</b>
            <span>n={row.effectiveSample}</span><strong>{row.eligible ? pct(row.medianReturnPct) : 'サンプル不足'}</strong></div>)}</div>
        {data.todayIntelligence?.failedRally && <div className="card mr-failed">
          <div className="mr-card-head"><b>上昇失速パターン</b><span>{data.todayIntelligence.failedRally.state}</span></div>
          <strong>発生 {data.todayIntelligence.failedRally.backtest.rawOccurrenceCount} · 実効 {data.todayIntelligence.failedRally.backtest.effectiveSampleCount}</strong>
          <span>{Object.entries(data.todayIntelligence.failedRally.backtest.outcomes).slice(0, 3)
            .map(([key, row]) => {
              const outcome = row as { averageReturnPct?: number | null };
              return `${key}D ${pct(outcome.averageReturnPct)}`;
            }).join(' · ')}</span>
          <small>パターンは検出可能 · 将来方向のSkillなし</small></div>}
      </>}
    </div>}
    {data && tab === 'LEDGER' && <LedgerGrid market={info.market} replay={replay} data={data} />}
    <footer className="mr-system-line">
      <span>AI POST 0</span><span>{data?.marketReplay?.methodVersion ?? 'replay cache pending'}</span>
      <span>read-back {data?.marketReplay?.readBack.verificationStatus ?? 'pending'}</span>
      <span>{replay?.datasetHash?.slice(0, 10) ?? 'no dataset hash'}</span>
    </footer>
  </div>;
};

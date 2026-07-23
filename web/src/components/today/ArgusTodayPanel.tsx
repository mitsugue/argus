import React from 'react';
import type { ArgusTodayView, MarketSelectionMode, TodayProjection } from '../../domain/argusTodayView';
import { formatEventTime, quoteDisplayLabel } from '../../domain/argusTodayView';
import { SIGNAL_ORDER, SIGNALS } from '../../domain/actionLevel';
import type { RouteKey } from '../NavRail';
import './ArgusToday.css';

interface Props {
  view: ArgusTodayView;
  onMode: (mode: MarketSelectionMode) => void;
  onInstrument: (market: 'JP' | 'US', symbol: string) => void;
  onNavigate: (key: RouteKey) => void;
  onOpenAsset?: (symbol: string) => void;
  aiButton: React.ReactNode;
}

const ACTION_TONE = { BUY: 'var(--value-positive)', WAIT: 'var(--amber, #fbbf24)', SELL: 'var(--value-negative)' };
const mark = (yes: boolean) => yes ? '○' : '×';
const fmt = (v: number) => v >= 1000 ? v.toLocaleString('ja-JP', { maximumFractionDigits: 1 }) : v.toFixed(2);
const fmtMove = (v: number, suffix = '') => `${fmt(v)}${suffix}`;
const shortDate = (value?: string | null) => value ? value.slice(5).replace('-', '/') : '';
const moveTone = (value: number, previous?: number | null) => previous == null || value === previous
  ? 'flat' : value > previous ? 'up' : 'down';
const zoneLabel = (kind: '支持' | '抵抗', status: string) =>
  `${kind}${status === 'reclaimed' ? '（回復）' : status === 'broken' ? '（突破済み）' : ''}`;
const probabilityReasonJa = (codes: string[]) => {
  if (codes.includes('effective_sample_below_30')) return '実効標本が30未満';
  if (codes.includes('brier_skill_non_positive')
    || codes.includes('model_not_better_than_baseline')) return 'Brier Skillが基準以下';
  if (codes.includes('calibration_integrity_failed')
    || codes.includes('future_leakage_not_excluded')) return '校正完全性が未確認';
  if (codes.includes('probability_sum_not_100')) return '確率合計を検証できません';
  return 'サーバー適格性判定待ち';
};

const Sparkline: React.FC<{ values: number[] }> = ({ values }) => {
  if (values.length < 2) return null;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const points = values.map((value, index) => `${index / (values.length - 1) * 42},${12 - (value - lo) / span * 10}`).join(' ');
  return <svg className="at-spark" viewBox="0 0 42 14" aria-hidden><polyline points={points} /></svg>;
};

interface PriceLabel { key: string; label: string; value: number; priority: number; tone: string }

export function layoutPriceLabels(labels: PriceLabel[], toY: (value: number) => number,
  minY = 16, maxY = 308, gap = 17): Array<PriceLabel & { y: number }> {
  const accepted: Array<PriceLabel & { y: number }> = [];
  for (const label of [...labels].sort((a, b) => a.priority - b.priority || b.value - a.value)) {
    let y = Math.max(minY, Math.min(maxY, toY(label.value)));
    for (const row of accepted) {
      if (Math.abs(y - row.y) < gap) y = row.y + (y >= row.y ? gap : -gap);
    }
    y = Math.max(minY, Math.min(maxY, y));
    accepted.push({ ...label, y });
  }
  return accepted.sort((a, b) => a.y - b.y);
}

export function formatInstrumentPrice(value: number, instrumentId: string): string {
  const isJp = instrumentId.startsWith('JP:') || /:\d{4}:/.test(instrumentId);
  return value.toLocaleString(isJp ? 'ja-JP' : 'en-US', {
    minimumFractionDigits: isJp ? 0 : 2,
    maximumFractionDigits: isJp ? (value < 100 ? 1 : 0) : 2,
  });
}

const ProjectionChart: React.FC<{ projection: TodayProjection; onActivate: () => void }> = ({ projection, onActivate }) => {
  const all = projection.history.map((point) => point.value).concat([
    projection.baseLow, projection.baseHigh, projection.upside, projection.downside, projection.invalidation,
    ...(projection.support ? [projection.support.low, projection.support.high] : []),
    ...(projection.resistance ? [projection.resistance.low, projection.resistance.high] : []),
  ]);
  const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  const x = (index: number) => 28 + index / Math.max(1, projection.history.length - 1) * 460;
  const y = (value: number) => 16 + (hi - value) / span * 292;
  const path = projection.history.map((point, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(' ');
  const currentX = 488, forecastX = 570;
  const median = (projection.baseLow + projection.baseHigh) / 2;
  const markerX = (date: string) => {
    const index = projection.history.findIndex((point) => point.date === date);
    return index < 0 ? null : x(index);
  };
  const recent = projection.history.slice(-20);
  const swingHigh = recent.reduce((best, point) => point.value > best.value ? point : best, recent[0]);
  const swingLow = recent.reduce((best, point) => point.value < best.value ? point : best, recent[0]);
  const priceLabels = layoutPriceLabels([
    { key: 'current', label: quoteDisplayLabel(projection.quoteState), value: projection.current, priority: 0, tone: 'current' },
    { key: 'invalid', label: '無効', value: projection.invalidation, priority: 1, tone: 'invalid' },
    { key: 'upper', label: '上限', value: projection.upside, priority: 2, tone: 'upper' },
    { key: 'lower', label: '下限', value: projection.downside, priority: 3, tone: 'lower' },
    ...(projection.support ? [{ key: 'support', label: zoneLabel('支持', projection.support.status), value: projection.support.high,
      priority: 4, tone: 'support' }] : []),
    ...(projection.resistance ? [{ key: 'resistance', label: zoneLabel('抵抗', projection.resistance.status), value: projection.resistance.low,
      priority: 5, tone: 'resistance' }] : []),
    { key: 'swing-high', label: '高値', value: swingHigh.value, priority: 6, tone: 'swing' },
    { key: 'swing-low', label: '安値', value: swingLow.value, priority: 7, tone: 'swing' },
  ], y);
  const strongest = projection.directionProbabilities
    ? (Object.entries(projection.directionProbabilities)
      .sort((a, b) => b[1] - a[1])[0]?.[0] ?? '') : '';
  return <div className="at-projection" role="link" tabIndex={0} onClick={onActivate}
    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onActivate(); }}>
    <div className="at-proj-heading"><b>{projection.label}｜{projection.horizon}見通し</b>
      <span>{projection.proxyFor ? 'ETF PROXY · ' : ''}{shortDate(projection.asOf)} {quoteDisplayLabel(projection.quoteState)}・{projection.timeframeLabel} · 過去{projection.history.length}日｜予測{projection.horizonDays}日</span></div>
    <svg viewBox="0 0 720 330" role="img" aria-label={`${projection.label} 実績と${projection.horizonDays}営業日シナリオ`}>
      <defs><linearGradient id="at-band" x1="0" x2="1"><stop offset="0" stopColor="#facc15" stopOpacity=".1"/><stop offset="1" stopColor="#facc15" stopOpacity=".35"/></linearGradient></defs>
      {[.25, .5, .75].map((ratio) => <line key={ratio} x1="28" x2="570"
        y1={16 + ratio * 292} y2={16 + ratio * 292} className="at-proj-grid" />)}
      {projection.support && <rect x="28" width="542" y={y(projection.support.high)}
        height={Math.max(1, y(projection.support.low) - y(projection.support.high))} className="at-proj-support" />}
      {projection.resistance && <rect x="28" width="542" y={y(projection.resistance.high)}
        height={Math.max(1, y(projection.resistance.low) - y(projection.resistance.high))} className="at-proj-resistance" />}
      <line x1="28" x2={forecastX} y1={y(projection.upside)} y2={y(projection.upside)} className="at-proj-up" />
      <line x1="28" x2={forecastX} y1={y(projection.downside)} y2={y(projection.downside)} className="at-proj-down" />
      <line x1={currentX} x2={forecastX} y1={y(projection.invalidation)} y2={y(projection.invalidation)} className="at-proj-inv" />
      <path d={`M${currentX},${y(projection.current)} L${forecastX},${y(projection.baseHigh)} L${forecastX},${y(projection.baseLow)} Z`} fill="url(#at-band)" />
      <path d={path} className="at-proj-actual" />
      {projection.history.map((point, index) => <circle key={`tip:${point.date}`}
        cx={x(index)} cy={y(point.value)} r="7" className="at-proj-tooltip-point">
        <title>{`${point.date} 実績 · 終値 ${formatInstrumentPrice(point.value, projection.instrumentId)} · 高値 ${formatInstrumentPrice(point.high, projection.instrumentId)} · 安値 ${formatInstrumentPrice(point.low, projection.instrumentId)} · 出来高 ${point.volume == null ? '未取得' : point.volume.toLocaleString('ja-JP')}`}</title>
      </circle>)}
      <line x1={currentX} x2={currentX} y1="10" y2="314" className="at-proj-boundary" />
      <text x={currentX - 8} y="12" textAnchor="end" className="at-proj-side-label">実績</text>
      <text x={currentX + 8} y="12" className="at-proj-side-label">予測</text>
      <circle cx={currentX} cy={y(projection.current)} r="4.2" className="at-proj-current" />
      <path d={`M${currentX},${y(projection.current)} C${currentX + 28},${y(projection.current)} ${forecastX - 24},${y(median)} ${forecastX},${y(median)}`} className="at-proj-base" />
      <circle cx={forecastX} cy={y(median)} r="7" className="at-proj-tooltip-point">
        <title>{`${projection.horizonDays}営業日先 予測 · 本線 ${formatInstrumentPrice(projection.baseLow, projection.instrumentId)}–${formatInstrumentPrice(projection.baseHigh, projection.instrumentId)}`}</title>
      </circle>
      {projection.eventMarkers.map((marker) => { const mx = markerX(marker.date); return mx == null ? null
        : <g key={marker.id}><line x1={mx} x2={mx} y1="16" y2="308" className="at-proj-event-line" />
          <circle cx={mx} cy="20" r="3" className="at-proj-event" /></g>; })}
      {projection.turningPointMarkers.map((point) => { const mx = markerX(point.date); return mx == null ? null
        : <path key={point.id} d={`M${mx - 5},300 L${mx},288 L${mx + 5},300 Z`} className="at-proj-turn" />; })}
      <circle cx={x(projection.history.indexOf(swingHigh))} cy={y(swingHigh.value)} r="3" className="at-proj-swing" />
      <circle cx={x(projection.history.indexOf(swingLow))} cy={y(swingLow.value)} r="3" className="at-proj-swing" />
      {priceLabels.map((row) => <g key={row.key} className={`at-proj-chip is-${row.tone}`}>
        <line x1="570" x2="588" y1={y(row.value)} y2={row.y} />
        <rect x="588" y={row.y - 8} width="126" height="16" rx="3" />
        <text x="594" y={row.y + 4}>{row.label} {formatInstrumentPrice(row.value, projection.instrumentId)}</text>
      </g>)}
    </svg>
    <div className="at-proj-levels"><span className="up">上限 <b>{formatInstrumentPrice(projection.upside, projection.instrumentId)}</b></span>
      <span>本線 <b>{formatInstrumentPrice(projection.baseLow, projection.instrumentId)}–{formatInstrumentPrice(projection.baseHigh, projection.instrumentId)}</b></span>
      <span className="down">下限 <b>{formatInstrumentPrice(projection.downside, projection.instrumentId)}</b></span>
      <span className="invalid">無効 <b>{formatInstrumentPrice(projection.invalidation, projection.instrumentId)}</b></span></div>
    {projection.directionProbabilities ? <div className="at-proj-prob"><span>{projection.horizonDays}D 終値方向</span>
      {(['UP', 'RANGE', 'DOWN'] as const).map((key) => <span key={key}
        className={`${key.toLowerCase()} ${strongest === key ? 'is-max' : ''}`}>{key} <b>{projection.directionProbabilities![key]}%</b></span>)}
      <em>実効n={projection.effectiveSampleCount} · BSS {projection.brierSkill?.toFixed(3)}</em></div>
      : <div className="at-proj-prob is-suppressed"><b>確率は非表示</b>
        <span>理由：{probabilityReasonJa(projection.probabilityEligibility.reasonCodes)} · 実効n={projection.effectiveSampleCount}</span></div>}
    <div className="at-proj-meta"><b>{projection.directionLabel}</b><span>{projection.horizon} · 反応{projection.reactionDelay == null ? '—' : `${projection.reactionDelay.toFixed(1)}日`}</span><small>タップでMarket Context</small></div>
  </div>;
};

export const ArgusTodayPanel: React.FC<Props> = ({ view, onMode, onInstrument, onNavigate, onOpenAsset, aiButton }) => {
  const [detail, setDetail] = React.useState(false);
  const [horizon, setHorizon] = React.useState<'1D' | '5D' | '20D'>('5D');
  const projection = view.projectionsByHorizon[horizon] ?? view.projection;
  const currentSignal = SIGNAL_ORDER.find((code) => SIGNALS[code].level === view.actionScore);
  React.useEffect(() => {
    try {
      sessionStorage.setItem('argus.todayDecisionMirror', JSON.stringify({
        schemaVersion: 'argus-today-decision-mirror-v1',
        market: view.selectedMarket, selectionMode: view.selectionMode,
        finalAction: view.finalAction, actionScore: view.actionScore,
        symbol: view.selectedInstrument?.symbol ?? projection?.symbol ?? null,
        instrumentId: projection?.instrumentId ?? null,
        horizon: projection?.horizonDays ?? 5,
        updatedAt: new Date().toISOString(),
      }));
    } catch { /* navigation mirror is best effort and contains no owner data */ }
  }, [projection, view.actionScore, view.finalAction, view.selectedInstrument,
    view.selectedMarket, view.selectionMode]);
  return <div className="argus-today">
    <section className="at-lamps" aria-label="市場セッション">
      {view.sessionLamps.map((lamp) => <span key={lamp.key} className={`is-${lamp.tone}`}>
        <i aria-hidden />{lamp.label}
      </span>)}
    </section>

    <section className="at-event card" aria-label="NEXT EVENT">
      <div className="at-head"><b>NEXT EVENT</b>{view.nextEvent && <span>{view.nextEvent.impact.toUpperCase()}</span>}</div>
      {view.nextEvent ? <button type="button" onClick={() => onNavigate('regime')}>
        <strong>{view.nextEvent.code}</strong><time>{formatEventTime(view.nextEvent.at)}</time>
        {view.nextEvent.descriptionJa && <small>{view.nextEvent.descriptionJa.slice(0, 32)}</small>}
      </button> : <p className="at-quiet">直近の重要イベントなし</p>}
      <div className="at-coming"><b>COMING 30D</b>
        {view.comingEvents.length ? view.comingEvents.map((event) => <span key={event.id}>{event.code} {formatEventTime(event.at).split(' ')[0]}</span>) : <span>予定なし</span>}
      </div>
    </section>

    <article className={`at-decision card is-${view.finalAction.toLowerCase()}`} aria-label="A.R.G.U.S. Engine 最終判断">
      <div className="at-mode" role="group" aria-label="表示市場">
        {(['AUTO', 'JP', 'US'] as MarketSelectionMode[]).map((mode) => <button type="button" key={mode}
          aria-pressed={view.selectionMode === mode} className={view.selectionMode === mode ? 'active' : ''}
          onClick={() => onMode(mode)}>{mode}</button>)}
        <span>SELECTED {view.selectedMarket}</span>{view.globalRisk && <em>GLOBAL {view.globalRisk}</em>}
      </div>
      {view.indexMoves.length > 0 && <div className="at-index-strip" aria-label="主要指数データ">
        {view.indexMoves.map((move) => <button type="button" key={move.id}
          aria-pressed={move.symbol === view.selectedInstrument?.symbol}
          onClick={() => move.symbol && move.market && onInstrument(move.market, move.symbol)}
          className={`is-${moveTone(move.value, move.previous)} ${move.symbol === view.selectedInstrument?.symbol ? 'is-selected' : ''}`}>
          <span title={move.label}>{move.label}</span><b>{fmtMove(move.value, move.suffix)}</b>
          <Sparkline values={(move.history ?? []).map((point) => point.value)} />
          <em>{move.directionLabel ?? ''} · {move.status ?? 'close'} {shortDate(move.asOf)}</em></button>)}
      </div>}
      <div className="at-call">
        <strong style={{ color: ACTION_TONE[view.finalAction] }}>{view.finalAction}</strong>
        <b>{view.actionScore} / 7</b><span>{currentSignal ? SIGNALS[currentSignal].labelJa : ''}</span>
      </div>
      <div className="at-meter" aria-label={`7段階 ${view.actionScore}`}>
        {SIGNAL_ORDER.map((code) => <i key={code} className={SIGNALS[code].level === view.actionScore ? 'active' : ''}><span>{SIGNALS[code].level}</span></i>)}
      </div>
      <div className="at-horizon" role="group" aria-label="予測期間">{(['1D', '5D', '20D'] as const).map((value) =>
        <button type="button" key={value} aria-pressed={horizon === value}
          onClick={() => setHorizon(value)}>{value}</button>)}</div>
      {projection ? <ProjectionChart projection={projection} onActivate={() => {
        try { sessionStorage.setItem('argus.replayContext', JSON.stringify({ route: 'market-context',
          schemaVersion: 'argus-replay-deeplink-v1',
          selectedTab: 'OVERVIEW', market: view.selectedMarket,
          instrumentId: projection.instrumentId, symbol: projection.symbol,
          horizon: projection.horizonDays, forecastId: projection.forecastId,
          finalAction: view.finalAction, actionScore: view.actionScore,
          forecastAsOf: projection.asOf,
          directionProbabilities: projection.directionProbabilities,
          priceLevels: { current: projection.current, upper: projection.upside,
            baseLow: projection.baseLow, baseHigh: projection.baseHigh,
            lower: projection.downside, invalidation: projection.invalidation },
          brierSkill: projection.brierSkill,
          effectiveSample: projection.effectiveSampleCount,
          signalEpisodeIds: projection.signalEpisodeIds,
          supportResistanceIds: projection.supportResistanceIds,
          eventIds: projection.eventIds })); } catch { /* best effort */ }
        onNavigate('regime');
      }} /> : <div className="at-projection-missing">実測OHLCV確認待ち</div>}
      <div className="at-kpis"><span>確度 <b>{view.projection?.confidenceLabel ?? (view.confidence == null ? '未算出' : Math.round(view.confidence * 100))}</b></span>
        <span>DATA <b className={`is-${view.dataStatus.tone}`}>● {view.dataStatus.label}</b></span></div>
      {view.factors.length > 0 && <div className="at-factors">{view.factors.map((factor) =>
        <span key={factor.key} className={factor.state === '↑' || factor.state === 'LOW' ? 'is-positive'
          : factor.state === '↓' || factor.state === 'HIGH' ? 'is-negative' : 'is-neutral'}>{factor.key} <b>{factor.state}</b></span>)}</div>}
      {view.failedRallyState && view.failedRallyState.state !== 'NONE' && <div className="at-failed-rally">
        <b>上昇失速パターン　{view.failedRallyState.state === 'CONFIRMED' ? '観測済み' : '候補'}</b>
        <span>将来リターンのSkill未検証</span>
      </div>}
      <div className="at-perms"><span>新規 <b>{mark(view.permissions.newEntry)}</b></span><span>買増 <b>{mark(view.permissions.add)}</b></span><span>保有 <b>{mark(view.permissions.hold)}</b></span></div>
      {(view.conciseAction || view.conciseAvoid) && <div className="at-concise">
        {view.conciseAction && <span><b>やる</b>{view.conciseAction}</span>}
        {view.conciseAvoid && <span><b>避ける</b>{view.conciseAvoid}</span>}
      </div>}
      <button className="at-detail-toggle" type="button" aria-expanded={detail} onClick={() => setDetail((v) => !v)}>
        {detail ? '詳細を閉じる' : '判断の根拠・システム詳細'}
      </button>
      {detail && <div className="at-details">
        <div><b>METHOD</b><span>{view.decisions[view.selectedMarket].methodVersion}</span></div>
        <div><b>CALCULATED</b><span>{view.decisions[view.selectedMarket].calculatedAt}</span></div>
        <div><b>DATA QUALITY</b><span>{view.dataStatus.label}</span></div>
        <div><b>BACKUP</b><span>{view.systemStatus.backup}</span></div>
        <div><b>RULE</b><span>{view.systemStatus.rule}</span></div>
        <div><b>SOURCE</b><span>{[...new Set(view.factors.map((factor) => factor.source).filter(Boolean))].join(' / ') || '—'}</span></div>
        {projection && <><div><b>PROJECTION</b><span>{projection.methodLabel}</span></div>
          <div><b>REPLAY</b><span>類似{projection.rawSampleCount} · episode {projection.episodeCount} · 実効{projection.effectiveSampleCount}</span></div>
          <div><b>CALIBRATION</b><span>{projection.calibrationStatus}
            {projection.modelBrier == null ? '' : ` · Brier ${projection.modelBrier.toFixed(3)}`}
            {projection.brierSkill == null ? ' · Skillなし/基準予測以下' : ` · BSS ${projection.brierSkill.toFixed(3)}`}</span></div>
          <div><b>EXPECTED 5D</b><span>{projection.expectedValue?.expectedReturn == null ? '未算出'
            : `EV ${(projection.expectedValue.expectedReturn * 100).toFixed(2)}% · q10 ${((projection.expectedValue.q10 ?? 0) * 100).toFixed(2)}% · R/R ${projection.expectedValue.rewardRisk?.toFixed(2) ?? '—'}`}</span></div>
          <div><b>INSTRUMENT</b><span>{projection.assetType}{projection.proxyFor ? ` · ETF PROXY for ${projection.proxyFor}` : ''} · {projection.licenseStatus}</span></div></>}
        {view.decisions[view.selectedMarket].evidence.map((line, index) => <p key={`${index}:${line}`}>{line}</p>)}
        <div className="at-detail-actions">{aiButton}<button type="button" onClick={() => onNavigate('quality')}>Data Quality</button><button type="button" onClick={() => onNavigate('backup')}>Backup</button></div>
      </div>}
    </article>

    {view.macroMoves.length > 0 && <Compact title="MACRO"><div className="at-rows">
      {view.macroMoves.map((move) => <div key={move.id}><b>{move.label}</b><span>{fmtMove(move.value, move.suffix)}</span><em>{move.directionLabel ?? '→'} · {shortDate(move.asOf)}</em></div>)}
    </div></Compact>}

    {view.positioning.length > 0 && <Compact title={`${view.selectedMarket} 需給`} className="at-positioning"
      onActivate={() => {
        try { sessionStorage.setItem('argus.replayContext', JSON.stringify({
          schemaVersion: 'argus-replay-deeplink-v1', route: 'market-context',
          selectedTab: 'LEDGER', market: view.selectedMarket,
          instrumentId: projection?.instrumentId,
          symbol: projection?.symbol, horizon: projection?.horizonDays ?? 5,
          forecastId: projection?.forecastId,
          finalAction: view.finalAction, actionScore: view.actionScore,
          forecastAsOf: projection?.asOf,
          directionProbabilities: projection?.directionProbabilities,
          priceLevels: projection ? { current: projection.current, upper: projection.upside,
            baseLow: projection.baseLow, baseHigh: projection.baseHigh,
            lower: projection.downside, invalidation: projection.invalidation } : undefined,
          brierSkill: projection?.brierSkill,
          effectiveSample: projection?.effectiveSampleCount,
        })); } catch { /* best effort */ }
        try { sessionStorage.setItem('argus.scrollTo', 'market-ledger'); } catch { /* legacy deep-link compatibility */ }
        onNavigate('regime');
      }}><div className="at-position-rows">
      {view.positioning.map((row) => <div key={row.key} className={`is-${row.tone ?? 'neutral'}`}>
        <b>{row.label}</b><span>{row.value}</span>{row.detail && <em>{row.detail}</em>}</div>)}
    </div></Compact>}

    <Compact title="重大ニュース" className={`at-news-card ${view.newsCardState.status !== 'live' ? 'is-stale' : ''}`}>
      {view.news.length ? <div className="at-news">
      {view.news.map((row) => <a key={row.id} href={row.url} target="_blank" rel="noreferrer"><b>{row.titleJa}</b><span>{row.source}</span></a>)}
      </div> : <div className="at-news-zero"><b>{view.newsCardState.status === 'live' ? '現在なし' : 'ニュース確認要'}</b>
        <span>最終確認 {view.newsCardState.lastChecked ? new Date(view.newsCardState.lastChecked).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '—'}</span></div>}
    </Compact>

    {view.holdingsReview.length > 0 && <Compact title="保有確認"><div className="at-rows">
      {view.holdingsReview.map((row) => <button type="button" key={row.symbol} onClick={() => onOpenAsset?.(row.symbol)}>
        <b>{row.symbol}</b><span>{row.reasonJa.slice(0, 24)}</span><em>{row.statusJa}</em>
      </button>)}
    </div></Compact>}

    {view.reviewSummary && <section className="at-review card">
      <div><b>前回 {view.reviewSummary.action}</b><span>{view.reviewSummary.marketLabel} · {view.reviewSummary.horizon}</span></div>
      {view.reviewSummary.status === 'matured' && view.reviewSummary.returnPct != null
        ? <strong>実績 {view.reviewSummary.returnPct > 0 ? '+' : ''}{view.reviewSummary.returnPct.toFixed(2)}% · 評価：{view.reviewSummary.evaluationJa}</strong>
        : view.reviewSummary.status === 'missing_price' ? <strong>価格取得待ち</strong>
          : <strong>{view.reviewSummary.horizon}・答え合わせ待ち</strong>}
    </section>}
  </div>;
};

const Compact: React.FC<{ title: string; children: React.ReactNode; className?: string;
  onActivate?: () => void }> = ({ title, children, className = '', onActivate }) =>
  <section className={`at-compact card ${className}`} role={onActivate ? 'link' : undefined}
    tabIndex={onActivate ? 0 : undefined} onClick={onActivate}
    onKeyDown={onActivate ? (event) => { if (event.key === 'Enter' || event.key === ' ') onActivate(); } : undefined}>
    <h3>{title}{onActivate && <span aria-hidden>↗</span>}</h3>{children}</section>;

export default ArgusTodayPanel;

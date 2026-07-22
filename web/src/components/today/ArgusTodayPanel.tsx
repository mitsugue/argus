import React from 'react';
import type { ArgusTodayView, MarketSelectionMode, TodayProjection } from '../../domain/argusTodayView';
import { formatEventTime } from '../../domain/argusTodayView';
import { SIGNAL_ORDER, SIGNALS } from '../../domain/actionLevel';
import type { RouteKey } from '../NavRail';
import './ArgusToday.css';

interface Props {
  view: ArgusTodayView;
  onMode: (mode: MarketSelectionMode) => void;
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

const Sparkline: React.FC<{ values: number[] }> = ({ values }) => {
  if (values.length < 2) return null;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const points = values.map((value, index) => `${index / (values.length - 1) * 42},${12 - (value - lo) / span * 10}`).join(' ');
  return <svg className="at-spark" viewBox="0 0 42 14" aria-hidden><polyline points={points} /></svg>;
};

const ProjectionChart: React.FC<{ projection: TodayProjection }> = ({ projection }) => {
  const all = projection.history.map((point) => point.value).concat([
    projection.baseLow, projection.baseHigh, projection.upside, projection.downside, projection.invalidation,
  ]);
  const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  const x = (index: number) => 8 + index / Math.max(1, projection.history.length - 1) * 66;
  const y = (value: number) => 6 + (hi - value) / span * 70;
  const path = projection.history.map((point, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(' ');
  return <div className="at-projection">
    <div className="at-proj-heading"><b>{projection.label}｜{projection.horizon}見通し</b>
      <span>{shortDate(projection.asOf)}終値・{projection.timeframeLabel} · 過去{projection.history.length}日｜予測5日 · {projection.quoteState}</span></div>
    <svg viewBox="0 0 100 82" role="img" aria-label={`${projection.label} 実績と5営業日シナリオ`}>
      <defs><linearGradient id="at-band" x1="0" x2="1"><stop offset="0" stopColor="#facc15" stopOpacity=".1"/><stop offset="1" stopColor="#facc15" stopOpacity=".35"/></linearGradient></defs>
      <line x1="5" x2="97" y1={y(projection.upside)} y2={y(projection.upside)} className="at-proj-up" />
      <line x1="5" x2="97" y1={y(projection.downside)} y2={y(projection.downside)} className="at-proj-down" />
      <line x1="72" x2="97" y1={y(projection.invalidation)} y2={y(projection.invalidation)} className="at-proj-inv" />
      <rect x="72" width="25" y={y(projection.baseHigh)} height={Math.max(2, y(projection.baseLow) - y(projection.baseHigh))} fill="url(#at-band)" />
      <path d={path} className="at-proj-actual" />
      <line x1="74" x2="74" y1="3" y2="78" className="at-proj-boundary" />
      <circle cx="74" cy={y(projection.current)} r="2.1" className="at-proj-current" />
      <line x1="74" x2="97" y1={y(projection.current)} y2={y((projection.baseLow + projection.baseHigh) / 2)} className="at-proj-base" />
    </svg>
    <div className="at-proj-levels"><span className="up">上 {fmt(projection.upside)}</span><span>本線 {fmt(projection.baseLow)}–{fmt(projection.baseHigh)}</span><span className="down">下 {fmt(projection.downside)}</span></div>
    <div className="at-proj-meta"><b>{projection.directionLabel}</b><span>{projection.horizon} · 確度 {projection.confidenceLabel}</span><small>無効 {fmt(projection.invalidation)} · 確率は未校正</small></div>
  </div>;
};

export const ArgusTodayPanel: React.FC<Props> = ({ view, onMode, onNavigate, onOpenAsset, aiButton }) => {
  const [detail, setDetail] = React.useState(false);
  const currentSignal = SIGNAL_ORDER.find((code) => SIGNALS[code].level === view.actionScore);
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
      {view.indexMoves.length > 0 && <div className="at-index-strip" aria-label="主要指数現在値">
        {view.indexMoves.map((move) => <div key={move.id} className={`is-${moveTone(move.value, move.previous)}`}>
          <span title={move.label}>{move.label}</span><b>{fmtMove(move.value, move.suffix)}</b>
          <Sparkline values={(move.history ?? []).map((point) => point.value)} />
          <em>{move.directionLabel ?? ''} · {move.status ?? 'close'} {shortDate(move.asOf)}</em></div>)}
      </div>}
      <div className="at-call">
        <strong style={{ color: ACTION_TONE[view.finalAction] }}>{view.finalAction}</strong>
        <b>{view.actionScore} / 7</b><span>{currentSignal ? SIGNALS[currentSignal].labelJa : ''}</span>
      </div>
      <div className="at-meter" aria-label={`7段階 ${view.actionScore}`}>
        {SIGNAL_ORDER.map((code) => <i key={code} className={SIGNALS[code].level === view.actionScore ? 'active' : ''}><span>{SIGNALS[code].level}</span></i>)}
      </div>
      {view.projection ? <ProjectionChart projection={view.projection} /> : <div className="at-projection-missing">予測図は実測OHLCV・ATR確認待ち</div>}
      <div className="at-kpis"><span>確度 <b>{view.projection?.confidenceLabel ?? (view.confidence == null ? '未算出' : Math.round(view.confidence * 100))}</b></span>
        <span>DATA <b className={`is-${view.dataStatus.tone}`}>● {view.dataStatus.label}</b></span></div>
      {view.factors.length > 0 && <div className="at-factors">{view.factors.map((factor) =>
        <span key={factor.key} className={factor.state === '↑' || factor.state === 'LOW' ? 'is-positive'
          : factor.state === '↓' || factor.state === 'HIGH' ? 'is-negative' : 'is-neutral'}>{factor.key} <b>{factor.state}</b></span>)}</div>}
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
        {view.projection && <div><b>PROJECTION</b><span>{view.projection.methodLabel}</span></div>}
        {view.decisions[view.selectedMarket].evidence.map((line, index) => <p key={`${index}:${line}`}>{line}</p>)}
        <div className="at-detail-actions">{aiButton}<button type="button" onClick={() => onNavigate('quality')}>Data Quality</button><button type="button" onClick={() => onNavigate('backup')}>Backup</button></div>
      </div>}
    </article>

    {view.macroMoves.length > 0 && <Compact title="MACRO"><div className="at-rows">
      {view.macroMoves.map((move) => <div key={move.id}><b>{move.label}</b><span>{fmtMove(move.value, move.suffix)}</span><em>{move.directionLabel ?? '→'} · {shortDate(move.asOf)}</em></div>)}
    </div></Compact>}

    {view.positioning.length > 0 && <Compact title={`${view.selectedMarket} 需給`} className="at-positioning"
      onActivate={view.selectedMarket === 'JP' ? () => {
        try { sessionStorage.setItem('argus.scrollTo', 'market-ledger'); } catch { /* best effort */ }
        onNavigate('regime');
      } : undefined}><div className="at-position-rows">
      {view.positioning.map((row) => <div key={row.key} className={`is-${row.tone ?? 'neutral'}`}>
        <b>{row.label}</b><span>{row.value}</span>{row.detail && <em>{row.detail}</em>}</div>)}
    </div></Compact>}

    {view.news.length ? <Compact title="重大ニュース"><div className="at-news">
      {view.news.map((row) => <a key={row.id} href={row.url} target="_blank" rel="noreferrer"><b>{row.titleJa}</b><span>{row.source}</span></a>)}
    </div></Compact> : <div className="at-news-zero"><b>重大ニュース</b><span>0</span></div>}

    {view.holdingsReview.length > 0 && <Compact title="保有確認"><div className="at-rows">
      {view.holdingsReview.map((row) => <button type="button" key={row.symbol} onClick={() => onOpenAsset?.(row.symbol)}>
        <b>{row.symbol}</b><span>{row.reasonJa.slice(0, 24)}</span><em>{row.statusJa}</em>
      </button>)}
    </div></Compact>}

    {view.reviewSummary && <section className="at-review card">
      <div><b>前回 {view.reviewSummary.action}</b><span>{view.reviewSummary.marketLabel} · {view.reviewSummary.horizon}</span></div>
      {view.reviewSummary.matured && view.reviewSummary.returnPct != null
        ? <strong>実績 {view.reviewSummary.returnPct > 0 ? '+' : ''}{view.reviewSummary.returnPct.toFixed(2)}% · 評価：{view.reviewSummary.evaluationJa}</strong>
        : <strong>答え合わせ待ち</strong>}
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

import React from 'react';
import type { ArgusTodayView, MarketSelectionMode } from '../../domain/argusTodayView';
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
const fmtMove = (v: number, suffix = '') => `${v.toFixed(suffix === '%' ? 2 : 2)}${suffix}`;

export const ArgusTodayPanel: React.FC<Props> = ({ view, onMode, onNavigate, onOpenAsset, aiButton }) => {
  const [detail, setDetail] = React.useState(false);
  return <div className="argus-today">
    <section className="at-lamps" aria-label="市場セッション">
      {view.sessionLamps.map((lamp) => <span key={lamp.key} className={lamp.active ? 'is-on' : 'is-off'}>
        <i aria-hidden />{lamp.label}
      </span>)}
    </section>

    <section className="at-event card" aria-label="NEXT EVENT">
      <div className="at-head"><b>NEXT EVENT</b>{view.nextEvent && <span>{view.nextEvent.impact.toUpperCase()}</span>}</div>
      {view.nextEvent ? <button type="button" onClick={() => onNavigate('regime')}>
        <strong>{view.nextEvent.code}</strong><time>{formatEventTime(view.nextEvent.at)}</time>
        {view.nextEvent.descriptionJa && <small>{view.nextEvent.descriptionJa.slice(0, 32)}</small>}
      </button> : <p className="at-quiet">直近の重要イベントなし</p>}
      {view.comingEvents.length > 0 && <div className="at-coming"><b>COMING 30D</b>
        {view.comingEvents.map((event) => <span key={event.id}>{event.code} {formatEventTime(event.at).split(' ')[0]}</span>)}
      </div>}
    </section>

    <article className="at-decision card" aria-label="A.R.G.U.S. Engine 最終判断">
      <div className="at-mode" role="group" aria-label="表示市場">
        {(['AUTO', 'JP', 'US'] as MarketSelectionMode[]).map((mode) => <button type="button" key={mode}
          aria-pressed={view.selectionMode === mode} className={view.selectionMode === mode ? 'active' : ''}
          onClick={() => onMode(mode)}>{mode}</button>)}
        <span>NOW {view.selectedMarket}</span>{view.globalRisk && <em>GLOBAL {view.globalRisk}</em>}
      </div>
      <div className="at-call">
        <strong style={{ color: ACTION_TONE[view.finalAction] }}>{view.finalAction}</strong>
        <b>{view.actionScore} / 7</b>
      </div>
      <div className="at-meter" aria-label={`7段階 ${view.actionScore}`}>
        {SIGNAL_ORDER.map((code) => <i key={code} className={SIGNALS[code].level === view.actionScore ? 'active' : ''} />)}
      </div>
      {(view.marketPrice != null || view.range || view.invalidation != null) && <div className="at-price">
        {view.marketPrice != null && <span>価格 <b>{view.marketPrice.toLocaleString('ja-JP')}</b></span>}
        {view.range && <span>本線 <b>{view.range.low.toLocaleString('ja-JP')}–{view.range.high.toLocaleString('ja-JP')}</b></span>}
        {view.invalidation != null && <span>無効 <b>{view.invalidation.toLocaleString('ja-JP')}</b></span>}
      </div>}
      <div className="at-kpis"><span>確度 <b>{view.confidence == null ? '—' : Math.round(view.confidence * 100)}</b></span>
        <span>DATA <b className={`is-${view.dataStatus.tone}`}>● {view.dataStatus.label}</b></span></div>
      {view.factors.length > 0 && <div className="at-factors">{view.factors.map((factor) =>
        <span key={factor.key}>{factor.key} <b>{factor.state}</b></span>)}</div>}
      <div className="at-perms"><span>新規 {mark(view.permissions.newEntry)}</span><span>買増 {mark(view.permissions.add)}</span><span>保有 {mark(view.permissions.hold)}</span></div>
      {(view.conciseAction || view.conciseAvoid) && <div className="at-concise">
        {view.conciseAction && <span><b>やる</b>{view.conciseAction}</span>}
        {view.conciseAvoid && <span><b>避ける</b>{view.conciseAvoid}</span>}
      </div>}
      <button className="at-detail-toggle" type="button" aria-expanded={detail} onClick={() => setDetail((v) => !v)}>
        {detail ? '詳細を閉じる' : '判断の詳細'}
      </button>
      {detail && <div className="at-details">
        <div><b>A.R.G.U.S. Engine</b><span>{view.decisions[view.selectedMarket].methodVersion}</span></div>
        <div><b>INTERNAL ACTION</b><span>{view.decisions[view.selectedMarket].internalAction}</span></div>
        <div><b>CALCULATED</b><span>{view.decisions[view.selectedMarket].calculatedAt}</span></div>
        <div><b>MARKET MEMORY</b><span>{view.decisions[view.selectedMarket].evidence.length ? '参照済み' : '—'}</span></div>
        <div><b>SIMILAR SCENES</b><span>—</span></div>
        <div><b>EVENT OVERLAY</b><span>{view.nextEvent?.code ?? '—'}</span></div>
        <div><b>CLOSING WINDOW</b><span>{view.factors.find((factor) => factor.key === 'CLOSE')?.state ?? '—'}</span></div>
        <div><b>OWNER POLICY</b><span>強気方向への上書きなし</span></div>
        <div><b>DATA QUALITY</b><span>{view.dataStatus.label}</span></div>
        <div><b>BACKUP</b><span>{view.systemStatus.backup}</span></div>
        <div><b>RULE</b><span>{view.systemStatus.rule}</span></div>
        <div><b>SOURCE</b><span>{[...new Set(view.factors.map((factor) => factor.source).filter(Boolean))].join(' / ') || '—'}</span></div>
        {view.decisions[view.selectedMarket].evidence.map((line, index) => <p key={`${index}:${line}`}>{line}</p>)}
      </div>}
    </article>

    {view.marketMoves.length > 0 && <Compact title="MARKET"><div className="at-rows">
      {view.marketMoves.map((move) => <div key={move.id}><b>{move.label}</b><span>{fmtMove(move.value, move.suffix)}</span><em>{move.directionLabel ?? '→'}</em></div>)}
    </div></Compact>}

    {view.positioning.length > 0 && <Compact title="需給"><div className="at-tags">
      {view.positioning.map((row) => <span key={row.key}>{row.label} <b>{row.value}</b></span>)}
    </div></Compact>}

    {view.attention.length > 0 && <Compact title={`ATTENTION ${view.attention.length}`}><div className="at-rows">
      {view.attention.map((row) => <div key={row.id}><b>{row.label}</b><span>{row.time ?? ''}</span></div>)}
    </div></Compact>}

    {view.holdingsReview.length > 0 && <Compact title="保有確認"><div className="at-rows">
      {view.holdingsReview.map((row) => <button type="button" key={row.symbol} onClick={() => onOpenAsset?.(row.symbol)}>
        <b>{row.symbol}</b><span>{row.reasonJa.slice(0, 20)}</span><em>{row.statusJa}</em>
      </button>)}
    </div></Compact>}

    {view.portfolioConcentration && <button type="button" className="at-line card" onClick={() => onNavigate('core')}>
      <b>集中度 {view.portfolioConcentration.risk.toUpperCase()}</b>
      {view.portfolioConcentration.topTwoPct != null && <span>上位2銘柄 {Math.round(view.portfolioConcentration.topTwoPct)}%</span>}
    </button>}

    <Compact title="RECOMMEND"><div className="at-rows">
      {view.recommendations.length ? view.recommendations.map((row) => <button type="button" key={row.symbol} onClick={() => onOpenAsset?.(row.symbol)}>
        <b>{row.symbol}</b><span>{row.labelJa}</span></button>) : <p className="at-quiet">本日の新規候補なし</p>}
    </div></Compact>

    <Compact title="FIRE">{view.fireProgress ? <div className="at-fire">
      <b>{Math.round(view.fireProgress.totalJpy / 10_000).toLocaleString('ja-JP')}万円 / 1億円</b>
      <span>{view.fireProgress.firstGoalPct.toFixed(1)}%</span><small>NEXT 4億円</small>
    </div> : <p className="at-quiet">評価額未入力</p>}</Compact>

    {view.reviewSummary && <button type="button" className="at-line card" onClick={() => onNavigate('core')}>
      <b>前回判断</b><span>結果 {view.reviewSummary.result} ・ 判断品質 {view.reviewSummary.quality}</span>
    </button>}

    <div className="at-actions">{aiButton}
      <button type="button" onClick={() => onNavigate('quality')}>Data Quality</button>
      <button type="button" onClick={() => onNavigate('backup')}>Backup</button>
    </div>
  </div>;
};

const Compact: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) =>
  <section className="at-compact card"><h3>{title}</h3>{children}</section>;

export default ArgusTodayPanel;

import React from 'react';
import type { ArgusTodayView, MarketSelectionMode, TodayProjection } from '../../domain/argusTodayView';
import { formatEventTime, quoteDisplayLabel } from '../../domain/argusTodayView';
import type { RouteKey } from '../NavRail';
import type { SettingsSection } from '../../navigation';
import { TriangleStepLoader } from '../common/TriangleStepLoader';
import type {
  MarketHorizon, MarketInstrumentMarket, MarketInstrumentSymbol,
} from '../../domain/marketInstruments';
import './ArgusToday.css';

export interface TodayInstrumentState {
  symbol: MarketInstrumentSymbol;
  market: MarketInstrumentMarket;
  shortLabel: string;
  fullLabel: string;
  instrumentType: 'ETF';
  underlying: string;
}

export interface TodayChartLoadState {
  loading: boolean;
  loaderVisible: boolean;
  slowInitial: boolean;
  statusText: string;
  error: string | null;
  snapshotState: string;
  snapshotId: string | null;
  responseSnapshotId: string | null;
  retry: () => void;
}

interface Props {
  view: ArgusTodayView;
  instruments: readonly TodayInstrumentState[];
  selectedSymbol: MarketInstrumentSymbol;
  horizon: MarketHorizon;
  chartLoad: TodayChartLoadState;
  /** Which canonical source currently feeds the visible projection. */
  projectionSource: 'verified-snapshot' | 'headline' | null;
  /** Truthful session/data-freshness note (e.g. EOD prices while JP OPEN). */
  freshnessNoteJa: string | null;
  /** Market-shock materiality view for the Major News surface. */
  shock: {
    status: 'loading' | 'data' | 'error';
    events: Array<{
      eventId: string; eventClass: string;
      severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
      headlineJa: string; whyJa: string;
      crossMarket: { confirmed: boolean; signals: string[] };
      sources: Array<{ name: string; kind: string }>;
      asOf: string | null;
    }>;
  };
  newsIntel: {
    status: 'loading' | 'data' | 'error';
    events: Array<{
      eventId: string; eventType: string;
      severity: 'INFO' | 'WATCH' | 'HIGH' | 'CRITICAL';
      headlineJa: string; whyJa: string; japanImpactJa: string | null;
      confirmationState: 'MARKET_CONFIRMED' | 'MARKET_CONFIRMATION_PENDING';
      marketReadings: Array<{ key: string; labelJa: string;
        value: number | null; change: number | null; unit: string }>;
      source: string; sourceReceivedAt: string | null; backfill: boolean;
    }>;
  };
  onMode: (mode: MarketSelectionMode) => void;
  onInstrument: (market: 'JP' | 'US', symbol: string) => void;
  onHorizon: (horizon: MarketHorizon) => void;
  onNavigate: (key: RouteKey) => void;
  onNavigateToAsset?: (symbol: string, section?: string) => void;
  onNavigateToSettings?: (section: SettingsSection) => void;
  aiButton: React.ReactNode;
}

const ACTION_TONE = {
  BUY: 'var(--value-positive)', HOLD: 'var(--accent)', WAIT: 'var(--amber, #fbbf24)',
  REDUCE: 'var(--event-high)', EXIT: 'var(--value-negative)',
};
const MARKET_STANCE = {
  BUY: 'BUY', HOLD: 'HOLD', WAIT: 'WAIT', REDUCE: 'REDUCE', EXIT: 'EXIT',
};
const SEVEN_SIGN_MEANING: Record<number, string> = {
  1: '強いRisk Off', 2: 'REDUCE寄り', 3: '新規回避', 4: 'WAIT',
  5: '条件付きBUY寄り', 6: 'BUY寄り', 7: '最高クラスBUY期待値',
};
const SEVEN_SIGN_REASON_JA: Record<string, string> = {
  decision_data_gated: '判断データ不足（DATA_GATED）',
  calibration_shadow: '校正シャドー検証中',
  calibration_missing: '校正データ未提供',
  calibration_data_gated: '校正データ不足',
  calibration_non_monotonic: '校正期待値の単調性未達',
  calibration_sample_insufficient: '校正サンプル数不足',
  calibration_not_out_of_sample: 'アウトオブサンプル検証未達',
  calibration_holdout_mutable: 'ホールドアウト不変性未達',
  calibration_artifact_not_verified: '校正アーティファクト未検証',
  reason_unavailable: '理由コード未提供',
};
const fmt = (v: number) => v >= 1000 ? v.toLocaleString('ja-JP', { maximumFractionDigits: 1 }) : v.toFixed(2);
const fmtMove = (v: number, suffix = '') => `${fmt(v)}${suffix}`;
const shortDate = (value?: string | null) => value ? value.slice(5).replace('-', '/') : '';
const zoneLabel = (kind: '支持' | '抵抗', status: string) =>
  `${kind}${status === 'reclaimed' ? '（回復）' : status === 'broken' ? '（突破済み）' : ''}`;

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

const ProjectionChart: React.FC<{
  projection: TodayProjection;
  snapshotId: string | null;
  responseSnapshotId: string | null;
  snapshotState: string;
  revalidationState: string;
  source?: 'verified-snapshot' | 'headline' | null;
  onActivate?: () => void;
}> = ({ projection, snapshotId, responseSnapshotId, snapshotState,
  revalidationState, source, onActivate }) => {
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
  const displayProbabilities = projection.directionProbabilities
    ?? projection.referenceDirectionProbabilities;
  const strongest = displayProbabilities
    ? (Object.entries(displayProbabilities)
      .sort((a, b) => b[1] - a[1])[0]?.[0] ?? '') : '';
  return <div className="at-projection" role={onActivate ? 'link' : undefined}
    data-argus-contract="today-projection-state-v1"
    data-projection-state="available"
    data-projection-source={source ?? undefined}
    data-projection-snapshot-id={snapshotId ?? undefined}
    data-projection-response-snapshot-id={responseSnapshotId ?? undefined}
    data-projection-snapshot-state={snapshotState}
    data-projection-revalidation-state={revalidationState}
    tabIndex={onActivate ? 0 : undefined} onClick={onActivate}
    onKeyDown={onActivate ? (event) => {
      if (event.key === 'Enter' || event.key === ' ') onActivate();
    } : undefined}>
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
    {displayProbabilities ? <div className={`at-proj-prob ${
      projection.directionProbabilities ? 'is-verified' : 'is-reference'}`}>
      <span>{projection.horizonDays}D 終値方向{
        projection.directionProbabilities ? '（検証済み）' : '（参考値・未検証）'}</span>
      {(['UP', 'RANGE', 'DOWN'] as const).map((key) => <span key={key}
        className={`${key.toLowerCase()} ${strongest === key ? 'is-max' : ''}`}>{key} <b>{displayProbabilities[key]}%</b></span>)}
      <em>実効n={projection.effectiveSampleCount} · BSS {
        projection.brierSkill == null ? '—' : projection.brierSkill.toFixed(3)}
        {!projection.directionProbabilities && ` · ${projection.probabilityTruth.uncertaintyJa}`}
      </em></div>
      : <div className="at-proj-prob is-suppressed"><b>確率は非表示</b>
        <span>{projection.probabilityTruth.directionalLeanJa} · 根拠{projection.probabilityTruth.evidenceStrength}
          · 実効n={projection.probabilityTruth.effectiveN ?? projection.effectiveSampleCount}
          · {projection.probabilityTruth.uncertaintyJa} · {projection.probabilityTruth.label}</span></div>}
    <div className="at-proj-meta"><b>{projection.directionLabel}</b><span>{projection.horizon} · 反応{projection.reactionDelay == null ? '—' : `${projection.reactionDelay.toFixed(1)}日`}</span><small>実測と校正済み根拠</small></div>
  </div>;
};

export const ArgusTodayPanel: React.FC<Props> = ({
  view, instruments, selectedSymbol, horizon, chartLoad,
  projectionSource, freshnessNoteJa, shock, newsIntel,
  onMode, onInstrument, onHorizon, onNavigate, onNavigateToAsset, onNavigateToSettings, aiButton,
}) => {
  const projection = view.projectionsByHorizon[`${horizon}D`] ?? view.projection;
  const actionCopy = {
    BUY: '条件内で新規または追加を検討',
    HOLD: '保有を維持し、判断更新条件を待つ',
    WAIT: '今は動かず、必要な正本証拠の更新を待つ',
    REDUCE: '保有リスクを減らす',
    EXIT: '保有の解消を優先する',
  }[view.finalAction];
  const target = view.canonicalDecision.targets[0];
  const invalidation = view.canonicalDecision.invalidation;
  const openEventDetails = () => onNavigate('notifications');
  React.useEffect(() => {
    try {
      sessionStorage.setItem('argus.todayDecisionMirror', JSON.stringify({
        schemaVersion: 'argus-today-decision-mirror-v1',
        market: view.selectedMarket, selectionMode: view.selectionMode,
        finalAction: view.finalAction, actionScore: view.actionScore,
        decisionId: view.canonicalDecision.decisionId,
        authorityPolicyId: view.canonicalDecision.identities.authorityPolicyId,
        sevenSign: view.canonicalDecision.sevenSign,
        symbol: view.selectedInstrument?.symbol ?? projection?.symbol ?? null,
        instrumentId: projection?.instrumentId ?? null,
        horizon: projection?.horizonDays ?? 5,
        updatedAt: new Date().toISOString(),
      }));
    } catch { /* navigation mirror is best effort and contains no owner data */ }
  }, [projection, view.actionScore, view.canonicalDecision, view.finalAction, view.selectedInstrument,
    view.selectedMarket, view.selectionMode]);
  // The verified warm cache remains the visible authority during background
  // revalidation. Publish an accepted response ID only when the rendered
  // snapshot has atomically moved to that exact identity.
  const coherentResponseSnapshotId = chartLoad.responseSnapshotId === chartLoad.snapshotId
    ? chartLoad.responseSnapshotId : null;
  const revalidationState = chartLoad.snapshotState === 'CACHE_READY_REVALIDATING'
    ? chartLoad.snapshotId ? 'background' : 'invalid'
    : chartLoad.snapshotState === 'NO_CACHE_LOADING' ? 'cold-loading'
    : chartLoad.snapshotState === 'CURRENT_READY' ? 'settled'
    : ['ERROR_WITH_CACHE', 'STALE_FALLBACK'].includes(chartLoad.snapshotState)
      ? 'cached-safe' : 'unavailable';
  return <div className="argus-today"
    data-argus-contract="canonical-market-snapshot-v1"
    data-canonical-snapshot-id={chartLoad.snapshotId ?? undefined}
    data-canonical-response-snapshot-id={coherentResponseSnapshotId ?? undefined}
    data-canonical-response-verification={coherentResponseSnapshotId ? 'verified' : 'unverified'}
    data-canonical-snapshot-state={chartLoad.snapshotState}
    data-canonical-verification={chartLoad.snapshotId ? 'verified' : 'unverified'}
    data-canonical-instrument={projection?.symbol ?? selectedSymbol}
    data-canonical-horizon={`${projection?.horizonDays ?? horizon}D`}>
    <article className={`at-decision at-primary-hero card is-${view.finalAction.toLowerCase()}`}
      aria-label="A.R.G.U.S. Primary Action">
      <div className="at-call">
        <small>PRIMARY ACTION · {view.selectedMarket} {view.selectedInstrument?.symbol ?? ''}</small>
        <strong style={{ color: ACTION_TONE[view.finalAction] }}>{MARKET_STANCE[view.finalAction]}</strong>
        <span className={`at-authority is-${view.canonicalDecision.status.toLowerCase()}`}>
          {view.canonicalDecision.status === 'EVALUATED' ? '確認済み' : '判断データ確認中'}</span>
      </div>
      <p className="at-impact-copy">{actionCopy}</p>
      {/* v13.5.2: Seven Sign is COMPACT — one summary line + seven chips,
          with meanings and the exact machine reason codes expanding on tap.
          All truthful canonical states are preserved; while everything is
          DATA_GATED the surface stays two short rows instead of a wall.
          Nothing here is computed client-side — it renders the SDA
          projection. */}
      <details className="at-seven" data-argus-contract="seven-sign-ladder-v1"
        data-seven-status={view.canonicalDecision.sevenSign.status}
        data-seven-level={view.actionScore ?? undefined}>
        <summary aria-label={`Seven Sign ${view.actionScore ?? '未確定'} / 7 · ${view.canonicalDecision.sevenSign.status}`}>
          <small>SEVEN SIGN</small>
          <b>{view.actionScore == null ? '— / 7' : `${view.actionScore} / 7`}</b>
          <span className="at-seven-status">
            {view.actionScore == null ? 'Calibration pending · ' : ''}
            {view.canonicalDecision.sevenSign.status}</span>
          <span className="at-seven-chips" aria-hidden="true">
            {[1, 2, 3, 4, 5, 6, 7].map((level) => <i key={level}
              className={level === view.actionScore ? 'is-current' : ''}
              data-seven-sign-level={level}>{level}</i>)}
          </span>
        </summary>
        <div className="at-seven-detail">
          <ul>
            {[1, 2, 3, 4, 5, 6, 7].map((level) => <li key={level}
              className={level === view.actionScore ? 'is-current' : ''}>
              <b>{level}</b> {SEVEN_SIGN_MEANING[level]}
              {level === view.actionScore && <i> ◀ 現在</i>}
            </li>)}
          </ul>
          {view.actionScore == null && <p className="at-seven-gated">
            現在のレベルは未確定（{view.canonicalDecision.sevenSign.status}）：
            {(view.canonicalDecision.sevenSign.reasonCodes.length
              ? view.canonicalDecision.sevenSign.reasonCodes
              : ['reason_unavailable']).map((code) =>
              SEVEN_SIGN_REASON_JA[code] ?? code).join(' / ')}
          </p>}
          {view.actionScore != null
            && view.canonicalDecision.sevenSign.status !== 'PRODUCTION'
            && <p className="at-seven-gated">
            {view.canonicalDecision.sevenSign.status === 'SHADOW'
              ? '校正はシャドー検証中（本番採用前）'
              : '校正データ不足のため参考レベル'}
            {view.canonicalDecision.sevenSign.reasonCodes.length > 0
              && ` · ${view.canonicalDecision.sevenSign.reasonCodes.map((code) =>
                SEVEN_SIGN_REASON_JA[code] ?? code).join(' / ')}`}
          </p>}
        </div>
      </details>
      <div className="at-action-plan" aria-label="行動条件">
        <div><b>今すること</b><span>{actionCopy}</span></div>
        <div><b>目標</b><span>{target ? `${target.value} ${target.unit}` : '検証済み目標なし'}</span></div>
        <div><b>無効化</b><span>{invalidation ? `${invalidation.value} ${invalidation.unit}` : '検証済み無効化条件なし'}</span></div>
        <div><b>次の確認</b><span>{view.canonicalDecision.nextReviewConditionCodes[0]
          ?? (view.nextEvent ? `${view.nextEvent.code} ${formatEventTime(view.nextEvent.at)}` : '正本証拠の更新')}</span></div>
      </div>
      <div className="at-kpis"><span>確度 <b>{Math.round(view.canonicalDecision.confidence.valueBps / 100)}%</b></span>
        <span>DATA <b className={`is-${view.dataStatus.tone}`}>● {view.dataStatus.label}</b></span></div>
    </article>

    <section className="at-event card" aria-label="NEXT EVENT">
      <div className="at-head"><b>NEXT EVENT</b>{view.nextEvent && <span>{view.nextEvent.impact.toUpperCase()}</span>}</div>
      {view.nextEvent ? <button type="button" onClick={openEventDetails}>
        <strong>{view.nextEvent.code}</strong><time>{formatEventTime(view.nextEvent.at)}</time>
        {view.nextEvent.descriptionJa && <small>{view.nextEvent.descriptionJa.slice(0, 32)}</small>}
      </button> : <p className="at-quiet">直近の重要イベントなし</p>}
      <div className="at-coming"><b>COMING 30D</b>
        {view.comingEvents.length ? view.comingEvents.map((event) => <span key={event.id}>{event.code} {formatEventTime(event.at).split(' ')[0]}</span>) : <span>予定なし</span>}
      </div>
    </section>

    {/* v13.5.0 restoration: the market block — session lamps, the four
        headline charts, and the projection — is the product, so it is always
        visible. Only system/verification detail stays behind the disclosure
        below. */}
    <section className="at-market card" aria-label="市場データ">
      <section className="at-lamps" aria-label="市場セッション">
        {view.sessionLamps.map((lamp) => <span key={lamp.key} className={`is-${lamp.tone}`}>
          <i aria-hidden />{lamp.label}
        </span>)}
      </section>
      <div className="at-mode" role="group" aria-label="表示市場">
        {(['AUTO', 'JP', 'US'] as MarketSelectionMode[]).map((mode) => <button type="button" key={mode}
          aria-pressed={view.selectionMode === mode} className={view.selectionMode === mode ? 'active' : ''}
          onClick={() => onMode(mode)}>{mode}</button>)}
        <span>SELECTED {view.selectedMarket}</span>{view.globalRisk && <em>GLOBAL {view.globalRisk}</em>}
      </div>
      {/* v13.5.1: four lightweight NAME selectors only. All chart, price,
          and probability information lives in the single selected projection
          chart below — no duplicated mini-charts or probability chips. */}
      <div className="at-index-strip at-index-strip--selectors"
        role="group" aria-label="銘柄選択">
        {instruments.map((instrument) => <button type="button"
          key={instrument.symbol}
          data-argus-control="market-instrument"
          data-instrument={instrument.symbol}
          aria-pressed={instrument.symbol === selectedSymbol}
          onClick={() => onInstrument(instrument.market, instrument.symbol)}
          className={instrument.symbol === selectedSymbol ? 'is-selected' : ''}
          title={`${instrument.fullLabel} · underlying ${instrument.underlying}`}>
          <span className="at-index-name">{instrument.shortLabel}</span>
          <small className="at-index-type">{instrument.instrumentType}</small>
        </button>)}
      </div>
      {freshnessNoteJa && <p className="at-freshness-note">{freshnessNoteJa}</p>}
      <div className="at-chart-controls">
        <div className="at-chart-status" data-snapshot-state={chartLoad.snapshotState}
          data-snapshot-id={chartLoad.snapshotId ?? undefined}>
          <span>{chartLoad.statusText}</span>
          {projection && chartLoad.loading && chartLoad.loaderVisible &&
            <TriangleStepLoader compact label="" />}
          {chartLoad.error && <button type="button" onClick={chartLoad.retry}>再試行</button>}
        </div>
        <div className="at-horizon" role="group" aria-label="予測期間">{([1, 5, 20] as const).map((value) =>
          <button type="button" key={value} aria-pressed={horizon === value}
            data-argus-control="canonical-horizon" data-horizon={`${value}D`}
            onClick={() => onHorizon(value)}>{value}D</button>)}</div>
      </div>
      {projection ? <ProjectionChart projection={projection}
        snapshotId={chartLoad.snapshotId}
        responseSnapshotId={coherentResponseSnapshotId}
        snapshotState={chartLoad.snapshotState}
        revalidationState={revalidationState}
        source={projectionSource} />
        : <div className="at-projection-missing" aria-busy={chartLoad.loading}
          data-argus-contract="today-projection-state-v1"
          data-projection-state="missing"
          data-projection-snapshot-id={chartLoad.snapshotId ?? undefined}
          data-projection-response-snapshot-id={coherentResponseSnapshotId ?? undefined}
          data-projection-snapshot-state={chartLoad.snapshotState}
          data-projection-revalidation-state={revalidationState}>
        {chartLoad.loaderVisible
          ? <TriangleStepLoader label={chartLoad.slowInitial
            ? '初回データを準備中' : 'データ確認中'} />
          : <span aria-hidden className="at-projection-placeholder" />}
        {!chartLoad.loading && <span>{chartLoad.error ? '取得できません' : '実測OHLCV確認待ち'}</span>}
        {chartLoad.error && <button type="button" onClick={chartLoad.retry}>再試行</button>}
      </div>}
      {view.factors.length > 0 && <div className="at-factors">{view.factors.map((factor) =>
        <span key={factor.key} className={factor.state === '↑' || factor.state === 'LOW' ? 'is-positive'
          : factor.state === '↓' || factor.state === 'HIGH' ? 'is-negative' : 'is-neutral'}>{factor.key} <b>{factor.state}</b></span>)}</div>}
      {view.failedRallyState && view.failedRallyState.state !== 'NONE' && <div className="at-failed-rally">
        <b>上昇失速パターン　{view.failedRallyState.state === 'CONFIRMED' ? '観測済み' : '候補'}</b>
        <span>将来リターンのSkill未検証</span>
      </div>}
    </section>

    <details className="at-evidence card">
      <summary>根拠・市場データ・システム情報</summary>
      <div className="at-details">
        <div><b>AUTHORITY</b><span>{view.canonicalDecision.identities.authorityPolicyId ?? 'unavailable'}</span></div>
        <div><b>DECISION ID</b><span>{view.canonicalDecision.decisionId}</span></div>
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
        {projection && <div><b>HISTORY</b><span>{projection.sourceHistoryCount.toLocaleString('ja-JP')}営業日
          {projection.historyStart ? ` · ${projection.historyStart}–${projection.historyEnd ?? '現在'}` : ''}
          {projection.sourceHistoryCount < 2_000 ? ' · 10年未達' : ' · 約10年'}</span></div>}
        {view.canonicalDecision.missingReasonCodes.map((line) => <p key={`missing:${line}`}>MISSING: {line}</p>)}
        {view.canonicalDecision.dissentReasonCodes.map((line) => <p key={`dissent:${line}`}>DISSENT: {line}</p>)}
        <div className="at-detail-actions">{aiButton}<button type="button"
          onClick={() => onNavigateToSettings
            ? onNavigateToSettings('recovery') : onNavigate('settings')}>Settings / Recovery</button></div>
      </div>
    </details>

    {view.holdingsReview.length > 0 && <section className="at-priorities card" aria-label="OWNER PRIORITIES">
      <div className="at-head"><b>OWNER PRIORITIES</b><span>MAX 3</span></div>
      {view.holdingsReview.map((item) => {
        const content = <>
          <span className="at-priority-title">
            <b>{item.symbol}</b><em>{item.isHeld ? '保有' : 'WATCH'}</em>
            <mark className={`is-${(item.impact ?? 'Neutral').toLowerCase()}`}>{item.impact ?? 'Neutral'}</mark>
            <strong>{item.actionJa ?? item.statusJa}</strong>
          </span>
          <span className="at-priority-impact">{item.reasonJa}</span>
          <small>次に確認: {item.checkNextJa || '証拠更新待ち'}
            {item.whatWouldChangeJa ? ` · 判断更新: ${item.whatWouldChangeJa}` : ''}</small>
        </>;
        return onNavigateToAsset ? <button type="button" key={item.symbol}
          onClick={() => onNavigateToAsset(item.symbol)}>{content}</button>
          : <div key={item.symbol}>{content}</div>;
      })}
    </section>}

    {view.macroMoves.length > 0 && <Compact title="MACRO"><div className="at-rows">
      {view.macroMoves.map((move) => <div key={move.id}><b>{move.label}</b><span>{fmtMove(move.value, move.suffix)}</span><em>{move.directionLabel ?? '→'} · {shortDate(move.asOf)}</em></div>)}
    </div></Compact>}

    {view.positioning.length > 0 && <Compact title={`${view.selectedMarket} 需給`}
      className="at-positioning"><div className="at-position-rows">
      {view.positioning.map((row) => <div key={row.key} className={`is-${row.tone ?? 'neutral'}`}>
        <b>{row.label}</b><span>{row.value}</span>{row.detail && <em>{row.detail}</em>}</div>)}
    </div></Compact>}

    <Compact title="重大ニュース" className={`at-news-card ${view.newsCardState.status !== 'live' ? 'is-stale' : ''}`}>
      {/* v13.5.3: Nikkei mail intelligence renders first — ARGUS's own
          compact interpretation (what/why/market/japan/confirmation), never
          the article body. Evidence only; SDA authority is untouched. INFO
          events stay off Today (Decision First). */}
      {newsIntel.status === 'data' && newsIntel.events.filter((event) =>
        event.severity !== 'INFO').length > 0
        && <div className="at-shock at-news-intel">
        {newsIntel.events.filter((event) => event.severity !== 'INFO')
          .slice(0, 3).map((event) => <div key={event.eventId}
            className="at-shock-event" data-shock-severity={event.severity}
            data-news-event-type={event.eventType}
            data-news-confirmation={event.confirmationState}>
            <div className="at-shock-head">
              <mark data-severity={event.severity}>{event.severity}</mark>
              <b>{event.headlineJa}</b>
            </div>
            <span>{event.whyJa}</span>
            {event.japanImpactJa && event.japanImpactJa !== event.whyJa
              && <span className="at-news-japan">{event.japanImpactJa}</span>}
            {event.marketReadings.length > 0 && <span className="at-news-market">
              {event.marketReadings.slice(0, 4).map((reading) =>
                `${reading.labelJa} ${reading.value ?? '—'}${reading.unit}`)
                .join(' · ')}</span>}
            <em>{event.source} · {event.sourceReceivedAt
              ? new Date(event.sourceReceivedAt).toLocaleTimeString('ja-JP',
                { hour: '2-digit', minute: '2-digit' }) : '—'}
              {' · '}
              {event.confirmationState === 'MARKET_CONFIRMED'
                ? '市場確認済み' : '市場確認待ち'}
              {event.backfill ? ' · 再処理(過去分)' : ''}</em>
          </div>)}
      </div>}
      {/* v13.5.1: materially market-moving conditions (long-end rate shocks,
          corroborated geopolitical/energy events) render first with severity,
          why-it-matters, and sources. Absence is stated explicitly with what
          is being monitored — never a bare generic empty state. */}
      {shock.status === 'data' && shock.events.length > 0 && <div className="at-shock">
        {shock.events.map((event) => <div key={event.eventId}
          className="at-shock-event" data-shock-severity={event.severity}
          data-shock-class={event.eventClass}>
          <div className="at-shock-head">
            <mark data-severity={event.severity}>{event.severity}</mark>
            <b>{event.headlineJa}</b>
          </div>
          <span>{event.whyJa}</span>
          <em>{event.sources.map((source) => source.name).join(' · ')}
            {event.asOf ? ` · ${event.asOf}` : ''}
            {event.crossMarket.confirmed
              && ` · 市場横断確認: ${event.crossMarket.signals.join('/')}`}</em>
        </div>)}
      </div>}
      {shock.status === 'data' && shock.events.length === 0
        && <p className="at-shock-clear">市場影響級イベント: 現在なし
          （監視中: 米長期金利 · エネルギー地政学 · 市場横断確認）</p>}
      {shock.status === 'error'
        && <p className="at-shock-clear">市場ショック監視: 取得できません</p>}
      {view.news.length ? <div className="at-news">
      {view.news.map((row) => <a key={row.id} href={row.url} target="_blank" rel="noreferrer"><b>{row.titleJa}</b><span>{row.source}</span></a>)}
      </div> : <div className="at-news-zero"><b>{view.newsCardState.status === 'live' ? '一般ニュース: 現在なし' : 'ニュース確認要'}</b>
        <span>最終確認 {view.newsCardState.lastChecked ? new Date(view.newsCardState.lastChecked).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '—'}</span></div>}
    </Compact>

  </div>;
};

const Compact: React.FC<{ title: string; children: React.ReactNode; className?: string;
  onActivate?: () => void }> = ({ title, children, className = '', onActivate }) =>
  <section className={`at-compact card ${className}`} role={onActivate ? 'link' : undefined}
    tabIndex={onActivate ? 0 : undefined} onClick={onActivate}
    onKeyDown={onActivate ? (event) => { if (event.key === 'Enter' || event.key === ' ') onActivate(); } : undefined}>
    <h3>{title}{onActivate && <span aria-hidden>↗</span>}</h3>{children}</section>;

export default ArgusTodayPanel;

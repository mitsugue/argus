import { revealNewsArticle } from '../../lib/revealNewsArticle';
import type { Job } from '../dialogue/OwnerDialogue';
import { OwnerOverview } from '../dialogue/OwnerOverview';
import { validJapanMarketComparison } from '../../lib/japanMarketComparison';
import { MarketBriefCard } from './MarketBriefCard';
import { useMarketBrief } from '../../hooks/useMarketBrief';
import { useDashboardEvents } from '../../hooks/useDashboardEvents';
import { releasedEventResultLabel } from '../../lib/dashboardEventState';
import { editorialEdition, editorialCoversNews } from '../../lib/presentationIntent';
import React from 'react';
import { MarginDynamicsCard } from './MarginDynamicsCard';
import { SharedMarketContext } from './SharedMarketContext';
import { JpyPositionCard } from './JpyPositionCard';
import { ImportantEventsCard } from '../dashboard/ImportantEventsCard';
import { JapanSqCalendarCard } from '../dashboard/JapanSqCalendarCard';
import { useJapanSqCalendar } from '../../hooks/useJapanSqCalendar';
import { sqCalendarIsCurrent } from '../../lib/japanSqCalendar';
import { JapanMarketComparisonPanel } from '../chart/JapanMarketComparisonPanel';
import { useChartIntelligence } from '../../hooks/useChartIntelligence';
import type { ArgusTodayView, TodayProjection } from '../../domain/argusTodayView';
import { formatEventTime, quoteDisplayLabel, subjectDisplayName, confidenceBasisJa, waitKindJa } from '../../domain/argusTodayView';
import { displayNewsHeadline, newsAnalysisStatusJa } from '../../lib/newsHeadline';
import type { RouteKey } from '../NavRail';
import type { SettingsSection } from '../../navigation';
import { TriangleStepLoader } from '../common/TriangleStepLoader';
import { useDecisionEvidence } from '../../hooks/useDecisionEvidence';
import { GlossaryTip } from '../common/GlossaryTip';
import { REVERSAL_STATE_GLOSSARY, FAMILY_STATE_GLOSSARY } from '../../domain/glossary';
import { marketSignalsView } from '../../domain/marketSignals';
import type { NewsIntelEvent } from '../../hooks/useNewsIntelligence';
import { orderMaterialNews, groupRepeatedNewsHeadlines, NEWS_IMPORTANCE_JA } from '../../domain/newsPresentation';
import type { MarketHorizon, MarketInstrumentSymbol } from '../../domain/marketInstruments';
import './ArgusToday.css';
import './ReadingHierarchy.css';

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
  selectedSymbol: MarketInstrumentSymbol;
  horizon: MarketHorizon;
  chartLoad: TodayChartLoadState;
  /** Which canonical source currently feeds the visible projection. */
  projectionSource: 'verified-snapshot' | 'headline' | null;
  /** Truthful session/data-freshness note (e.g. EOD prices while JP OPEN). */
  freshnessNoteJa: string | null;
  /** v13.5.59: JP code → company name for the Tachibana rows (code+name rule). */
  jpNameBySymbol?: Record<string, string>;
  /** Market-shock materiality view for the Major News surface. */
  shock: {
    status: 'loading' | 'data' | 'error';
    events: Array<{
      eventId: string; eventClass: string;
      severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
      headlineJa: string; whyJa: string;
      crossMarket: { confirmed: boolean; signals: string[] };
      impactDirection?: { primaryDirection: 'BULLISH' | 'BEARISH' | 'MIXED' | 'UNCLEAR';
        directionByTarget: Record<string, string>; transmissionChain: string[] };
      sources: Array<{ name: string; kind: string }>;
      asOf: string | null;
    }>;
  };
  newsIntel: {
    status: 'loading' | 'data' | 'error';
    events: Array<{
      eventId: string; eventType: string; analysisState?: string; analysisInputScope?: string;
      revision?: number; processedAt?: string; staleness?: string; ageMinutes?: number;
      impactDirection?: NewsIntelEvent['impactDirection'];
      executionConstraint?: NewsIntelEvent['executionConstraint'];
      severity: 'INFO' | 'WATCH' | 'HIGH' | 'CRITICAL';
      headlineJa: string; whyJa: string; japanImpactJa: string | null;
      confirmationState: 'MARKET_CONFIRMED' | 'MARKET_CONFIRMATION_PENDING';
      marketReadings: Array<{ key: string; labelJa: string;
        value: number | null; change: number | null; unit: string }>;
      source: string; sourceReceivedAt: string | null; backfill: boolean;
      eventMemory: {
        status: string; firstSeenAt: string; openedDaysAgo: number | null;
        episodeId: string; flagRecovery: boolean;
        hypothesisStates: Record<string, string>;
        analogEvidence: { sampleSize: number; independentEpisodeCount: number;
          confidence: string; insufficientEvidence: boolean } | null;
        calibrationMode: 'SHADOW'; sdaAuthority: false;
      } | null;
    }>;
  };
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
// v13.5.54 (owner 2026-09-04: 「データ一部不足とは何か？全て与えているはず」).
// Every one of these is an ARGUS-side freshness or authority state — none of
// them says the owner failed to supply anything. Naming them is the whole
// point; an unmapped code still shows its raw form rather than disappearing.
const DATA_PARTIAL_REASON_JA: Record<string, string> = {
  watchlist_polling_partial: '銘柄クォートの一部が未取得',
  important_events_unread: '重要イベント情報が未取得',
  downside_unread: '急落インシデント情報が未取得',
  flow_authority_stale: '資金フロー証拠の鮮度切れ',
  supply_demand_authority_stale: '需給証拠の鮮度切れ',
  fx_authority_missing: '為替の正本が未取得',
  session_authority_missing: '市場セッション正本が未取得',
  quote_authority_missing: '判断に使えるクォートが未取得',
  visibility_limited: '可視性ガードにより表示を制限中',
};
const DATA_NOTE_JA: Record<string, string> = {
  flow_previous_value_closed_session: '資金フローは休場中のため前回値',
  flow_no_records_now: '資金フロー: 現在は帰属できる動きなし（休場中は通常）',
  supply_previous_value_closed_session: '需給は休場中のため前回値',
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
const NEXT_REVIEW_REASON_JA: Record<string, string> = {
  'resolve.freshness_unknown': '正本データの更新時刻を確認',
  'resolve.market_truth_missing': '市場データの正本を取得',
  'resolve.prediction_ledger_missing': '市場スナップショットの更新後に再作成',
  'resolve.risk_evidence_missing': 'リスク証拠を更新',
  'resolve.scenario_event_missing': '重要イベント情報を更新',
  'resolve.jp_market_engine_evidence_missing': 'チャート分析証拠を更新',
  'resolve.input_invalid': '判断入力を再取得',
  risk_reassessment: 'リスク条件を再確認',
  jp_market_engine_revalidation: 'チャート分析証拠を再検証',
  evidence_refresh: '正本証拠を更新',
};
// v13.5.36 (external review item A): MARKET VIEW (JP_MARKET_ENGINE) / ACTION (SDA)
// separation. The strip renders the document-level JP_MARKET_ENGINE consumer projection —
// reversal + downside axis states and D01-D07 family states — directly under
// the SDA action so the owner sees "what the market looks like" and "what we
// do" as two explicitly different authorities. The projection carries
// actionAuthority:false by construction and is never an SDA input.
// v13.5.36 (owner: 「言葉の意味がわからない」): reason codes rendered in plain
// Japanese. Spec-by-design states (owner context, prediction ledger auth) must
// not read as errors. Unknown codes fall through readably.
// The code space is closed: `{market_truth|prediction_ledger|jp_market_engine}_{missing|
// stale|conflict}` from referenceReasons, `quality_{partial|missing|conflict}`,
// `freshness_{stale|unknown}`, `owner_context_unknown`, `risk_evidence_empty`,
// `risk_{missing|conflict}.<factorId>`, plus the server's own quality codes
// (risk_evidence_missing / scenario_event_missing / jp_market_engine_evidence_missing).
// Every one of them is spelled out here — the owner reported seeing raw
// `freshness_unknown` / `quality_missing` / `risk_evidence_missing` /
// `scenario_event_missing` / `jp_market_engine_evidence_missing` on 2026-09-04.
const MISSING_REASON_JA: Record<string, string> = {
  freshness_stale: 'データ鮮度が低下（次の更新待ち）',
  freshness_unknown: 'データの鮮度を確認できない（更新時刻が未取得）',
  market_truth_stale: '市場データの鮮度が低下（市場終了後は終値基準で継続）',
  market_truth_missing: '市場データ未取得',
  market_truth_conflict: '市場データが食い違っています（照合待ち）',
  owner_context_unknown: '保有情報は端末内のみで参照（設計どおり・エラーではありません）',
  // v13.5.53: this reference is the SDA's EPHEMERAL prediction CONTEXT, built
  // from the market snapshot — not the durable Layer-2B ledger, and never
  // gated on owner authentication. Production on 2026-09-04 showed why the old
  // wording mattered: verificationFailures.predictionLedger was
  // "market_truth_reference_unavailable", i.e. the context could not be built
  // because the market snapshot was not fresh, yet the owner was told their
  // authentication was not set up and sent to fix a problem that did not exist.
  // State the fact; the market_truth_* line beside it carries the cause.
  prediction_ledger_missing: '予測コンテキストを作成できていません',
  prediction_ledger_stale: '予測台帳の鮮度が低下（次の記録待ち）',
  prediction_ledger_conflict: '予測台帳の記録が食い違っています（照合待ち）',
  quality_partial: 'データが一部不足',
  quality_missing: '判断に必要なデータが未取得',
  quality_conflict: '判断に必要なデータが食い違っています（照合待ち）',
  risk_evidence_empty: 'リスク入力が空（銘柄別の値が未取得）',
  risk_evidence_missing: 'リスク証拠が未取得',
  scenario_event_missing: '条件・イベントの証拠が未取得',
  jp_market_engine_missing: 'チャート証拠が未取得',
  jp_market_engine_stale: 'チャート証拠の鮮度が低下（次の更新待ち）',
  jp_market_engine_conflict: 'チャート証拠が食い違っています（照合待ち）',
  jp_market_engine_evidence_missing: 'チャート証拠が未取得',
  'risk_missing.discipline.required_authority':
    '銘柄別の価格権限なし（市場終了中または取得待ち）',
};
// An unmapped code must never reach the owner as bare English, and its meaning
// must not be invented either: say what is true (something is still missing)
// and keep the raw code visible as a code for support. `data-reason-code`
// still carries the exact identifier for tests and diagnostics.
const missingReasonJa = (line: string): string => {
  const mapped = MISSING_REASON_JA[line];
  if (mapped) return mapped;
  if (line.startsWith('risk_missing.')) {
    return `リスク入力の不足（${line.slice('risk_missing.'.length)}）`;
  }
  if (line.startsWith('risk_conflict.')) {
    return `リスク入力の食い違い（${line.slice('risk_conflict.'.length)}）`;
  }
  return `追加の証拠待ち（コード: ${line}）`;
};
const dissentReasonJa = (line: string): string =>
  line.startsWith('context_missing_advisory')
    ? '文脈証拠が不足しているという参考意見（最終判断は変えません）'
    : line;

type OtherMarketMove = ArgusTodayView['indexMoves'][number];
const OTHER_MARKET_META = {
  nikkei: { instrument: '1321', name: '日経平均', product: '1321 日経225 ETF' },
  topix: { instrument: '1306', name: 'TOPIX', product: '1306 TOPIX ETF' },
  sp500: { instrument: 'SPY', name: 'S&P 500', product: 'SPY' },
  nasdaq: { instrument: 'QQQ', name: 'NASDAQ-100', product: 'QQQ' },
} as const;

const OtherMarketsActuals: React.FC<{ moves: OtherMarketMove[] }> = ({ moves }) => {
  const [selectedId, setSelectedId] = React.useState<keyof typeof OTHER_MARKET_META>('topix');
  const [sessions, setSessions] = React.useState<1 | 5 | 20>(5);
  const move = moves.find((row) => row.id === selectedId) ?? moves[0];
  const meta = OTHER_MARKET_META[selectedId];
  const snapshot = useChartIntelligence({ scope: 'market', symbol: meta.instrument,
    market: ['1321', '1306'].includes(meta.instrument) ? 'JP' : 'US',
    timeframe: 'daily', horizon: sessions });
  const bars = snapshot.data?.indicators.bars ?? [];
  const points = bars.slice(-(sessions + 1)).map((bar) => ({ date: bar.date, value: bar.close }));
  const values = points.map((point) => point.value).filter(Number.isFinite);
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const polyline = points.map((point, index) => `${index / Math.max(1, points.length - 1) * 300},${82 - (point.value - low) / span * 68}`).join(' ');
  const first = values[0], last = values.at(-1);
  const change = first && last ? (last - first) / first * 100 : null;
  return <div className="at-other-markets__explorer" data-argus-contract="other-market-actuals-explorer-v1"
    data-other-market-symbol={meta.instrument} data-other-market-horizon={`${sessions}D`}>
    <div className="at-other-markets__controls" role="group" aria-label="比較する市場">
      {(Object.entries(OTHER_MARKET_META) as Array<[keyof typeof OTHER_MARKET_META, typeof meta]>).map(([id, row]) =>
        <button type="button" key={id} data-argus-control="market-instrument" data-instrument={row.instrument}
          aria-pressed={selectedId === id} onClick={() => setSelectedId(id)}>{row.name}</button>)}
    </div>
    <div className="at-other-markets__controls" role="group" aria-label="比較期間">
      {([1, 5, 20] as const).map(value => <button type="button" key={value}
        data-argus-control="canonical-horizon" data-horizon={`${value}D`}
        aria-pressed={sessions === value} onClick={() => setSessions(value)}>{value}営業日</button>)}
    </div>
    {snapshot.loading && <p><TriangleStepLoader compact label="選んだ市場の実績を読み込んでいます" /></p>}
    {snapshot.error && <p role="status">実績の更新を確認できません。<button type="button" onClick={snapshot.retry}>再取得</button></p>}
    {snapshot.snapshotId && points.length >= 2 ? <figure data-market-snapshot-id={snapshot.snapshotId}>
      <figcaption><b>{meta.name}</b>
      <span>{meta.product}の終値 · {sessions}営業日の実績</span></figcaption>
      <svg viewBox="0 0 300 96" role="img" aria-label={`${meta.name}連動ETFの${sessions}営業日実績`}>
        <polyline points={polyline} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg><p><strong>{change == null ? '変化率未確認' : `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}</strong>
        <span>（{points.at(-1)?.date ?? move?.asOf ?? '時点未確認'} 終値）</span></p></figure>
      : <p className="at-quiet">この期間の実績データを確認中です。</p>}
    <p className="at-other-markets__note">指数の予測や売買判断ではありません。連動ETFの実績を比較しています。</p>
  </div>;
};

const JP_MARKET_ENGINE_STATE_JA: Record<string, string> = {
  MIXED: '混在', FRAGILE: '脆弱', DOWNSIDE_TRIGGERED: '下方シグナル点灯',
  SELL_OFF_ACTIVE: '売り圧継続', REVERSAL_EARLY: '反転初動',
  TECHNICAL_REBOUND: 'テクニカル反発', RECOVERY_TEST: '回復試験',
  CONFIRMED_ADVANCE: '上昇確認', FALSE_RALLY: 'だまし上げ警戒',
};
const JP_MARKET_ENGINE_FAMILY_JA: Record<string, string> = {
  D01: '信用残', D02: '1570倍率', D03: '相対力', D04: 'EPS基準',
  D05: '海外フロー', D06: 'VIX', D07: '決算反応',
};
const familyStateJa = (row: { status?: string; conditionMet?: boolean | null }): string => {
  if (row.status === 'LICENSE_BLOCKED') return '要ライセンス';
  if (row.status !== 'AVAILABLE') return '欠測';
  return row.conditionMet === true ? '成立' : row.conditionMet === false ? '不成立' : '判定不能';
};

const MarketViewStrip: React.FC = () => {
  const evidence = useDecisionEvidence();
  const projection = evidence.marketView?.projection;
  if (!projection || projection.actionAuthority !== false) return null;
  const reversal = projection.reversal;
  // v13.5.38 MARKET SIGNALS: the same seven families in the owner vocabulary
  // (SIG-01..07) with a count recomputed from the per-signal states shown.
  return <div className="at-marketview" data-argus-contract="jp-market-engine-market-view-v1"
    aria-label="市場観（行動権限なし）">
    <small>市場観（検証前の参考情報） — 売買の最終判断とは別枠</small>
    {/* v13.5.59 (owner iPhone): MARKET SIGNALS is rendered ONCE, at the top of
        the Primary Action (tap to expand). The seven family chips that repeated
        the same conditions here are gone; only the JP_MARKET_ENGINE reversal/downside states
        stay, since they are a different judgment. */}
    <div className="mv-states">
      <span>反転: <GlossaryTip glossaryKey={reversal?.reversalState
        ? (REVERSAL_STATE_GLOSSARY[reversal.reversalState] ?? '') : 'recovery_pending'}>
        <b>{reversal?.reversalState
          ? (JP_MARKET_ENGINE_STATE_JA[reversal.reversalState] ?? reversal.reversalState) : 'データ待ち'}</b>
      </GlossaryTip></span>
      <span>下方: <GlossaryTip glossaryKey={reversal?.downsideState
        ? (REVERSAL_STATE_GLOSSARY[reversal.downsideState] ?? '') : 'recovery_pending'}>
        <b>{reversal?.downsideState
          ? (JP_MARKET_ENGINE_STATE_JA[reversal.downsideState] ?? reversal.downsideState) : 'データ待ち'}</b>
      </GlossaryTip></span>
    </div>
    <span className="mv-note">市場観は行動権限を持たない（各項目は検証前・確率は主張しない）</span>
  </div>;
};

// v13.5.36 NEWS/EVENT SIGNAL (owner spec 2026-08-23): the independent news
// direction axis rendered BESIDE the JP_MARKET_ENGINE market view and the SDA action —
// three separate judgments, never one blended score. A chart view and a news
// view that disagree stay visibly different; cancellation into a vague
// composite is structurally impossible because nothing here is summed.
// v13.5.60 (owner: 「方向性不明。なぜか？」): UNCLEAR is a verdict — this news
// does not decide up or down — not a missing value, and the label says so.
const NEWS_DIRECTION_JA: Record<string, string> = {
  BULLISH: '強気', BEARISH: '弱気', MIXED: '混在', UNCLEAR: '方向判定不能',
};
const NEWS_TARGET_JA: Record<string, string> = {
  broadMarket: '市場全体', japanEquities: '日本株', growth: 'グロース',
  semiconductors: '半導体', banks: '銀行', exporters: '輸出', energy: 'エネルギー',
};
const NEWS_CONSTRAINT_JA: Record<string, string> = {
  NO_CONSTRAINT: '制約なし', CAUTION: '買い急がず市場反応を確認',
  BLOCK_NEW_BUY: '新規買い停止（確認済み逆風）',
  RISK_REVIEW_REQUIRED: 'リスク再確認（重大・確認済み）',
};
const newsAgeJa = (event: { ageMinutes?: number }): string | null => {
  const minutes = event.ageMinutes;
  if (typeof minutes !== 'number' || minutes < 0) return null;
  if (minutes < 60) return `${minutes}分前`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)}時間前`;
  return `${Math.round(minutes / 1440)}日前`;
};
const NewsDirectionSummary: React.FC<{ event: Props['newsIntel']['events'][number] }> = ({ event }) => {
  const direction = event.impactDirection;
  const primary = direction?.primaryDirection ?? 'UNCLEAR';
  const targets = (state: string) => Object.entries(direction?.directionByTarget ?? {})
    .filter(([, value]) => value === state).map(([target]) => NEWS_TARGET_JA[target] ?? target);
  const bearish = targets('BEARISH');
  const bullish = targets('BULLISH');
  return <span className="at-news-direction" data-argus-contract="news-event-signal-v1"
    data-news-event-id={event.eventId}>
    <span><b>影響の見立て: {NEWS_DIRECTION_JA[primary] ?? '不明'}</b>
      {primary === 'UNCLEAR' && ' · この記事だけでは上下を決めません'}</span>
    {(bearish.length > 0 || bullish.length > 0) && <span>
      {bearish.length > 0 && `逆風: ${bearish.join('・')}`}
      {bearish.length > 0 && bullish.length > 0 && ' ／ '}
      {bullish.length > 0 && `追い風: ${bullish.join('・')}`}
    </span>}
    {event.executionConstraint && event.executionConstraint !== 'NO_CONSTRAINT'
      && <span>{NEWS_CONSTRAINT_JA[event.executionConstraint]}</span>}
  </span>;
};

type NewsRowMemory = Props['newsIntel']['events'][number]['eventMemory'];
export type TodayNewsRow = { id: string; eventId: string; severity: string; kind: '市場データ' | 'ニュース';
    sourceReceivedAt: string | null; headlineJa: string; whyJa: string; metaJa: string;
    eventMemory: NewsRowMemory; newsEvent?: Props['newsIntel']['events'][number];
    previousDeliveries?: Props['newsIntel']['events'] };


export const TodayNewsCards: React.FC<{ rows: readonly TodayNewsRow[]; onOpen: (id: string) => void }> = ({ rows, onOpen }) => (
<div className="at-news-rows">
        {rows.map((row) => <article key={row.id}
          className="at-news-row" data-shock-severity={row.severity} data-news-event-id={row.id}>
          <button type="button" className="at-news-row__open" onClick={() => onOpen(row.id)}>
          <span className="at-news-row__head"><mark data-severity={row.severity}>{NEWS_IMPORTANCE_JA[row.severity] ?? row.severity}</mark>
            <i>{row.kind}</i><b>{row.headlineJa}</b></span>
          <span className="at-news-row__why">{row.whyJa}</span>
          {row.newsEvent && <NewsDirectionSummary event={row.newsEvent} />}
          <em>{row.metaJa} · 詳しく読む</em>
          </button>
          {!!row.previousDeliveries?.length && <details className="at-news-memory">
            <summary>同じ見出しの以前の配信 · {row.previousDeliveries.length}件</summary>
            <p>続報・訂正の有無は各配信の詳細で確認できます。</p>
            {row.previousDeliveries.map(event => <button key={event.eventId} type="button"
              className="at-news-row__open" onClick={() => onOpen(event.eventId)}>
              {event.sourceReceivedAt ? new Date(event.sourceReceivedAt).toLocaleTimeString('ja-JP',
                { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' }) : '時刻不明'}の配信を読む
            </button>)}
          </details>}
          {/* Causal event memory (SHADOW): the flag-recovery / analog evidence
              line stays with the news it qualifies; never an SDA input. */}
          {row.eventMemory && <details className="at-news-memory">
            <summary>過去の事例との照合 · 検証中</summary>
            <span className="at-event-memory"
            data-event-memory-status={row.eventMemory.status}
            data-flag-recovery={row.eventMemory.flagRecovery ? 'true' : 'false'}
            data-calibration-mode={row.eventMemory.calibrationMode}>
            <b>{row.eventMemory.flagRecovery ? 'フラグ回収' : 'イベント記憶'}</b>
            {' '}{row.eventMemory.openedDaysAgo != null && row.eventMemory.openedDaysAgo > 0
              ? `${row.eventMemory.openedDaysAgo}日前から監視 · ` : ''}{row.eventMemory.status}
            {row.eventMemory.analogEvidence && ` · 類似 ${row.eventMemory.analogEvidence.independentEpisodeCount} 独立事例`
              + (row.eventMemory.analogEvidence.insufficientEvidence
                ? ' · 根拠不足' : ` · ${row.eventMemory.analogEvidence.confidence}`)}
            {' · 校正 SHADOW · 判断権限なし'}
          </span></details>}
        </article>)}
      </div>
);

const nextReviewLabel = (code: string | undefined): string | undefined => {
  if (!code) return undefined;
  if (NEXT_REVIEW_REASON_JA[code]) return NEXT_REVIEW_REASON_JA[code];
  // Canonical reason codes remain in the signed decision object for audit.
  // Owner UI must not expose an internal resolver token as an instruction.
  return code.startsWith('resolve.') ? '不足している正本証拠を更新' : '判断条件を再確認';
};
const fmt = (v: number) => v >= 1000 ? v.toLocaleString('ja-JP', { maximumFractionDigits: 1 }) : v.toFixed(2);
const fmtMove = (v: number, suffix = '') => `${fmt(v)}${suffix}`;
const macroTone = (move: { value: number; previous?: number | null }): string =>
  typeof move.previous === 'number' && Number.isFinite(move.previous) && move.previous !== move.value
    ? (move.value > move.previous ? 'is-positive' : 'is-negative') : 'is-neutral';
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
    data-projection-symbol={projection.symbol}
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
      <span>{projection.proxyFor ? 'ETF PROXY · ' : ''}{shortDate(projection.asOf)} {quoteDisplayLabel(projection.quoteState)}・{projection.timeframeLabel} · 過去{projection.history.length}日｜予測{projection.horizonDays}日</span>
      {/* v13.5.54: the drawn series is the index; the decision still anchors on
          the verified ETF snapshot, and the owner is told which is which. */}
      {projection.disclosureJa && <em className="at-proj-disclosure">{projection.disclosureJa}</em>}</div>
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
      {/* v13.5.36 (external review): the reference-mode numbers are DEMOTED —
          the ablation showed no out-of-sample edge over the base rate, so the
          lead line says so plainly and the digits render muted/uncolored.
          Verified mode (a future state gated on positive OOS skill) keeps
          the prominent treatment. */}
      <span>{projection.directionProbabilities
        ? `${projection.horizonDays}D 終値方向（検証済み）`
        : `類似局面の頻度 — 検証済み確率ではない（${projection.horizonDays}D・参考のみ）`}</span>
      {(['UP', 'RANGE', 'DOWN'] as const).map((key) => <span key={key}
        className={`${key.toLowerCase()} ${strongest === key ? 'is-max' : ''}`}>{key} <b>{displayProbabilities[key]}%</b></span>)}
      </div>
      : <div className="at-proj-prob is-suppressed"><b>確率は非表示</b>
        <span>{projection.probabilityTruth.directionalLeanJa} · 根拠{projection.probabilityTruth.evidenceStrength}
          · 実効n={projection.probabilityTruth.effectiveN ?? projection.effectiveSampleCount}
          · {projection.probabilityTruth.uncertaintyJa} · {projection.probabilityTruth.label}</span></div>}
    <div className="at-proj-meta"><b>{projection.directionLabel}</b><span>{projection.horizon} · 反応{projection.reactionDelay == null ? '—' : `${projection.reactionDelay.toFixed(1)}日`}</span></div>
    {/* v13.5.62 (GPT review items 3/7): the conditioning state is always stated
        (JP_MARKET_ENGINE-conditioned or fallback), and the statistical detail opens on tap. */}
    <details className="at-proj-detail" data-argus-contract="projection-method-detail-v1">
      <summary>方式と根拠の詳細</summary>
      <span>{projection.marketConditioningJa ?? '需給・トレンド条件の状態を取得できていません'}</span>
      <span>類似局面 実効n={projection.effectiveSampleCount} · BSS {projection.brierSkill == null ? '—' : projection.brierSkill.toFixed(3)}
        {!projection.directionProbabilities && ` · ${projection.probabilityTruth.uncertaintyJa}`}</span>
      <span>割合は類似局面での出現頻度です。検証済み予測確率ではありません（独立holdoutで再現性が証明されるまで確率とは表示しません）。</span>
    </details>
  </div>;
};

export const ArgusTodayPanel: React.FC<Props> = ({
  view, selectedSymbol, horizon, chartLoad,
  projectionSource, freshnessNoteJa, shock, newsIntel,
  onNavigate, onNavigateToAsset, onNavigateToSettings, aiButton, jpNameBySymbol,
}) => {
  const projection = view.projectionsByHorizon[`${horizon}D`] ?? view.projection;
  // v13.5.39: the top command area renders MARKET SIGNALS (SIG-01..07, x / 7)
  // from the real market-view projection — the seven-signal system the owner
  // reads first.  The SDA Seven Sign level stays as a secondary line.
  const decisionEvidence = useDecisionEvidence();
  const { brief: editorialBrief } = useMarketBrief();
  const dashboardEvents = useDashboardEvents();
  const sqCalendar = useJapanSqCalendar();
  const sqCalendarCurrent = sqCalendarIsCurrent(sqCalendar.data, sqCalendar.checkedAt);
  const editorialScope = view.selectedMarket === 'JP' && selectedSymbol === '1321' && horizon === 5;
  const savedEditorial = editorialScope ? editorialEdition(editorialBrief) : null;
  const editorialChartAvailable = validJapanMarketComparison(
    savedEditorial?.calculationSnapshots?.['5']?.comparison, 5);
  const [periodOverview,setPeriodOverview] = React.useState<Job|null>(null);
  const [otherMarketsOpen, setOtherMarketsOpen] = React.useState(false);
  const scopedSubject = view.selectedMarket === 'JP' && selectedSymbol === '1321' ? 'N225' : selectedSymbol;
  const matchingOverview = periodOverview?.context.subject.symbol === scopedSubject
    && periodOverview.context.subject.market === view.selectedMarket
    && periodOverview.context.horizonSessions === horizon ? periodOverview : null;
  const hasSavedPeriodChart = !editorialScope && matchingOverview?.result?.answer?.presentationStatus === 'GENERATED'
    && validJapanMarketComparison(matchingOverview.context.indexComparison,horizon);
  const topSignals = marketSignalsView(decisionEvidence.marketView?.projection ?? null);
  // v13.5.63 (GPT review item 1): the seven signals are Japanese inputs.
  const usSelected = view.selectedMarket === 'US';
  const actionCopy = {
    BUY: '条件内で新規または追加を検討',
    HOLD: '保有を維持し、判断更新条件を待つ',
    WAIT: '今は動かず、必要な正本証拠の更新を待つ',
    REDUCE: '保有リスクを減らす',
    EXIT: '保有の解消を優先する',
  }[view.finalAction];
  const target = view.canonicalDecision.targets[0];
  const invalidation = view.canonicalDecision.invalidation;
  // The complete macro-event review lives on Today. Keep this interaction on
  // the same surface while the former Alerts route is retired in stages.
  const openEventDetails = () => {
    const jump = () => document.getElementById('today-event-details')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    jump();
  };
  const openSqDetails = (eventId: string) => {
    const jump = () => {
      const item = document.getElementById(eventId);
      if (item instanceof HTMLDetailsElement) item.open = true;
      item?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    jump();
  };
  // v13.5.60 (owner iPhone review 2026-09-07): 重大ニュース and 市場リスク are
  // one block, directly under the decision (they qualify it), listing up to
  // five items instead of one; a tap lands on the matching Alerts section.
  const openNewsDetails = (anchorId?: string) => {
    onNavigate('notifications');
    const jump = () => {
      const element = document.getElementById(anchorId ?? '') ?? document.getElementById('news-intel');
      if (element) revealNewsArticle(element, 'smooth');
    };
    window.setTimeout(jump, 350);
    window.setTimeout(jump, 1000);
  };
  const deliveryGroups = groupRepeatedNewsHeadlines(newsIntel.events);
  const previousDeliveries = new Map(deliveryGroups.map(group => [group.lead.eventId, group.previous]));
  const materialMailEvents = orderMaterialNews(deliveryGroups.map(group => group.lead));
  const unexplainedMailEvents = materialMailEvents.filter(event =>
    !editorialScope || !editorialCoversNews(editorialBrief, event));
  const newsRows = orderMaterialNews<TodayNewsRow>([
    ...shock.events.map((event) => ({
      id: event.eventId, eventId: event.eventId, severity: event.severity, kind: '市場データ' as const,
      sourceReceivedAt: event.asOf,
      headlineJa: event.headlineJa, whyJa: event.whyJa, eventMemory: null,
      metaJa: `${event.sources.map((source) => source.name).join(' · ')}${event.asOf ? ` · ${event.asOf}` : ''}`,
    })),
    ...unexplainedMailEvents.map((event) => ({
      id: event.eventId, eventId: event.eventId, severity: event.severity, kind: 'ニュース' as const,
      sourceReceivedAt: event.sourceReceivedAt, newsEvent: event,
      previousDeliveries: previousDeliveries.get(event.eventId),
      headlineJa: displayNewsHeadline(event.headlineJa), whyJa: event.whyJa, eventMemory: event.eventMemory,
      metaJa: `${event.source} · ${event.sourceReceivedAt
        ? new Date(event.sourceReceivedAt).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '受信時刻不明'}`
        + `${newsAgeJa(event) ? ` · ${newsAgeJa(event)}` : ''}`
        + ` · ${event.confirmationState === 'MARKET_CONFIRMED' ? '市場反応を確認済み' : '市場反応は確認待ち'}`
        + ` · ${newsAnalysisStatusJa(event.analysisState, event.analysisInputScope)}`,
    })),
  ]);
  const NEWS_ROWS_CAP = 5;
  const criticalNewsCount = newsRows.filter(row => row.severity === 'CRITICAL').length;
  const scheduledEvents = [
    ...(view.nextEvent ? [{ kind: 'macro' as const, id: view.nextEvent.id,
      sortAt: Date.parse(view.nextEvent.at ?? ''), event: view.nextEvent }] : []),
    ...view.comingEvents.map((event) => ({ kind: 'macro' as const, id: event.id,
      sortAt: Date.parse(event.at ?? ''), event })),
    ...(sqCalendar.data?.events ?? []).map((event) => ({ kind: 'sq' as const,
      id: event.eventId, sortAt: Date.parse(`${event.sqDate}T08:45:00+09:00`), event })),
  ].sort((left, right) => {
    const leftAt = Number.isFinite(left.sortAt) ? left.sortAt : Number.MAX_SAFE_INTEGER;
    const rightAt = Number.isFinite(right.sortAt) ? right.sortAt : Number.MAX_SAFE_INTEGER;
    return leftAt - rightAt || left.id.localeCompare(right.id);
  });
  const nextScheduledEvent = scheduledEvents[0] ?? null;
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
    // v13.5.57: the contract names the DECISION SUBJECT (the verified ETF
    // snapshot), never the series being drawn. Since the headline draws the
    // index, projection.symbol reads N225/NDX while the SDA subject and the
    // release-acceptance contract are 1321/1306/SPY/QQQ.
    data-canonical-instrument={selectedSymbol}
    data-canonical-horizon={`${projection?.horizonDays ?? horizon}D`}>
    <span className="at-contract-state" aria-hidden="true"
      data-argus-contract="today-projection-state-v1"
      data-projection-state={chartLoad.snapshotId ? 'available' : 'missing'}
      data-projection-symbol="N225"
      data-projection-snapshot-id={chartLoad.snapshotId ?? undefined}
      data-projection-response-snapshot-id={coherentResponseSnapshotId ?? undefined}
      data-projection-snapshot-state={chartLoad.snapshotState}
      data-projection-revalidation-state={revalidationState} />
    <section className="at-view-hero" aria-label="今日の見立て">
      {editorialScope ? <MarketBriefCard signals={topSignals && !usSelected ? { activeCount: topSignals.activeCount, total: topSignals.total } : null}
        cutoff={decisionEvidence.marketView?.informationCutoff ?? null} market="JP" editorial />
        : <><OwnerOverview key={`${view.selectedMarket}:${scopedSubject}:${horizon}`}
          symbol={scopedSubject} market={view.selectedMarket} horizon={horizon} onReference={setPeriodOverview}/>
          <details className="at-brief__fallback"><summary>市場全体の説明 · 日経平均・5営業日</summary>
            <MarketBriefCard market="JP"/>
          </details></>}
      {criticalNewsCount > 0 && <button type="button" className="at-critical-jump"
        onClick={()=>document.getElementById('today-material-news')?.scrollIntoView({behavior:'smooth',block:'start'})}>
        重大なニュース・市場変化 {criticalNewsCount}件を確認する ↓
      </button>}
    </section>
    {view.selectedMarket === 'JP' && selectedSymbol === '1321' && !editorialChartAvailable && !hasSavedPeriodChart
      && <section aria-label="日経平均の過去比較">
        {savedEditorial && <p className="at-stored-note">この見立てには当時の比較チャートが保存されていません。以下は最新データによる比較で、上の説明と同じ時点の根拠とは限りません。</p>}
        <JapanMarketComparisonPanel horizon={horizon} />
      </section>}
    {!chartLoad.snapshotId && <div className="at-canonical-load-status" role="status">
      {chartLoad.loaderVisible && <TriangleStepLoader label={chartLoad.slowInitial
        ? '日経平均の根拠を確認しています。前回の説明は引き続き読めます'
        : '日経平均の根拠を読み込んでいます'} />}
      {!chartLoad.loaderVisible && <span>日経平均の根拠を準備しています</span>}
      {chartLoad.error && <><span>根拠を取得できませんでした。</span>
        <button type="button" onClick={chartLoad.retry}>再取得</button></>}
    </div>}

    <article className={`at-decision at-primary-hero card is-${view.finalAction.toLowerCase()}`}
      aria-label="A.R.G.U.S. Primary Action">
      <div className="at-kpis"><span>DATA <b className={`is-${view.dataStatus.tone}`}>● {view.dataStatus.label}</b></span>
        {/* v13.5.60 (owner iPhone review): the reasons behind a non-LIVE DATA
            state are ARGUS-side fetch/freshness facts, not trading information —
            they open on tap instead of occupying the decision area. */}
        {(view.dataQualityReasonCodes.length > 0 || view.dataQualityNotes.length > 0)
          && <details className="at-data-detail">
          <summary>{view.dataQualityReasonCodes.length > 0 ? '何が不足か' : '補足'}を見る</summary>
          {view.dataQualityReasonCodes.length > 0 && <span className="at-data-why">
            {view.dataQualityReasonCodes
              .map((code) => DATA_PARTIAL_REASON_JA[code] ?? `未定義の不足理由（コード: ${code}）`)
              .join(' · ')}（いずれもARGUS側の取得・鮮度の状態です）</span>}
          {view.dataQualityNotes.length > 0 && <span className="at-data-why at-data-note">
            {view.dataQualityNotes.map((code) => DATA_NOTE_JA[code] ?? code).join(' · ')}</span>}
          {/* v13.5.62 (GPT review item 1): what the percentage is. */}
          <span className="at-data-why at-confidence-basis">{confidenceBasisJa(view.canonicalDecision)}</span>
          {/* v13.5.61 (owner: 「どうなれば BUY になるのか」): the exact gate, in words. */}
          <span className="at-data-why at-buy-conditions">BUYが出る条件: ①リスク制約なし ②需給・トレンドの反転状態が反転初期・自律反発・回復試験・上昇確認のいずれかで検証済み ③検証済み買い成立レジストリの本番採用（現在は未採用＝構造的に無効。検証結果: docs/REVERSAL_BUY_VALIDATION.md） ④保有側の追加許可</span>
        </details>}
        <span className="at-buy-note">BUYは検証完了まで出ません（方針・現在は構造的に無効）</span>
        {/* v13.5.65 (stabilization item 5): while this session's first fetch runs,
            the stored evidence is on screen — with its time, never silently. */}
        {decisionEvidence.loading && decisionEvidence.generatedAt && <span className="at-stored-note" data-argus-contract="stored-evidence-note-v1">
          <TriangleStepLoader compact label="判断の根拠を更新中" /> 保存分 {new Date(decisionEvidence.generatedAt).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} を表示中（更新取得中）</span>}</div>

      <details className="at-seven" data-argus-contract="seven-sign-ladder-v1"
        data-seven-status={view.canonicalDecision.sevenSign.status}
        data-seven-level={view.actionScore ?? undefined}
        data-market-signals-active={topSignals?.activeCount ?? undefined}
        data-market-signals-total={topSignals?.total ?? undefined}>
        <summary aria-label={topSignals
          ? `Market Signals ${topSignals.countLabel} · Seven Sign ${view.actionScore ?? '未確定'} / 7 · ${view.canonicalDecision.sevenSign.status}`
          : `Seven Sign ${view.actionScore ?? '未確定'} / 7 · ${view.canonicalDecision.sevenSign.status}`}>
          <small>セブンサイン · 日本株の7条件</small>
          {/* v13.5.63 (GPT review item 1): the seven conditions are Japanese
              market inputs (credit balances, 1570, foreign flow…). With the US
              market selected they are labelled as Japan's, and the US
              conditioning inputs are named instead of borrowing the count. */}
          {usSelected && <i className="at-signals-market" data-argus-contract="market-signals-market-v1">日本市場の値</i>}
          {/* v13.5.62 (GPT review item 4): the information cutoff of the document
              behind the count, so Today and the brief can be compared. */}
          {decisionEvidence.marketView?.informationCutoff && <i className="at-signals-cutoff" data-argus-contract="market-signals-cutoff-v1">
            {new Date(decisionEvidence.marketView.informationCutoff).toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit' })} 時点</i>}
          <b data-argus-contract="market-signals-top-v1">
            {topSignals ? topSignals.countLabel : '— / 7'}</b>
          <span className="at-seven-status">
            {usSelected ? '米国選択中: 7条件は日本固有（米国は適用外）· 米国の条件付けはVIX水準・VIX10日変化・対SPY相対力 · ' : ''}
            {topSignals ? `点灯 ${topSignals.activeCount} · ` : ''}
            {view.actionScore == null ? '校正待ち · ' : ''}
            判断レベル {view.actionScore == null ? '— / 7' : `${view.actionScore} / 7`}
            {topSignals ? '' : ` · ${view.canonicalDecision.sevenSign.status}`}</span>
          <span className="at-seven-chips" aria-hidden="true">
            {topSignals
              ? topSignals.signals.map((row) => <i key={row.id}
                className={row.state === 'ACTIVE' ? 'is-current' : ''}
                data-signal-id={row.id} data-signal-state={row.state}
                title={`${row.id} ${row.nameJa} ${row.stateJa}`}>{row.id.slice(-1)}</i>)
              : [1, 2, 3, 4, 5, 6, 7].map((level) => <i key={level}
                className={level === view.actionScore ? 'is-current' : ''}
                data-seven-sign-level={level}>{level}</i>)}
          </span>
        </summary>
        <div className="at-seven-detail">
          {topSignals && <div className="at-seven-signals" data-argus-contract="market-signals-top-detail-v1">
            {topSignals.signals.map((row) => <GlossaryTip key={row.id} glossaryKey={row.glossaryKey}>
              <i data-signal-id={row.id} data-signal-state={row.state}>
                {row.id} {row.nameJa} <b>{row.stateJa}</b></i>
            </GlossaryTip>)}
            <small>点灯 = 条件成立のみ数える（判定不能・欠測・古い・要ライセンスは数えない）</small>
          </div>}
          <p className="at-seven-gated">判断レベル（SEVEN SIGN・売買判断側の校正段階）:</p>
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
      <details className="at-decision-details">
        <summary>売買判断：{MARKET_STANCE[view.finalAction]}<span>判断条件とデータの状態を見る</span></summary>
      <div className="at-call">
        {/* v13.5.54: name the instrument the DECISION is anchored on, not the
            series being drawn. Since the headline chart switched to the index,
            view.selectedInstrument follows the projection — reading
            「PRIMARY ACTION · JP N225」 while the SDA subject is 1321 is exactly
            the confusion the index disclosure exists to prevent. */}
        {/* v13.5.61 (owner: 「数字の表示は止めること」): the subject is named in
            words on Today; its code stays on the Holdings page and in the
            data-canonical-instrument contract attribute. */}
        <small>PRIMARY ACTION · {view.selectedMarket}{' '}
          {subjectDisplayName(view.canonicalDecision.subject?.instrumentId
            || view.selectedInstrument?.symbol || '', view.selectedInstrument?.label)}</small>
        <strong style={{ color: ACTION_TONE[view.finalAction] }}>{MARKET_STANCE[view.finalAction]}</strong>
        <span className={`at-authority is-${view.canonicalDecision.status.toLowerCase()}`}>
          {view.canonicalDecision.status === 'EVALUATED' ? '確認済み' : '判断データ確認中'}</span>
      </div>
      <p className="at-impact-copy">{actionCopy}</p>
      {/* v13.5.62 (GPT review item 1): which WAIT this is — data-gated, risk-constrained, or no BUY case. */}
      {waitKindJa(view.canonicalDecision) && <p className="at-wait-kind" data-argus-contract="wait-kind-v1">{waitKindJa(view.canonicalDecision)}</p>}
      {/* v13.5.2: Seven Sign is COMPACT — one summary line + seven chips,
          with meanings and the exact machine reason codes expanding on tap.
          All truthful canonical states are preserved; while everything is
          DATA_GATED the surface stays two short rows instead of a wall.
          Nothing here is computed client-side — it renders the SDA
          projection. */}
      {/* Data availability qualifies the decision before the signals. */}

      <div className="at-action-plan" aria-label="行動条件">
        <div><b>今すること</b><span>{actionCopy}</span></div>
        <div><b>目標</b><span>{target ? `${target.value} ${target.unit}` : '検証済み目標なし'}</span></div>
        <div><b>無効化</b><span>{invalidation ? `${invalidation.value} ${invalidation.unit}` : '検証済み無効化条件なし'}</span></div>
        <div><b>次の確認</b><span>{nextReviewLabel(view.canonicalDecision.nextReviewConditionCodes[0])
          ?? (view.nextEvent ? `${view.nextEvent.code}（${formatEventTime(view.nextEvent.at, view.nextEvent.dateOnly)}）` : '正本証拠の更新')}</span></div>
      </div>

      </details>
    </article>



    {view.holdingsReview.length > 0 && <section className="at-priorities card" aria-label="OWNER PRIORITIES">
      <div className="at-head"><b>自分の銘柄への影響</b><span>優先して確認</span></div>
      {view.holdingsReview.map((item) => {
        const content = <>
          <span className="at-priority-title">
            <b>{item.name?.trim() || item.symbol}</b><em>{item.isHeld ? '保有' : 'WATCH'}</em>
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

    <section id="today-material-news" className="at-event card at-news-top" aria-label="重大ニュース・市場リスク"
      data-argus-contract="today-material-news-v1" data-news-count={newsRows.length}>
      <div className="at-head"><b>重大ニュース・市場リスク</b>
        <span>{newsRows.length > NEWS_ROWS_CAP ? `${NEWS_ROWS_CAP} / ${newsRows.length}件` : `${newsRows.length}件`}</span></div>
      <p className="at-news-order">重要度順 · 赤は重大、黄は重要。同じ重要度では新しい情報から表示します。</p>
      {newsIntel.status === 'error' && <p className="at-shock-clear" role="status">
        {newsIntel.events.length ? 'ニュース更新失敗・前回取得分を表示しています。' : 'ニュースを取得できていません。'}</p>}
      {newsIntel.status === 'loading' && <p className="at-shock-clear"><TriangleStepLoader label="ニュースを更新しています。取得済みの記事は引き続き読めます" /></p>}
      {newsRows.length > 0 && <TodayNewsCards rows={newsRows.slice(0, NEWS_ROWS_CAP)}
        onOpen={(id) => openNewsDetails(`news-${id}`)} />}
      {shock.status === 'data' && newsIntel.status === 'data'
        && shock.events.length === 0 && materialMailEvents.length === 0
        && <p className="at-shock-clear">突発の市場ショック: 現在なし
          （監視中: 中央銀行 · 雇用/物価 · 地政学 · 企業イベント）·
          予定されている経済イベントはイベント欄に表示されます</p>}
      {shock.status === 'error' && <p className="at-shock-clear">市場ショック監視: 取得できません</p>}
      <p className="at-news-note">ニュースの方向はチャート観とは独立しています。ニュースは売買権限を持たない参考情報です。</p>
      <button type="button" className="at-news-more" onClick={() => openNewsDetails()}>ニュース・続報をすべて見る ↗</button>

    </section>

    <section className="at-event card" aria-label="重要イベント" data-argus-contract="unified-event-schedule-v1">
      <div className="at-head"><b>重要イベント</b><span>30日先まで</span></div>
      {nextScheduledEvent ? <button type="button"
        onClick={() => nextScheduledEvent.kind === 'sq'
          ? openSqDetails(nextScheduledEvent.event.eventId) : openEventDetails()}>
        {nextScheduledEvent.kind === 'sq' ? <>
          <strong>{nextScheduledEvent.event.title}（{nextScheduledEvent.event.sqDate.replaceAll('-', '/')}・寄付き基準）</strong>
          <time>{nextScheduledEvent.event.kind === 'MAJOR_SQ' ? 'メジャーSQ' : 'SQ'}</time>
          <small>取引所日程。方向判断ではありません</small>
        </> : <>
          <strong>{nextScheduledEvent.event.code}（{formatEventTime(nextScheduledEvent.event.at, nextScheduledEvent.event.dateOnly)}）</strong>
          <time>{nextScheduledEvent.event.impact.toUpperCase()}</time>
          {nextScheduledEvent.event.descriptionJa && <small>{nextScheduledEvent.event.descriptionJa.slice(0, 32)}</small>}
        </>}
      </button> : <p className="at-quiet">{view.eventsAuthorityUnknown
        ? 'イベント情報を取得できていません（予定がないという意味ではありません）'
        : '直近の重要イベントなし'}</p>}
      {/* v13.5.54: a release that just fired must not vanish from Today the
          moment it happens — that is when the owner most needs it. */}
      {view.releasedEvent && <p className="at-released">
        <b>発表済み</b> {view.releasedEvent.code}
        <time>（{formatEventTime(view.releasedEvent.at, view.releasedEvent.dateOnly)}）</time>
        <span>{releasedEventResultLabel(view.releasedEvent, dashboardEvents)}</span>
      </p>}
      <div className="at-coming"><b>この先の予定</b>
        {scheduledEvents.length > 1
          ? scheduledEvents.slice(1).map((row) => row.kind === 'sq'
            ? <button type="button" key={row.id} onClick={() => openSqDetails(row.event.eventId)}
              data-event-kind={row.event.kind}>{row.event.title}（{row.event.sqDate.replaceAll('-', '/')}・寄付き基準）
              <small>{sqCalendarCurrent && !sqCalendar.failed ? row.event.stage === 'TODAY' ? '本日' : row.event.stage === 'LAST_TRADING_DAY'
                ? '最終取引日' : row.event.stage === 'EVENT_WEEK' ? '今週' : '予定' : '保存済み日程'}</small></button>
            : <button type="button" key={row.id} onClick={openEventDetails}>
              {row.event.code}（{formatEventTime(row.event.at, row.event.dateOnly)}）</button>)
          : <span>{view.eventsAuthorityUnknown ? '取得待ち' : '予定なし'}</span>}
        {sqCalendar.loading && <span><TriangleStepLoader compact label="SQ日程を更新中" /></span>}
        {sqCalendar.failed && !sqCalendar.data?.events.length && <span> SQ日程は更新を確認できません</span>}
      </div>
      <button type="button" className="at-event-more" onClick={openEventDetails}>イベントの結果・出典を見る ↗</button>
    </section>

    {/* Keep the complete pre-release scenario, official result, and answer-check
        on Today before retiring the separate Alerts surface.  A distinct ID
        prevents an anchor collision during this measured migration. */}
    <ImportantEventsCard sectionId="today-event-details" />
    <JapanSqCalendarCard />

    <details className="at-other-markets card" data-argus-contract="other-markets-actuals-v1"
      onToggle={(event) => setOtherMarketsOpen(event.currentTarget.open)}>
      <summary>他の市場を見る</summary>
      <section className="at-lamps" aria-label="市場セッション">
        {view.sessionLamps.map((lamp) => <span key={lamp.key} className={`is-${lamp.tone}`}>
          <i aria-hidden />{lamp.label}
        </span>)}
      </section>
      {freshnessNoteJa && <p className="at-freshness-note">{freshnessNoteJa}</p>}
      <p className="at-other-markets__note">市場間の実績比較です。Todayの見通しや確率は切り替わりません。</p>
      {otherMarketsOpen && <OtherMarketsActuals moves={view.indexMoves} />}
      <p className="at-other-markets__note">指数そのもののリアルタイム値ではありません。NASDAQ総合ではなくNASDAQ-100連動ETFを参照しています。</p>
    </details>

    {!usSelected && <SharedMarketContext horizon={horizon} />}
    {!usSelected && <MarginDynamicsCard document={decisionEvidence.marketView?.margin1570Dynamics} refreshFailed={!!decisionEvidence.error} />}
    {!usSelected && <JpyPositionCard document={decisionEvidence.marketView?.jpyPosition} />}

    {/* v13.5.59: reading order top-down — decision → signals → what is
        coming → the market itself → then the reference market view and the
        news axis, then verification detail. */}
    {/* v13.5.62: the reference market view and the same market's 需給 sit
        together — JP with JP, US with US — instead of alternating. */}
    {/* v13.5.61 (owner): Japan first, then the US — each market's live line,
        market view, 需給 and (for the US) MACRO in its own block, never mixed. */}
    <section className="at-event card at-context" aria-label="市場観・需給（参考）">
      <div className="at-context__block" data-market="JP">
        <small className="at-context__title">日本株</small>
        <MarketViewStrip />
        {view.positioningByMarket.JP.length > 0 && <div className="at-positioning">
          <small>JP 需給</small>
          <div className="at-position-rows">
            {view.positioningByMarket.JP.map((row) => <div key={row.key} className={`is-${row.tone ?? 'neutral'}`}>
              <b>{row.label}</b><span>{row.value}</span>{row.detail && <em>{row.detail}</em>}</div>)}
          </div>
        </div>}
      </div>
      <div className="at-context__block" data-market="US">
        <small className="at-context__title">米国株</small>
        {view.positioningByMarket.US.length > 0 && <div className="at-positioning at-positioning--us">
          <small>US 需給</small>
          <div className="at-position-rows">
            {view.positioningByMarket.US.map((row) => <div key={row.key} className={`is-${row.tone ?? 'neutral'}`}>
              <b>{row.label}</b><span>{row.value}</span>{row.detail && <em>{row.detail}</em>}</div>)}
          </div>
        </div>}
        {view.macroMoves.length > 0 && <div className="at-macro">
          <small>MACRO</small>
          <div className="at-rows at-macro-rows">
            {view.macroMoves.map((move) => <div key={move.id} className={macroTone(move)}>
              <b>{move.label}</b><span>{fmtMove(move.value, move.suffix)}</span>
              <em>{move.directionLabel ?? '→'} · {shortDate(move.asOf)}</em></div>)}
          </div>
        </div>}
        {view.positioningByMarket.US.length === 0 && view.macroMoves.length === 0
          && <span className="at-quiet">米国株の需給・MACROは取得待ち</span>}
      </div>
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
        {view.canonicalDecision.missingReasonCodes.map((line) => <p
          key={`missing:${line}`} data-reason-code={line}>不足: {missingReasonJa(line)}</p>)}
        {view.canonicalDecision.dissentReasonCodes.map((line) => <p
          key={`dissent:${line}`} data-reason-code={line}>補足意見: {dissentReasonJa(line)}</p>)}
        <div className="at-detail-actions">{aiButton}<button type="button"
          onClick={() => onNavigateToSettings
            ? onNavigateToSettings('recovery') : onNavigate('settings')}>Settings / Recovery</button></div>
      </div>
    </details>





  </div>;
};

const Compact: React.FC<{ title: string; children: React.ReactNode; className?: string;
  onActivate?: () => void }> = ({ title, children, className = '', onActivate }) =>
  <section className={`at-compact card ${className}`} role={onActivate ? 'link' : undefined}
    tabIndex={onActivate ? 0 : undefined} onClick={onActivate}
    onKeyDown={onActivate ? (event) => { if (event.key === 'Enter' || event.key === ' ') onActivate(); } : undefined}>
    <h3>{title}{onActivate && <span aria-hidden>↗</span>}</h3>{children}</section>;

export default ArgusTodayPanel;

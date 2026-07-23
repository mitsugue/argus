import React, { useEffect, useMemo, useState } from 'react';
import { PageShell } from './PageShell';
import { useLocale, tEn } from '../i18n';
import { previousJudgment, recordJudgment } from '../lib/judgmentLog';
import { useAssetIntel } from '../hooks/useAssetIntel';
import { latestActionPriorities, latestSessionBrief, latestFireCore, publishEventsJa, publishDataQuality, latestDataQuality } from '../lib/positionExposureShare';
import { maybeDailySnapshot } from '../lib/portfolioSync';
import { maybeUpdateOutcomes } from '../lib/decisionQuality';
import { ProHandoffButton } from '../components/dashboard/ProHandoffButton';
import { MobileStickyCommand } from '../components/dashboard/MobileStickyCommand';
import { runNotificationEngine } from '../lib/notifications';
import { assessBackupSafety } from '../lib/backupSafety';
import { listSnapshots } from '../lib/portfolioSync';
import type { RouteKey } from '../components/NavRail';
import '../components/dashboard/Dashboard.css';
import { ArgusTodayPanel } from '../components/today/ArgusTodayPanel';
import { buildArgusTodayView, buildTodayReview, selectTodayNews,
  type MarketSelectionMode, type TodayMoveInput, type TodayPositioningRow } from '../domain/argusTodayView';
import { resolveCommandSummary } from '../domain/commandSummary';
import { SIGNALS, type SignalCode } from '../domain/actionLevel';
import { useMarketLedger } from '../hooks/useMarketLedger';
import { useChartIntelligence } from '../hooks/useChartIntelligence';
import { useMarketNews } from '../hooks/useMarketNews';
import type { ChartIntelligencePayload } from '../types/chartIntelligence';
import type { TodayProjectionInput } from '../domain/argusTodayView';

interface Props {
  onNavigate: (key: RouteKey) => void;
  /** V12.2.12: Asset Deskの当該銘柄カードを開いてスクロール(App.tsx state経由)。 */
  onNavigateToAsset?: (symbol: string, section?: string) => void;
}

// Today is a SUMMARY composed from LIVE data (action-labels + market-regime +
// events). Detail lives on the respective detail pages.
const formatDate = (iso: string) => {
  const d = new Date(`${iso}T00:00:00+09:00`);
  return d.toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  });
};

function instrumentLabel(payload: ChartIntelligencePayload): string {
  if (payload.symbol === '1321') return '日経225 ETF（1321）';
  const name = (payload.displayNameJa || payload.symbol).trim();
  return name.includes(payload.symbol) ? name : `${name}（${payload.symbol}）`;
}

function projectionInput(payload: ChartIntelligencePayload | null): TodayProjectionInput | null {
  if (!payload) return null;
  return { symbol: payload.symbol, label: instrumentLabel(payload), asOf: payload.periodEnd,
    status: payload.status, timeframe: payload.timeframe,
    quoteState: payload.quoteState ?? 'CLOSE',
    sourceHistoryCount: payload.indicators.bars.length,
    instrumentId: payload.instrumentMetadata?.instrumentId,
    source: payload.instrumentMetadata?.source ?? 'existing_market_data_cache',
    availableFrom: payload.instrumentMetadata?.availableFrom,
    assetType: payload.instrumentMetadata?.assetType,
    proxyFor: payload.symbol === '1321'
      ? (payload.instrumentMetadata?.proxyFor ?? 'Nikkei 225') : payload.instrumentMetadata?.proxyFor,
    licenseStatus: payload.symbol === '1321'
      ? (payload.instrumentMetadata?.licenseStatus ?? 'license_unverified')
      : (payload.instrumentMetadata?.licenseStatus ?? 'not_applicable'),
    bars: payload.indicators.bars, zones: payload.zones,
    eventMarkers: payload.eventMarkers,
    turningPoints: payload.turningPoints,
    calibration: payload.todayIntelligence?.calibration,
    shortSelling: payload.todayIntelligence?.shortSelling ?? null,
    failedRally: payload.todayIntelligence?.failedRally ?? null };
}

function marketMove(payload: ChartIntelligencePayload | null, id: string): TodayMoveInput | null {
  const bars = payload?.indicators.bars.filter((bar) => Number.isFinite(bar.close) && bar.close > 0) ?? [];
  const latest = bars.at(-1), previous = bars.at(-2);
  if (!latest || !payload) return null;
  const changePct = previous && previous.close > 0 ? (latest.close - previous.close) / previous.close * 100 : null;
  return { id, symbol: payload.symbol, market: payload.market === 'JP' ? 'JP' : 'US',
    label: instrumentLabel(payload), value: latest.close, previous: previous?.close ?? null,
    directionLabel: changePct == null ? undefined : `${changePct >= 0 ? '▲' : '▼'}${Math.abs(changePct).toFixed(1)}%`,
    asOf: latest.date, status: payload.status === 'delayed' ? 'delayed' : 'close',
    history: bars.slice(-12).map((bar) => ({ date: bar.date, value: bar.close })) };
}

function reviewFor(payload: ChartIntelligencePayload | null, action: string, date: string) {
  return buildTodayReview(payload?.indicators.bars ?? [], payload ? instrumentLabel(payload) : '対象価格', action, date);
}

const signed = (value: number, digits = 0) => `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;
const oku = (value: number) => `${Math.round(value / 100_000_000).toLocaleString('ja-JP')}億`;

export const CommandCenter: React.FC<Props> = ({ onNavigate, onNavigateToAsset }) => {
  useLocale();   // re-render Today on locale switch
  // V12.2.12: 個別銘柄系のデータ組み立ては useAssetIntel(Today/Asset Desk共有の
  // 正本)へ移設。Todayは publish:true — 共有ストアへのpublish副作用(Exposure/AP/
  // Brief/Scenarios/Plans/Strategy/FireCore)は従来どおりTodayだけが実行する。
  const {
    assets, al, regime, impEvents, rates, events247,
    flowRecords, sdSignals, cardGroups, positionExposure,
    apItems, sessionBrief, scenarioSets, portfolioStrategy, positionPlans,
    phase, judgment, isPartial, visLimited, cappedConf, commandSummary,
    positionRisk, overlay,
  } = useAssetIntel({ publish: true });
  const marketLedger = useMarketLedger();
  const jpChart = useChartIntelligence({ scope: 'market', timeframe: 'daily', enabled: true });
  const topixChart = useChartIntelligence({ scope: 'asset', symbol: '1306', market: 'JP', timeframe: 'daily', enabled: true });
  const sp500Chart = useChartIntelligence({ scope: 'asset', symbol: 'SPY', market: 'US', timeframe: 'daily', enabled: true });
  const nasdaqChart = useChartIntelligence({ scope: 'asset', symbol: 'QQQ', market: 'US', timeframe: 'daily', enabled: true });
  const marketNews = useMarketNews();
  const [marketMode, setMarketMode] = useState<MarketSelectionMode>(() => {
    try {
      const saved = localStorage.getItem('argus.today.marketSelection.v1');
      return saved === 'JP' || saved === 'US' ? saved : 'AUTO';
    } catch { return 'AUTO'; }
  });
  const changeMarketMode = (mode: MarketSelectionMode) => {
    setMarketMode(mode);
    try { localStorage.setItem('argus.today.marketSelection.v1', mode); } catch { /* device-local best effort */ }
  };
  const [selectedInstrument, setSelectedInstrument] = useState<{ JP: '1321' | '1306'; US: 'SPY' | 'QQQ' }>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('argus.today.selectedInstrument.v1') || '{}') as Record<string, string>;
      return { JP: saved.JP === '1306' ? '1306' : '1321', US: saved.US === 'QQQ' ? 'QQQ' : 'SPY' };
    } catch { return { JP: '1321', US: 'SPY' }; }
  });
  const changeInstrument = (market: 'JP' | 'US', symbol: string) => {
    const next = { ...selectedInstrument,
      [market]: market === 'JP' && symbol === '1306' ? '1306'
        : market === 'US' && symbol === 'QQQ' ? 'QQQ'
          : market === 'JP' ? '1321' : 'SPY' } as typeof selectedInstrument;
    setSelectedInstrument(next);
    setMarketMode(market);
    try {
      localStorage.setItem('argus.today.selectedInstrument.v1', JSON.stringify(next));
      localStorage.setItem('argus.today.marketSelection.v1', market);
    } catch { /* device-local best effort */ }
  };
  // v11.9.0/v11.17.0: one automatic LOCAL snapshot per JST day once holdings
  // price — scenarioSummary込みで「あの日ARGUSが何を言っていたか」を残す(送信なし)。
  useEffect(() => {
    try {
      const flowBySymbol: Record<string, string> = {};
      for (const r of flowRecords) flowBySymbol[r.symbol.toUpperCase()] = r.flowClass;
      const tops = latestActionPriorities().slice(0, 7).map((x) => ({
        symbol: x.symbol, rank: x.priorityRank, actionLabel: x.actionLabel, blockingReason: x.blockingReason }));
      maybeDailySnapshot(positionExposure, __APP_VERSION__, flowBySymbol,
        sdSignals.map((s) => ({ symbol: s.symbol, rank: s.supplyDemandRank, condition: s.condition,
          level: (s as { supplyDemandLevel?: string }).supplyDemandLevel } as never)), tops,
        (() => { const b = latestSessionBrief(); return b ? { headlineJa: b.headlineJa, ownerMode: b.ownerMode,
          sessionType: b.sessionType, nextChecksJa: b.nextChecksJa, whatNotToDoJa: b.whatNotToDoJa } : null; })(),
        scenarioSets.map((s) => ({ symbol: s.symbol, dominant: s.dominant, evidenceQuality: s.evidenceQuality })),
        positionPlans.map((p) => ({ symbol: p.symbol, planType: p.planType, currentStance: p.currentStance,
          blockingReasons: p.blockingReasons, evidenceQuality: p.evidenceQuality })),
        portfolioStrategy.noHoldings ? undefined : {
          strategyMode: portfolioStrategy.strategyMode, fireStatus: portfolioStrategy.fireStatus,
          corePct: portfolioStrategy.corePct, satellitePct: portfolioStrategy.satellitePct,
          tacticalPct: portfolioStrategy.tacticalPct, hedgePct: portfolioStrategy.hedgePct,
          tacticalBudget: portfolioStrategy.tacticalBudget,
          themeRisk: portfolioStrategy.themeRisk, singleNameRisk: portfolioStrategy.singleNameRisk,
          roles: portfolioStrategy.roles.filter((r) => r.weightPct != null)
            .map((r) => ({ symbol: r.symbol, role: r.role, addPolicy: r.addPolicy })) },
        (() => { const f = latestFireCore(); return f && f.positions.length ? {
          mutualFundTotal: f.mutualFundTotal, fireCoreTotal: f.fireCoreTotal,
          monthlyContributionTotal: f.monthlyContributionTotal,
          tacticalToCoreRatio: f.tacticalToCoreRatio, tacticalToCoreBand: f.tacticalToCoreBand,
          contributionDataStatus: f.contributionDataStatus,
          valuationDataStatus: f.valuationDataStatus, staleCount: f.staleCount } : undefined; })(),
        (() => { const d = latestDataQuality(); return d ? {
          overallStatus: d.overallStatus, topIssues: d.topIssuesJa.slice(0, 4),
          expectedDisabled: d.expectedDisabledJa.slice(0, 3) } : undefined; })());
    } catch { /* quota */ }
  }, [positionExposure, scenarioSets, positionPlans, portfolioStrategy, sdSignals, flowRecords]);

  // v11.14.0: 通知エンジン — 変化検知のみ(60sスロットル+dedupe+静音時間内蔵)。
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        const sdBySymbol: Record<string, { rank: string; condition: string; level?: string; name?: string; isHeld?: boolean }> = {};
        for (const s of sdSignals) {
          sdBySymbol[s.symbol.toUpperCase()] = {
            rank: s.supplyDemandRank, condition: s.condition,
            level: (s as { supplyDemandLevel?: string }).supplyDemandLevel,
            name: s.name, isHeld: !!positionExposure.notes[s.symbol.toUpperCase()]?.held };
        }
        const flowBySymbol: Record<string, { flowClass: string; name?: string; isHeld?: boolean }> = {};
        for (const r of flowRecords) {
          flowBySymbol[r.symbol.toUpperCase()] = { flowClass: r.flowClass, name: r.name,
            isHeld: !!positionExposure.notes[r.symbol.toUpperCase()]?.held };
        }
        const snaps = listSnapshots();
        const age = snaps.length
          ? Math.floor((Date.now() - Date.parse(snaps[0].createdAt)) / 86_400_000) : null;
        const scenarioBySymbol: Record<string, { dominant: string; name?: string;
          isHeld?: boolean; summaryJa?: string }> = {};
        for (const s of scenarioSets) {
          scenarioBySymbol[s.symbol] = { dominant: s.dominant, name: s.assetName,
            isHeld: s.isHeld, summaryJa: s.summaryJa };
        }
        const planBySymbol: Record<string, { planType: string; currentStance: string;
          name?: string; isHeld?: boolean; summaryJa?: string }> = {};
        for (const p of positionPlans) {
          planBySymbol[p.symbol] = { planType: p.planType, currentStance: p.currentStance,
            name: p.assetName, isHeld: p.isHeld, summaryJa: p.summaryJa };
        }
        runNotificationEngine({
          apItems, eventNames: [...new Set((impEvents?.events ?? [])
            .filter((ie) => ie.countdown === 'D' || ie.countdown === 'D-1')
            .map((ie) => ie.eventCode))],
          sdBySymbol, flowBySymbol, scenarioBySymbol, planBySymbol,
          strategyState: portfolioStrategy.noHoldings ? null : {
            tactical: portfolioStrategy.tacticalBudget, single: portfolioStrategy.singleNameRisk,
            theme: portfolioStrategy.themeRisk, fire: portfolioStrategy.fireStatus,
            summaryJa: portfolioStrategy.summaryJa },
          fireCoreState: (() => { const f = latestFireCore(); return f && f.positions.length ? {
            valuation: f.valuationDataStatus, contribution: f.contributionDataStatus,
            ratio: f.tacticalToCoreBand } : null; })(),
          briefSession: sessionBrief.sessionType,
          hasHoldings: !positionExposure.noHoldings,
          snapshotAgeDays: age,
          vaultConfigured: !!localStorage.getItem('argus.vaultPass.v1'),
          restoreVerified: assessBackupSafety(assets).restoreVerified,
        });
      } catch { /* never break Today */ }
    }, 12_000);
    return () => clearTimeout(t);
  }, [apItems, sdSignals, flowRecords, sessionBrief, impEvents, positionExposure, scenarioSets, positionPlans, portfolioStrategy]);

  // v11.22.0: Data Quality — 一度だけ取得し、warning/critical時のみTodayに一行警告。
  // 取得内容はパック/スナップショットにも共有(鮮度注意は私的情報ではない)。
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    const t = setTimeout(() => {
      fetch(backend.replace(/\/$/, '') + '/api/argus/data-quality')
        .then((r) => r.json())
        .then((d) => {
          publishDataQuality({ overallStatus: d.overallStatus, overallStatusJa: d.overallStatusJa,
            topIssuesJa: d.topIssuesJa ?? [],
            expectedDisabledJa: (d.expectedDisabled ?? [])
              .map((x: { sourceName: string; reasonJa: string }) => `${x.sourceName}: ${x.reasonJa}`) });
        })
        .catch(() => { /* Data Qualityページ自体が疎通チェック — Todayは静かに */ });
    }, 5000);
    return () => clearTimeout(t);
  }, []);

  // v11.20.0: AI Review Pack用のイベント一行群(パック内でイベント要約は1回のみ)
  useEffect(() => {
    // v12.0.8 Part B: パックにもイベント名だけでなく日付を必ず含める
    const lines = (impEvents?.events ?? []).slice(0, 6).map((ie) =>
      `${ie.eventCode} ${ie.title} — ${ie.date ?? '日付未確認'}${ie.jstTime ? ` ${String(ie.jstTime).slice(11)}` : ''} (${ie.countdown})${ie.actual ? ` / 結果: ${ie.actual}` : ''}`);
    publishEventsJa(lines);
  }, [impEvents]);

  // v11.11.0: device-local outcome updater — once per JST day, fills
  // 「その後どうなったか」(1d/3d/5d/20d) for past decision records.
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    const t = setTimeout(() => { void maybeUpdateOutcomes(backend); }, 8000);
    return () => clearTimeout(t);
  }, []);


  // ── Judgment log (device-local memory) ──
  // Record today's LIVE/PARTIAL call (mock is never logged — no fake history).
  useEffect(() => {
    if (phase !== 'live' && phase !== 'partial') return;
    recordJudgment({
      date: judgment.date,
      overall: judgment.overall,
      risk: judgment.risk,
      posture: al.data?.marketPosture?.label ?? '—',
      confidence: cappedConf,
      summary: judgment.summary,
      phase,
      updatedAt: judgment.updatedAt,
    });
  }, [phase, judgment, al.data, regime.data]);


  const argusToday = useMemo(() => {
    const usSummary = resolveCommandSummary({
      legacyAction: judgment.overall,
      globalRegime: overlay.globalRegime,
      jpOverlay: 'NORMAL',
      ownerRisk: overlay.holderRiskOverlay,
      risk: judgment.risk,
      isPartial: isPartial || visLimited,
      confidence: cappedConf,
      nextConditionJa: judgment.nextCondition,
    });
    const marketSignal = (market: 'JP' | 'US', fallback: SignalCode): SignalCode => {
      const held = (market === 'JP' ? cardGroups.jpWatch : cardGroups.usWatch)
        .filter((card) => card.held).map((card) => card.signalCode);
      return held.reduce((current, signal) =>
        SIGNALS[signal].level < SIGNALS[current].level ? signal : current, fallback);
    };
    const summary = marketLedger.ledger?.summary ?? {};
    const factorState = (value: string | undefined): '↑' | '→' | '↓' | '△' | '—' | 'JP' | 'US' | 'HIGH' | 'LOW' => {
      if (['INFLOW', 'RISING', 'OVERHEAT_CANDIDATE'].includes(value ?? '')) return '↑';
      if (['OUTFLOW', 'FALLING', 'OVERSOLD_CANDIDATE'].includes(value ?? '')) return '↓';
      if (value === 'HIGH' || value === 'LOW') return value;
      return value && value !== 'UNKNOWN' ? '△' : '—';
    };
    const selectedJpChart = selectedInstrument.JP === '1306' ? topixChart.data : jpChart.data;
    const selectedUsChart = selectedInstrument.US === 'QQQ' ? nasdaqChart.data : sp500Chart.data;
    const shortState = selectedJpChart?.todayIntelligence?.shortSelling;
    const jpFactors = [
      { key: 'TREND' as const, state: regime.data?.regime?.label === 'RISK_ON' ? '↑' as const : regime.data?.regime?.label === 'RISK_OFF' ? '↓' as const : '△' as const, source: 'market-regime' },
      { key: 'BREADTH' as const, state: factorState(summary.breadth), source: 'market-ledger' },
      { key: 'FLOW' as const, state: factorState(summary.foreignFlow), source: 'market-ledger' },
      { key: 'SHORT' as const, state: shortState?.latest?.previousDayDifference == null ? '—' as const
        : shortState.latest.previousDayDifference < 0 ? '↓' as const : '↑' as const,
      source: 'jquants-daily-short-ratio' },
      { key: 'CLOSE' as const, state: '—' as const, source: 'closing-window' },
    ];
    const usBars = selectedUsChart?.indicators.bars ?? [];
    const usLatest = usBars.at(-1);
    const usFactors = [
      { key: 'TREND' as const, state: usLatest?.ma?.['25'] == null ? '—' as const
        : usLatest.close >= usLatest.ma['25']! ? '↑' as const : '↓' as const,
      source: 'us-ohlcv' },
      { key: 'BREADTH' as const, state: '△' as const, source: 'market-regime' },
      { key: 'RELATIVE' as const, state: usBars.length >= 21
        ? (usBars.at(-1)!.close >= usBars.at(-21)!.close ? '↑' as const : '↓' as const)
        : '—' as const,
      source: 'spy-qqq-relative' },
      { key: 'FLOW' as const, state: '—' as const, source: 'us-volume-proxy' },
      { key: 'CLOSE' as const, state: '—' as const, source: 'closing-window' },
    ];
    const eventRows = (impEvents?.events ?? []).map((event) => ({
      id: event.eventId, code: event.eventCode, title: event.title,
      at: event.eventTimeUtc || (event.jstTime
        ? String(event.jstTime).replace(' JST', '').replace(' ', 'T') + ':00+09:00'
        : null),
      impact: event.displayImpact, lifecycle: event.lifecycle,
      descriptionJa: event.rationaleJa,
    }));
    const imminent = (impEvents?.events ?? []).some((event) =>
      (event.daysUntil ?? 99) <= 1 && ['critical', 'high'].includes(event.displayImpact)
      && !['RELEASED', 'RESOLVED'].includes(event.lifecycle));
    const indexMoves: TodayMoveInput[] = [];
    for (const move of [
      marketMove(jpChart.data, 'nikkei'), marketMove(topixChart.data, 'topix'),
      marketMove(sp500Chart.data, 'sp500'), marketMove(nasdaqChart.data, 'nasdaq'),
    ]) if (move) indexMoves.push(move);
    const macroMoves: TodayMoveInput[] = [];
    const addRate = (id: string, label: string, point: NonNullable<typeof rates.data>['us10y'] | undefined, suffix: string, direction?: string) => {
      if (point?.status === 'live' && Number.isFinite(point.latestValue)) macroMoves.push({ id, label,
        value: point.latestValue, previous: point.previousValue, suffix, directionLabel: direction,
        asOf: point.latestDate, status: 'close' });
    };
    addRate('usdjpy', 'USDJPY', rates.data?.usdJpy, '', (rates.data?.usdJpy?.change ?? 0) > 0 ? '円安' : '円高');
    addRate('us10y', 'US10Y', rates.data?.us10y, '%', (rates.data?.us10y?.change ?? 0) > 0 ? '↑' : '↓');
    addRate('vix', 'VIX', rates.data?.vix, '', (rates.data?.vix?.change ?? 0) > 0 ? '↑' : '↓');
    const holdings = apItems.filter((item) => item.isHeld && ['P0', 'P1', 'P2'].includes(item.priorityRank))
      .map((item) => ({ symbol: item.symbol, name: item.assetName,
        rank: item.priorityRank === 'P0' ? 0 : item.priorityRank === 'P1' ? 2 : 5,
        reasonJa: item.whyJa, statusJa: item.priorityRank === 'P0' ? '要確認' : '監視' }));
    for (const risk of positionExposure.risks) holdings.push({ symbol: risk.symbol,
      name: positionExposure.notes[risk.symbol]?.name ?? risk.symbol,
      rank: risk.riskType === 'concentration' ? 1 : risk.riskType === 'event_risk' ? 3 : 4,
      reasonJa: risk.riskType === 'concentration' && positionExposure.notes[risk.symbol]?.weightPct != null
        ? `集中${Math.round(positionExposure.notes[risk.symbol].weightPct!)}%` : risk.whyJa,
      statusJa: ['critical', 'high'].includes(risk.riskLevel) ? '要確認' : '監視' });
    const attention = [
      ...(impEvents?.events ?? []).filter((event) => event.daysUntil === 0 && ['critical', 'high'].includes(event.displayImpact))
        .map((event) => ({ id: event.eventId, label: event.eventCode,
          time: event.jstTime ? String(event.jstTime).slice(11, 16) : null, severity: event.displayImpact === 'critical' ? 5 : 4 })),
      ...events247.filter((event) => event.severity >= 4)
        .map((event) => ({ id: event.eventId, label: event.nameJa || event.symbol || event.eventType,
          time: null, severity: event.severity })),
    ];
    const ledgerRows = new Map((marketLedger.ledger?.table ?? []).map((row) => [row.seriesId, row]));
    const metric = (ids: string[]) => ids.map((id) => ledgerRows.get(id)?.latestValue
      ?? marketLedger.ledger?.derivedMetrics.find((row) => row.metricId === id)?.value)
      .find((value): value is number => typeof value === 'number' && Number.isFinite(value));
    const jpPositioning: TodayPositioningRow[] = [];
    const credit = ledgerRows.get('credit.short_balance');
    if (credit?.latestValue != null) jpPositioning.push({ key: 'credit-numeric', label: '売残',
      value: oku(credit.latestValue), detail: credit.thresholdDistance == null ? undefined
        : `8千億差 ${signed(credit.thresholdDistance / 100_000_000)}億`,
      tone: credit.thresholdSide === 'above' ? 'negative' : 'neutral' });
    const dailyShort = selectedJpChart?.todayIntelligence?.shortSelling?.latest;
    if (dailyShort) jpPositioning.push({ key: 'daily-short-ratio', label: 'SHORT',
      value: `${dailyShort.totalShortRatio.toFixed(1)}%`,
      detail: dailyShort.previousDayDifference == null ? undefined
        : `${dailyShort.previousDayDifference > 0 ? '▲' : dailyShort.previousDayDifference < 0 ? '▼' : '→'}${Math.abs(dailyShort.previousDayDifference).toFixed(1)}pt`,
      tone: (dailyShort.previousDayDifference ?? 0) > 0 ? 'negative' : 'positive' });
    const foreign = ledgerRows.get('flow.foreign');
    if (foreign?.fourPeriodTotal != null) jpPositioning.push({ key: 'foreign-4w', label: '海外4週',
      value: oku(foreign.fourPeriodTotal), detail: foreign.fourPeriodDirection === 'up' ? '↑' : foreign.fourPeriodDirection === 'down' ? '↓' : '→',
      tone: foreign.fourPeriodTotal > 0 ? 'positive' : foreign.fourPeriodTotal < 0 ? 'negative' : 'neutral' });
    const ratio6 = metric(['breadth.prime.ratio6', 'breadth.ratio6']);
    const ratio25 = metric(['breadth.prime.ratio25', 'breadth.ratio25']);
    if (ratio6 != null || ratio25 != null) jpPositioning.push({ key: 'breadth-ratios', label: '騰落比率',
      value: [ratio6 == null ? null : `6日${ratio6.toFixed(0)}`, ratio25 == null ? null : `25日${ratio25.toFixed(0)}`].filter(Boolean).join(' / ') });
    const jpRs = jpChart.data?.relativeStrength?.nikkei_sp500?.change20Pct;
    if (jpRs != null) jpPositioning.push({ key: 'relative-numeric', label: '日米強弱',
      value: jpRs >= 0 ? 'JP優位' : 'US優位', detail: `${signed(jpRs, 1)}pt`,
      tone: jpRs >= 0 ? 'positive' : 'negative' });

    const usPositioning: TodayPositioningRow[] = [];
    const change20 = (payload: ChartIntelligencePayload | null) => {
      const bars = payload?.indicators.bars.filter((bar) => bar.close > 0) ?? [];
      return bars.length >= 21 ? (bars.at(-1)!.close / bars.at(-21)!.close - 1) * 100 : null;
    };
    const qqq20 = change20(nasdaqChart.data), spy20 = change20(sp500Chart.data);
    if (qqq20 != null && spy20 != null) usPositioning.push({ key: 'us-relative-numeric', label: 'NASDAQ対SPY',
      value: `${signed(qqq20 - spy20, 1)}pt`, detail: qqq20 >= spy20 ? 'NASDAQ優位' : 'SPY優位',
      tone: qqq20 >= spy20 ? 'positive' : 'negative' });
    const usVolume = selectedUsChart?.indicators.bars.at(-1)?.volumeRatio20;
    if (usVolume != null) usPositioning.push({ key: 'us-volume-regime', label: '出来高',
      value: `${usVolume.toFixed(2)}×`, detail: usVolume >= 1.2 ? '増加' : usVolume <= .8 ? '低調' : '平常',
      tone: usVolume >= 1.2 ? 'positive' : 'neutral' });
    const positioning = { JP: jpPositioning, US: usPositioning };
    const news = selectTodayNews((marketNews.data?.items ?? []).map((item, index) => ({
      id: `${item.datetime ?? index}:${item.url}`, titleJa: item.displayTitleJa ?? '',
      titleOriginal: item.titleOriginal ?? item.headline, source: item.source, url: item.url,
      publishedAt: item.datetime, major: item.major, relevant: item.relevant,
      translationStatus: item.translationStatus, tier: item.tier, corroboration: item.corroboration,
      linkedSymbols: item.linkedSymbols,
    })), assets.map((asset) => asset.symbol));
    const backup = assessBackupSafety(assets);
    const previous = previousJudgment(judgment.date);
    return buildArgusTodayView({
      now: new Date(), selectionMode: marketMode,
      calendar: marketLedger.ledger?.phase3?.calendar,
      baseSignal: commandSummary.signalCode,
      jpSignal: marketSignal('JP', commandSummary.signalCode),
      usSignal: marketSignal('US', usSummary.signalCode),
      confidence: cappedConf, dataQuality: commandSummary.dataQuality,
      ownerPolicyLimit: positionRisk.alert ? 'REVIEW' : null,
      eventHardVeto: { JP: imminent, US: imminent },
      factors: { JP: jpFactors, US: usFactors },
      evidence: { JP: judgment.reasons, US: judgment.reasons },
      events: eventRows, indexMoves, macroMoves, positioning, attention, holdings, news,
      newsCardState: {
        status: marketNews.data?.status ?? 'unavailable',
        lastChecked: marketNews.lastChecked,
        lastSuccessfulPollAt: marketNews.data?.lastSuccessfulPollAt
          ?? (marketNews.data?.status === 'live' ? marketNews.data.asOf : null),
        fetchedCount: marketNews.data?.fetchedCount ?? marketNews.data?.items.length ?? 0,
        relevantCount: news.length,
        stale: marketNews.data?.stale ?? marketNews.data?.status !== 'live',
        failureClass: marketNews.failureClass,
      },
      projection: {
        JP: projectionInput(selectedJpChart),
        US: projectionInput(selectedUsChart),
      },
      review: previous ? {
        JP: reviewFor(selectedJpChart, previous.overall, previous.date),
        US: reviewFor(selectedUsChart, previous.overall, previous.date),
      } : undefined,
      selectedInstrument,
      systemStatus: { data: commandSummary.dataQuality, backup: backup.protectionLevelJa,
        rule: al.data?.status === 'live' ? 'DETERMINISTIC' : 'RULE TEMPORARY' },
      conciseAction: apItems.find((item) => item.isHeld && ['P0', 'P1'].includes(item.priorityRank))?.actionLabelJa
        ?? sessionBrief.bullets[0] ?? null,
      conciseAvoid: sessionBrief.whatNotToDoJa[0] ?? null,
    });
  }, [judgment, overlay, isPartial, visLimited, cappedConf, cardGroups, marketLedger.ledger,
    regime.data, impEvents, rates.data, apItems, positionExposure, events247,
    commandSummary, positionRisk, assets, al.data, sessionBrief, marketMode,
    jpChart.data, topixChart.data, sp500Chart.data, nasdaqChart.data, marketNews.data,
    marketNews.lastChecked, marketNews.failureClass,
    selectedInstrument]);


  return (
    <PageShell
      title={tEn('page.today')}
      subtitle={<span>{formatDate(judgment.date)}</span>}
    >
      <ArgusTodayPanel view={argusToday} onMode={changeMarketMode}
        onInstrument={changeInstrument}
        onNavigate={onNavigate} onOpenAsset={(symbol) => onNavigateToAsset?.(symbol)}
        aiButton={<ProHandoffButton nextEvent={argusToday.nextEvent} />} />
      <MobileStickyCommand text={argusToday.footerText} />
    </PageShell>
  );
};

import React, { useEffect, useMemo, useState } from 'react';
import { PageShell } from './PageShell';
import { useLocale, tEn } from '../i18n';
import { recordJudgment } from '../lib/judgmentLog';
import { useLedgerSummary } from '../hooks/useLedgerSummary';
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
import { buildArgusTodayView, type MarketSelectionMode, type TodayRecommendationInput } from '../domain/argusTodayView';
import { resolveCommandSummary } from '../domain/commandSummary';
import { SIGNALS, type SignalCode } from '../domain/actionLevel';
import { useMarketLedger } from '../hooks/useMarketLedger';

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

export const CommandCenter: React.FC<Props> = ({ onNavigate, onNavigateToAsset }) => {
  useLocale();   // re-render Today on locale switch
  const ledger = useLedgerSummary();
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
  const [recommendations, setRecommendations] = useState<TodayRecommendationInput[]>([]);
  useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    fetch(backend.replace(/\/$/, '') + '/api/argus/buy-candidates')
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then((data) => { if (alive) setRecommendations((data.items ?? []).slice(0, 3)
        .map((item: { symbol: string; entryJa?: string; thesisJa?: string; conviction?: number }, index: number) => ({
          symbol: item.symbol, labelJa: (item.entryJa || item.thesisJa || '小さく検討').slice(0, 20),
          rank: index + 1 - Math.min(0.9, item.conviction ?? 0),
        }))); })
      .catch(() => { /* quiet empty state; no synthetic candidate */ });
    return () => { alive = false; };
  }, []);
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
    const sharedFactors = [
      { key: 'TREND' as const, state: regime.data?.regime?.label === 'RISK_ON' ? '↑' as const : regime.data?.regime?.label === 'RISK_OFF' ? '↓' as const : '△' as const, source: 'market-regime' },
      { key: 'BREADTH' as const, state: factorState(summary.breadth), source: 'market-ledger' },
      { key: 'FLOW' as const, state: factorState(summary.foreignFlow), source: 'market-ledger' },
      { key: 'CREDIT' as const, state: factorState(summary.shortFuel), source: 'market-ledger' },
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
    const moves = [] as Array<{ id: string; label: string; value: number; previous?: number | null; suffix?: string; directionLabel?: string; asOf?: string | null }>;
    const addRate = (id: string, label: string, point: NonNullable<typeof rates.data>['us10y'] | undefined, suffix: string, direction?: string) => {
      if (point?.status === 'live' && Number.isFinite(point.latestValue)) moves.push({ id, label,
        value: point.latestValue, previous: point.previousValue, suffix, directionLabel: direction,
        asOf: point.latestDate });
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
    const positioning = [
      { key: 'credit', label: '信用', value: factorState(summary.shortFuel) },
      { key: 'flow', label: '海外', value: factorState(summary.foreignFlow) },
      { key: 'breadth', label: '幅', value: factorState(summary.breadth) },
      { key: 'relative', label: '強弱', value: '—' },
      { key: 'value', label: '評価', value: summary.valuationBand === 'HIGH_VALUATION_BAND' ? '高' : summary.valuationBand === 'UNKNOWN' ? '—' : '中' },
    ];
    const backup = assessBackupSafety(assets);
    const reviewOverall = ledger.data?.overall;
    return buildArgusTodayView({
      now: new Date(), selectionMode: marketMode,
      calendar: marketLedger.ledger?.phase3?.calendar,
      baseSignal: commandSummary.signalCode,
      jpSignal: marketSignal('JP', commandSummary.signalCode),
      usSignal: marketSignal('US', usSummary.signalCode),
      confidence: cappedConf, dataQuality: commandSummary.dataQuality,
      ownerPolicyLimit: positionRisk.alert ? 'REVIEW' : null,
      eventHardVeto: { JP: imminent, US: imminent },
      factors: { JP: sharedFactors, US: sharedFactors },
      evidence: { JP: judgment.reasons, US: judgment.reasons },
      events: eventRows, marketMoves: moves, positioning, attention, holdings,
      concentration: positionExposure.noHoldings ? null : {
        risk: positionExposure.singleNameRisk ?? 'unknown',
        topTwoPct: positionExposure.base.holdings.length > 1
          ? Object.values(positionExposure.notes).filter((note) => note.held)
            .map((note) => note.weightPct ?? 0).sort((a, b) => b - a).slice(0, 2).reduce((a, b) => a + b, 0)
          : positionExposure.top1Pct,
      },
      recommendations, totalAssetJpy: positionExposure.base.combinedJpy,
      review: reviewOverall ? {
        result: (reviewOverall.hitRate ?? 0) >= 0.5 ? '○' : '△',
        quality: reviewOverall.n >= 20 ? '○' : '△',
      } : null,
      systemStatus: { data: commandSummary.dataQuality, backup: backup.protectionLevelJa,
        rule: al.data?.status === 'live' ? 'DETERMINISTIC' : 'RULE TEMPORARY' },
      conciseAction: apItems.find((item) => item.isHeld && ['P0', 'P1'].includes(item.priorityRank))?.actionLabelJa
        ?? sessionBrief.bullets[0] ?? null,
      conciseAvoid: sessionBrief.whatNotToDoJa[0] ?? null,
    });
  }, [judgment, overlay, isPartial, visLimited, cappedConf, cardGroups, marketLedger.ledger,
    regime.data, impEvents, rates.data, apItems, positionExposure, events247, recommendations,
    ledger.data, commandSummary, positionRisk, assets, al.data, sessionBrief, marketMode]);


  return (
    <PageShell
      title={tEn('page.today')}
      subtitle={<span>{formatDate(judgment.date)}</span>}
    >
      <ArgusTodayPanel view={argusToday} onMode={changeMarketMode}
        onNavigate={onNavigate} onOpenAsset={(symbol) => onNavigateToAsset?.(symbol)}
        aiButton={<ProHandoffButton nextEvent={argusToday.nextEvent} />} />
      <MobileStickyCommand text={argusToday.footerText} />
    </PageShell>
  );
};

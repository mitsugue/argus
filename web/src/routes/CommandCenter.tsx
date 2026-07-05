import React, { useEffect, useMemo, useState } from 'react';
import { PageShell } from './PageShell';
import { HeroCard } from '../components/dashboard/HeroCard';
import { AssetCategorySection } from '../components/dashboard/AssetCategorySection';
import { FxMacroSection } from '../components/dashboard/FxMacroSection';
import { CaosHub } from '../components/dashboard/CaosHub';
import { FlowAttributionSection } from '../components/dashboard/FlowAttributionSection';
import { BuyCandidates } from '../components/dashboard/BuyCandidates';
import { useDownsideIncidents } from '../hooks/useDownsideIncidents';
import { useVisibilityGuard } from '../hooks/useVisibilityGuard';
import { useEventsActive } from '../hooks/useEventsActive';
import { useImportantEvents } from '../hooks/useImportantEvents';
import { groupAssetCards, type LinkedEventTag, type AiFreshness } from '../domain/assetCard';
import { useLocale, t, tEn } from '../i18n';
import { MarketSessionLamps } from '../components/dashboard/MarketSessionLamps';
import { ActionPill } from '../components/action/ActionBadge';
import { recordJudgment, previousJudgment, recentJudgments } from '../lib/judgmentLog';
import { useLedgerSummary } from '../hooks/useLedgerSummary';
import { useAIJudgment } from '../hooks/useAIJudgment';
import { useActionLabels } from '../hooks/useActionLabels';
import { useMarketRegime } from '../hooks/useMarketRegime';
import { useEventRadar } from '../hooks/useEventRadar';
import { useAssets } from '../hooks/useAssets';
import { useRatesSnapshot } from '../hooks/useRatesSnapshot';
import { useJapanWatchlist } from '../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../hooks/useUSWatchlist';
import { useFlowAttributionList } from '../hooks/useFlowAttribution';
import { useSupplyDemandList } from '../hooks/useSupplyDemand';
import { SupplyDemandSection } from '../components/dashboard/SupplyDemandSection';
import { buildPositionExposure } from '../domain/positionExposure';
import { publishExposure, publishActionPriorities, latestActionPriorities, publishSessionBrief, latestSessionBrief, publishScenarios, publishPlans, publishStrategy, publishFireCore, latestFireCore, publishEventsJa } from '../lib/positionExposureShare';
import { maybeDailySnapshot } from '../lib/portfolioSync';
import { maybeUpdateOutcomes, listDQ } from '../lib/decisionQuality';
import { buildItem as buildAPItem, rankItems as rankAPItems, type APItem } from '../domain/actionPriority';
import { ActionPrioritySection } from '../components/dashboard/ActionPrioritySection';
import { buildLocalBrief } from '../domain/sessionBrief';
import { buildScenarioSet, type LocalScenarioSet } from '../domain/scenario';
import { buildPlan, marketOpenNow, type LocalPlan } from '../domain/positionPlan';
import { PositionPlanSection } from '../components/dashboard/PositionPlanSection';
import { ProHandoffButton } from '../components/dashboard/ProHandoffButton';
import { CollapsibleSection } from '../components/common/CollapsibleSection';
import { MobileStickyCommand } from '../components/dashboard/MobileStickyCommand';
import { unreadCounts } from '../lib/notifications';
import { classifyRole, buildStrategy, todayStrategicNoteJa, type LocalStrategy } from '../domain/portfolioStrategy';
import { themeOf } from '../domain/positionExposure';
import { buildLocalFireCore, fireCoreTodayNoteJa } from '../lib/fireCore';
import { SessionBriefSection } from '../components/dashboard/SessionBriefSection';
import { runNotificationEngine, listNotifications, SEV_TONE, SEV_JA } from '../lib/notifications';
import { assessBackupSafety } from '../lib/backupSafety';
import { listSnapshots } from '../lib/portfolioSync';
import { PositionRiskSection } from '../components/dashboard/PositionRiskSection';
import { useCryptoWatchlist } from '../hooks/useCryptoWatchlist';
import { coingeckoIdOf } from '../lib/cryptoIds';
import {
  deriveTodayJudgment, combinePhase,
  type TodayPhase,
} from '../lib/todayCall';
import type { RouteKey } from '../components/NavRail';
import '../components/dashboard/Dashboard.css';

interface Props {
  onNavigate: (key: RouteKey) => void;
}

// Today is a SUMMARY composed from LIVE data (action-labels + market-regime +
// events). Detail lives on the respective detail pages.
const formatDate = (iso: string) => {
  const d = new Date(`${iso}T00:00:00+09:00`);
  return d.toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  });
};

export const CommandCenter: React.FC<Props> = ({ onNavigate }) => {
  useLocale();   // re-render Today on locale switch
  const { assets } = useAssets();
  const ledger = useLedgerSummary();
  const aiJ = useAIJudgment();
  const aiStateJa = useMemo(() => {
    if (aiJ.phase === 'connecting') return null;
    if (aiJ.data && (aiJ.data.status === 'live' || aiJ.data.status === 'partial')) {
      // v10.36 (#4): distinguish fresh / persisted / stale + show the models, so
      // a lapsed 30-min cache doesn't read as "AI doesn't exist".
      const d = aiJ.data as typeof aiJ.data & {
        freshness?: string; ageMin?: number | null;
        models?: { primary?: string | null; checker?: string | null };
      };
      const t = Date.parse(aiJ.data.asOf);
      const m = d.ageMin ?? (Number.isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 60000)) : null);
      const age = m == null ? '' : m < 60 ? `${m}分前` : m < 1440 ? `${Math.round(m / 60)}時間前` : `${Math.round(m / 1440)}日前`;
      const tag = d.freshness === 'fresh' ? '最新' : d.freshness === 'persisted' ? '保持中(前回成功)'
        : d.freshness === 'stale' ? '古い' : aiJ.data.status;
      const models = d.models?.primary ? ` [${d.models.primary}+${d.models.checker}]` : '';
      return `🤖 AI見解: ${age}の実行・${tag}${models}。ルール判定が主・AIは時刻付きの第二意見。次回 平日16:05。`;
    }
    return '🤖 AI見解: まだ未実行(平日16:05に自動実行。それまではルール判定で稼働中)。';
  }, [aiJ.data, aiJ.phase]);
  // The engine follows the USER's actual watchlist (dynamic symbols, v9.8).
  const jpSyms = useMemo(() => assets.filter((a) => a.market === 'JP').map((a) => a.symbol), [assets]);
  const usSyms = useMemo(() => assets.filter((a) => a.market === 'US').map((a) => a.symbol), [assets]);
  const al = useActionLabels({ jp: jpSyms, us: usSyms });
  // Crypto has no Action Label; pull its live quote separately so the top-screen
  // crypto cards show the day-change like JP/US (was always "—" before).
  const cryptoAssets = useMemo(() => assets.filter((a) => a.market === 'CRYPTO'), [assets]);
  const cryptoIds = useMemo(
    () => cryptoAssets.map((a) => coingeckoIdOf(a)).filter(Boolean),
    [cryptoAssets]);
  const cw = useCryptoWatchlist(cryptoIds);
  const cryptoQuotes = useMemo(() => {
    const m: Record<string, { price?: number | null; changePct?: number | null }> = {};
    for (const a of cryptoAssets) {
      const id = coingeckoIdOf(a);
      const q = id ? cw.byId?.[id] : undefined;
      if (q) m[a.symbol.toUpperCase()] = { price: q.priceUsd ?? null, changePct: q.changePct ?? null };
    }
    return m;
  }, [cryptoAssets, cw.byId]);
  const regime = useMarketRegime();
  const ev = useEventRadar();
  const { data: downside } = useDownsideIncidents();
  const guard = useVisibilityGuard();   // Visibility Risk Guard (v10.195)
  const { events: events247 } = useEventsActive();
  const { data: impEvents } = useImportantEvents();

  // Unified per-stock cards (v10.140): merge action-labels + downside + 24/7 events
  // + linked macro-event tags into ONE card per stock, grouped + sorted per market.
  const cardGroups = useMemo(() => {
    const linked: Record<string, LinkedEventTag[]> = {};
    for (const ie of impEvents?.events ?? []) {
      for (const a of ie.linkedAssets ?? []) {
        const k = String(a).toUpperCase();
        (linked[k] ??= []).push({ code: ie.eventCode, countdown: ie.countdown, impact: ie.displayImpact.toUpperCase() });
      }
    }
    const aiF = aiJ.data as undefined | { freshness?: string; status?: string };
    const aiFreshness: AiFreshness = aiF?.freshness === 'fresh' ? 'fresh'
      : aiF?.freshness === 'persisted' || aiF?.freshness === 'stale' ? 'stale'
      : aiJ.data ? 'unavailable' : 'rule_only';
    // (a) AI-AS-PRIMARY (v10.160): when a recent AI run exists (live/partial + fresh/
    // persisted), the displayed per-stock call IS the GPT+Gemini arbitrated judgment
    // (aiFinalAction + the AI's reason). The rule engine is the guardrail fallback
    // (stale/cold/budget-paused → shown as ルール暫定). Holdings stay device-local;
    // this only swaps which judgment the card shows.
    const aiPrimary = !!aiJ.data && (aiF?.status === 'live' || aiF?.status === 'partial')
      && (aiF?.freshness === 'fresh' || aiF?.freshness === 'persisted');
    const aiBySym = new Map((aiJ.data?.labels ?? []).map((l) => [l.symbol.toUpperCase(), l]));
    const labels = (al.data?.labels ?? []).map((rl) => {
      const ai = aiPrimary ? aiBySym.get(rl.symbol.toUpperCase()) : undefined;
      if (ai && ai.aiFinalAction) {
        return { ...rl, action: ai.aiFinalAction, reasonJa: ai.reasonJa || rl.reasonJa,
                 confidence: ai.confidence ?? rl.confidence, judgmentSource: 'ai' as const };
      }
      return { ...rl, judgmentSource: 'rule' as const };
    });
    return groupAssetCards({
      assets, labels, incidents: downside?.incidents ?? [],
      events: events247 ?? [], linked, aiFreshness, cryptoQuotes,
    });
  }, [assets, al.data, downside, events247, impEvents, aiJ.data, cryptoQuotes]);

  // OWNER CRITICAL (spec): a held asset on the most defensive signals (EXIT/DEFEND)
  // gets a small top banner so a held emergency is never buried below the fold.
  const ownerCritical = useMemo(() =>
    [...cardGroups.jpWatch, ...cardGroups.usWatch, ...cardGroups.crypto]
      .filter((c) => c.held && (c.signalCode === 'EXIT' || c.signalCode === 'DEFEND')),
    [cardGroups]);

  // ── V11.8.0 Position / Exposure — device-local. Prices come from the cards
  // already built for Today; quantities/costs never leave localStorage.
  const rates = useRatesSnapshot();
  const { records: flowRecords } = useFlowAttributionList();
  const { signals: sdSignals } = useSupplyDemandList();   // v11.10.0 需給ランク(JP)
  // Card prices vanish outside sessions (labels carry no price) — fall back to
  // the same real quote hooks Core Portfolio uses (delayed close = real data).
  const peJpSyms = useMemo(() => assets.filter((a) => a.market === 'JP').map((a) => a.symbol), [assets]);
  const peUsSyms = useMemo(() => assets.filter((a) => a.market === 'US').map((a) => a.symbol), [assets]);
  const peJp = useJapanWatchlist(peJpSyms);
  const peUs = useUSWatchlist(peUsSyms);
  const positionExposure = useMemo(() => {
    const priceMap = new Map<string, number>();
    const okSt = (st?: string) => st != null && st !== 'mock';
    for (const s of peJp.data?.stocks ?? []) if (okSt(s.status) && Number.isFinite(s.price)) priceMap.set(s.symbol.toUpperCase(), s.price);
    for (const s of peUs.data?.stocks ?? []) if (okSt(s.status) && Number.isFinite(s.price)) priceMap.set(s.symbol.toUpperCase(), s.price);
    for (const c of [...cardGroups.jpWatch, ...cardGroups.usWatch, ...cardGroups.crypto]) {
      if (c.price != null && Number.isFinite(c.price)) priceMap.set(c.symbol.toUpperCase(), c.price);
    }
    const flowBySymbol: Record<string, string> = {};
    for (const r of flowRecords) flowBySymbol[r.symbol.toUpperCase()] = r.flowClass;
    const eventSymbols = new Set<string>();
    for (const ie of impEvents?.events ?? []) {
      if (ie.countdown === 'D' || ie.countdown === 'D-1') {
        for (const a of ie.linkedAssets ?? []) eventSymbols.add(String(a).toUpperCase());
      }
    }
    const regLabel = regime.data?.regime?.label ?? null;
    const sdRankBySymbol: Record<string, string> = {};
    for (const s of sdSignals) sdRankBySymbol[s.symbol.toUpperCase()] = s.supplyDemandRank;
    const pe = buildPositionExposure(
      assets,
      (a) => priceMap.get(a.symbol.toUpperCase()),
      rates.data?.usdJpy?.latestValue ?? null,
      { regimeLabel: regLabel, riskOff: regLabel === 'RISK_OFF' || regLabel === 'EVENT_WAIT',
        flowBySymbol, eventSymbols, sdRankBySymbol },
    );
    publishExposure(pe);   // Pro Handoff / AI Review read this at copy time (device-local)
    return pe;
  }, [assets, cardGroups, rates.data, flowRecords, sdSignals, impEvents, regime.data, peJp.data, peUs.data]);

  // v11.12.0: ACTION PRIORITY — 全レイヤーを「今日これを見る」に統合(端末内・保有加味)。
  const apItems: APItem[] = useMemo(() => {
    const sdBySym = new Map(sdSignals.map((s) => [s.symbol.toUpperCase(), s]));
    const flowBySym = new Map(flowRecords.map((r) => [r.symbol.toUpperCase(), r]));
    const riskBySym = new Map(positionExposure.risks.map((r) => [r.symbol, r.riskLevel]));
    const regLabel = regime.data?.regime?.label ?? null;
    const riskOff = regLabel === 'RISK_OFF' || regLabel === 'EVENT_WAIT';
    const eventSyms = new Map<string, string>();
    for (const ie of impEvents?.events ?? []) {
      if (ie.countdown === 'D' || ie.countdown === 'D-1') {
        for (const a of ie.linkedAssets ?? []) eventSyms.set(String(a).toUpperCase(), ie.eventCode);
      }
    }
    // DQ modifier (modest): symbols whose past avoid_chase was contradicted
    const dqContra = new Set<string>();
    const dqSupp = new Set<string>();
    for (const r of listDQ()) {
      const it = r.outcome?.outcomeInterpretation;
      if (r.decisionContext === 'avoid_chase' && it === 'contradicted') dqContra.add(r.symbol.toUpperCase());
      if (it === 'supported') dqSupp.add(r.symbol.toUpperCase());
    }
    const items = assets.map((a) => {
      const sym = a.symbol.toUpperCase();
      const note = positionExposure.notes[sym];
      const sd = sdBySym.get(sym);
      const fl = flowBySym.get(sym);
      const missing: string[] = [];
      if (note?.held && note.pnlPct == null) missing.push(a.avgCost == null ? '取得単価' : '価格');
      return buildAPItem({
        symbol: sym, market: a.market, assetName: a.displayNameJa || a.displayName,
        isHeld: !!note?.held, weightPct: note?.weightPct ?? null,
        concentrationRisk: positionExposure.top1Symbol === sym ? positionExposure.singleNameRisk : null,
        positionRiskLevel: riskBySym.get(sym) ?? null,
        readiness: note?.readiness ?? null,
        sdRank: sd?.supplyDemandRank ?? null, sdCondition: sd?.condition ?? null,
        flowClass: fl?.flowClass ?? null,
        eventPending: eventSyms.has(sym), eventName: eventSyms.get(sym) ?? null,
        regimeRiskOff: riskOff, changePct: fl?.changePct ?? null,
        dataMissing: missing,
        dqContradictedAvoidChase: dqContra.has(sym), dqSupported: dqSupp.has(sym),
      });
    });
    const ranked = rankAPItems(items, 20);
    publishActionPriorities(ranked);   // Handoff/AIReview read at copy time
    return ranked;
  }, [assets, positionExposure, sdSignals, flowRecords, impEvents, regime.data]);

  // v11.13.0: SESSION BRIEF — 今日の作戦(端末内合成・保有加味)。
  const sessionBrief = useMemo(() => {
    const eventNames: string[] = [];
    for (const ie of impEvents?.events ?? []) {
      if (ie.countdown === 'D' || ie.countdown === 'D-1') eventNames.push(ie.eventCode);
    }
    const regLabel = regime.data?.regime?.label ?? null;
    const missing: string[] = [];
    if (!positionExposure.noHoldings && positionExposure.unpriced.length) {
      missing.push(`価格未取得: ${positionExposure.unpriced.slice(0, 2).join('/')}`);
    }
    const b = buildLocalBrief(apItems, {
      eventNames: [...new Set(eventNames)].slice(0, 3),
      riskOff: regLabel === 'RISK_OFF' || regLabel === 'EVENT_WAIT',
      missingDataJa: missing,
    });
    publishSessionBrief(b);
    return b;
  }, [apItems, impEvents, regime.data, positionExposure]);

  // v11.17.0: SCENARIOS — 条件付きの分岐(端末内合成・保有加味)。単一予測ではなく
  // ベース/強気/弱気/踏み上げ失速/イベント待ちを全レイヤーから決定論合成。帯のみ。
  const scenarioSets: LocalScenarioSet[] = useMemo(() => {
    const sdBySym = new Map(sdSignals.map((s) => [s.symbol.toUpperCase(), s]));
    const flowBySym = new Map(flowRecords.map((r) => [r.symbol.toUpperCase(), r]));
    const riskBySym = new Map(positionExposure.risks.map((r) => [r.symbol, r.riskLevel]));
    const regLabel = regime.data?.regime?.label ?? null;
    const riskOff = regLabel === 'RISK_OFF' || regLabel === 'EVENT_WAIT';
    const eventSyms = new Map<string, string>();
    for (const ie of impEvents?.events ?? []) {
      if (ie.countdown === 'D' || ie.countdown === 'D-1') {
        for (const a of ie.linkedAssets ?? []) eventSyms.set(String(a).toUpperCase(), ie.eventCode);
      }
    }
    const sets = assets.map((a) => {
      const sym = a.symbol.toUpperCase();
      const sd = sdBySym.get(sym);
      const fl = flowBySym.get(sym);
      return buildScenarioSet({
        symbol: sym, market: a.market, assetName: a.displayNameJa || a.displayName,
        isHeld: !!positionExposure.notes[sym]?.held,
        sdRank: sd?.supplyDemandRank ?? null, sdCondition: sd?.condition ?? null,
        sdLevel: (sd as { supplyDemandLevel?: string } | undefined)?.supplyDemandLevel ?? null,
        sdDirection: (sd as { direction?: string } | undefined)?.direction ?? null,
        flowClass: fl?.flowClass ?? null,
        eventPending: eventSyms.has(sym), eventName: eventSyms.get(sym) ?? null,
        regimeRiskOff: riskOff, changePct: fl?.changePct ?? null,
        positionRiskLevel: riskBySym.get(sym) ?? null,
        missing: sd || fl ? [] : ['需給/フロー未取得'],
      });
    });
    publishScenarios(sets);   // Handoff/AIReview/Regime/CorePortfolio read at render/copy time
    return sets;
  }, [assets, positionExposure, sdSignals, flowRecords, impEvents, regime.data]);

  // v11.19.0: PORTFOLIO STRATEGY — 役割分類(コア/サテライト/戦術枠/ヘッジ)と
  // FIRE整合・リスク予算を端末内で合成。計画層(下)へ制約を供給する。
  const portfolioStrategy: LocalStrategy = useMemo(() => {
    const eventSyms = new Set<string>();
    for (const ie of impEvents?.events ?? []) {
      if (ie.countdown === 'D' || ie.countdown === 'D-1') {
        for (const a of ie.linkedAssets ?? []) eventSyms.add(String(a).toUpperCase());
      }
    }
    const roles = assets.map((a) => {
      const sym = a.symbol.toUpperCase();
      const note = positionExposure.notes[sym];
      return classifyRole({
        symbol: sym, assetName: a.displayNameJa || a.displayName,
        theme: themeOf(a), assetType: a.assetType,
        isHeld: !!note?.held, weightPct: note?.weightPct ?? null,
        concentrationRisk: positionExposure.top1Symbol === sym ? positionExposure.singleNameRisk : null,
        eventPending: eventSyms.has(sym),
      });
    });
    // v11.19.1: FIRE Core(投信=本丸資産)を先に合成し、戦略へ文脈供給
    const fc = buildLocalFireCore(assets, positionExposure, roles);
    publishFireCore(fc);
    const s = buildStrategy(positionExposure, roles, {
      eventPending: eventSyms.size > 0,
      recurringAccumulationKnown: fc.contributionDataStatus === 'complete',
      fireCore: { known: fc.fireCoreTotal != null,
        tacticalToCoreBand: fc.tacticalToCoreBand,
        contributionKnown: fc.contributionDataStatus === 'complete' },
    });
    publishStrategy(s);   // CorePortfolio/Handoff/AIReview read at render/copy time
    return s;
  }, [assets, positionExposure, impEvents]);

  // v11.18.0: POSITION PLAN — 「入っていいか/買い増しか/利確検討か/持ち越しか」を
  // 計画として合成(端末内・保有加味・執行語なし)。売買指示ではない。
  const positionPlans: LocalPlan[] = useMemo(() => {
    const sdBySym = new Map(sdSignals.map((s) => [s.symbol.toUpperCase(), s]));
    const flowBySym = new Map(flowRecords.map((r) => [r.symbol.toUpperCase(), r]));
    const scBySym = new Map(scenarioSets.map((s) => [s.symbol, s]));
    const apBySym = new Map(apItems.map((it) => [it.symbol, it]));
    const riskBySym = new Map(positionExposure.risks.map((r) => [r.symbol, r.riskLevel]));
    const regLabel = regime.data?.regime?.label ?? null;
    const eventSyms = new Map<string, string>();
    for (const ie of impEvents?.events ?? []) {
      if (ie.countdown === 'D' || ie.countdown === 'D-1') {
        for (const a of ie.linkedAssets ?? []) eventSyms.set(String(a).toUpperCase(), ie.eventCode);
      }
    }
    const tacticalStretched = ['stretched', 'exceeded'].includes(portfolioStrategy.tacticalBudget);
    const themeHigh = ['high', 'critical'].includes(portfolioStrategy.themeRisk);
    const roleBySym = new Map(portfolioStrategy.roles.map((r) => [r.symbol, r]));
    const plans = assets.map((a) => {
      const sym = a.symbol.toUpperCase();
      const note = positionExposure.notes[sym];
      const sd = sdBySym.get(sym);
      const fl = flowBySym.get(sym);
      const role = roleBySym.get(sym);
      const aiTheme = role ? ['ai_infrastructure', 'physical_ai_robotics', 'semiconductor_photonics'].includes(role.theme) : false;
      return buildPlan({
        symbol: sym, market: a.market, assetName: a.displayNameJa || a.displayName,
        isHeld: !!note?.held,
        sdRank: sd?.supplyDemandRank ?? null, sdCondition: sd?.condition ?? null,
        sdLevel: (sd as { supplyDemandLevel?: string } | undefined)?.supplyDemandLevel ?? null,
        flowClass: fl?.flowClass ?? null,
        scenarioDominant: scBySym.get(sym)?.dominant ?? null,
        apCategory: apBySym.get(sym)?.category ?? null,
        eventPending: eventSyms.has(sym), eventName: eventSyms.get(sym) ?? null,
        regimeRiskOff: regLabel === 'RISK_OFF' || regLabel === 'EVENT_WAIT',
        weightPct: note?.weightPct ?? null,
        concentrationRisk: positionExposure.top1Symbol === sym ? positionExposure.singleNameRisk : null,
        positionRiskLevel: riskBySym.get(sym) ?? null,
        pnlPct: note?.pnlPct ?? null,
        priorRunupPct: null,
        marketOpen: marketOpenNow(a.market),
        missing: sd || fl ? [] : ['需給/フロー未取得'],
        portfolioTacticalStretched: tacticalStretched,
        themeConcentrationHigh: themeHigh && aiTheme,
      });
    });
    // v11.19.0: 戦略上の役割をカード表示用に付与(端末内のみ)
    // v11.19.1: 投信はFIRE Core注記(積立/評価額の鮮度)を追記
    const fcPos = new Map((latestFireCore()?.positions ?? []).map((x) => [x.symbol, x]));
    for (const p of plans) {
      const r = roleBySym.get(p.symbol);
      if (r) {
        let reason = r.roleReasonJa;
        const fp = fcPos.get(p.symbol);
        if (fp) {
          reason = `FIRE Core(本丸資産)。積立${fp.monthlyContribution != null ? `月${fp.monthlyContribution.toLocaleString()}円` : '未入力'}`
            + `・評価額${fp.marketValue != null ? (fp.stale ? '更新が古い' : '追跡中') : '未入力'}(${fp.accountTypeJa})`;
        }
        p.strategicRole = { roleJa: fp ? 'FIRE Core' : r.roleJa, roleReasonJa: reason,
          addPolicyJa: r.addPolicyJa, strategyFit: r.strategyFit };
      }
    }
    publishPlans(plans);   // Handoff/AIReview/CorePortfolio read at render/copy time
    return plans;
  }, [assets, positionExposure, sdSignals, flowRecords, scenarioSets, apItems, impEvents, regime.data, portfolioStrategy]);

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
          valuationDataStatus: f.valuationDataStatus, staleCount: f.staleCount } : undefined; })());
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

  // v11.20.0: AI Review Pack用のイベント一行群(パック内でイベント要約は1回のみ)
  useEffect(() => {
    const lines = (impEvents?.events ?? []).slice(0, 6).map((ie) =>
      `${ie.eventCode} ${ie.title} — ${ie.countdown}${ie.actual ? ` / 結果: ${ie.actual}` : ''}`);
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

  const phase = combinePhase(al.phase as TodayPhase, regime.phase as TodayPhase);
  const judgment = useMemo(
    () => deriveTodayJudgment(al.data, regime.data, ev.data, Date.now()),
    [al.data, regime.data, ev.data],
  );

  // 3-layer risk overlay for the hero (v10.103): a green global regime must not
  // hide a weak Japan tape or holder risk.
  const overlay = useMemo(() => {
    // Prefer the downside engine's globalRegime, but treat "UNKNOWN"/empty as a
    // miss and fall back to the regime endpoint's label (fixes Global=UNKNOWN
    // while Market Regime=Mixed when the downside read hit a cold cache, v10.112).
    const ds = downside?.globalRegime;
    const global = (ds && ds !== 'UNKNOWN') ? ds : (regime.data?.regime?.label || ds || 'UNKNOWN');
    return {
      globalRegime: global,
      jpIntradayOverlay: downside?.jpIntradayOverlay || 'NORMAL',
      holderRiskOverlay: downside?.holderRiskOverlay || 'NONE',
    };
  }, [downside, regime.data]);
  // Partial-data discipline: when data is incomplete, cap confidence at 0.60 and
  // flag PARTIAL so a HOLD never looks high-confidence on thin data.
  const isPartial = phase === 'partial';
  const baseConf = regime.data?.regime?.confidence ?? null;
  // v10.195: fold the Visibility Risk Guard cap into the SAME confidence the hero +
  // judgment log use. Intersect base, the partial-0.60, and the guard cap — ignoring
  // nulls (a naive Math.min(...,undefined) would blank the hero as NaN).
  const capCandidates = [baseConf, isPartial ? 0.60 : null, guard?.confidenceCap ?? null]
    .filter((v): v is number => typeof v === 'number');
  const cappedConf = capCandidates.length ? Math.min(...capCandidates) : baseConf;
  const visLimited = !!guard && guard.visibilityLevel !== 'full';

  // ── Judgment log (device-local memory) ──
  // Record today's LIVE/PARTIAL call (mock is never logged — no fake history),
  // then re-read so the diff/strip below reflect the fresh entry.
  const [logTick, setLogTick] = useState(0);
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
    setLogTick((t) => t + 1);
  }, [phase, judgment, al.data, regime.data]);

  const { diffLineJa, recent } = useMemo(() => {
    void logTick; // re-read after each record
    const prev = previousJudgment(judgment.date);
    const posture = al.data?.marketPosture?.label ?? '—';
    let line: string;
    if (phase !== 'live' && phase !== 'partial') {
      line = '接続中 — ライブ判断が確定したら記録します。';
    } else if (!prev) {
      line = '本日から判断の記録を開始しました。明日以降「昨日からの変化」をここに表示します。';
    } else {
      const changed = prev.overall !== judgment.overall || prev.posture !== posture;
      line = `昨日(${prev.date.slice(5)}): ${prev.overall}(${prev.posture}) → 今日: ${judgment.overall}(${posture}) — ${changed ? '変化あり' : '変化なし'}`;
    }
    return { diffLineJa: line, recent: recentJudgments(7) };
  }, [logTick, judgment, phase, al.data]);

  return (
    <PageShell
      title={tEn('page.today')}
      subtitle={<span>{formatDate(judgment.date)}</span>}
    >
      <MarketSessionLamps />

      {/* LIMITED VISIBILITY (v10.207, owner request): the big yellow "監視に穴があります"
          banner was removed — the owner wants only the plain "PARTIAL DATA" keyword in its
          usual place (the hero status line). A situational degradation (visLimited) is now
          folded into the hero's data-quality below, so it still surfaces as PARTIAL DATA
          without a dominating card. The guard's confidence cap + ENTER suppression are
          unchanged (they flow through cappedConf / the signal), and the muted structural
          coverage line still sits below the hero — nothing loud, nothing lost. */}

      {/* OWNER CRITICAL — a held position on EXIT/DEFEND is surfaced at the very top
          (small), so a held emergency is never missed below the fold (v10.145). */}
      {ownerCritical.length > 0 && (
        <div className="owner-critical" role="alert">
          <span className="owner-critical__tag">OWNER CRITICAL</span>
          <span className="owner-critical__items">
            {ownerCritical.map((c) => (
              <span key={c.id} className="owner-critical__item">{c.symbol} {c.name} · {c.signalCode === 'EXIT' ? '撤退判断' : '資金防衛'}</span>
            ))}
          </span>
        </div>
      )}

      {/* Top page = the main hub (v10.140). Order: PRIMARY COMMAND (+ IMPORTANT
          EVENTS as its lower block) → per-stock category cards (JP first, watchlist
          before emerging) → FX/MACRO → news → history. ONE unified card per stock. */}
      <HeroCard judgment={judgment} overlay={overlay} isPartialData={isPartial || visLimited} confidence={cappedConf} visibilityReasonJa={al.data?.visibility?.downgradeReasonJa} onNavigate={onNavigate} />

      {/* Structural coverage line (v10.195) — always present but MUTED (not an alarm):
          the owner is never falsely reassured that ARGUS sees everything. */}
      {guard?.coverageLineJa && (
        <p className="visibility-coverage">{guard.coverageLineJa}</p>
      )}

      {/* C.A.O.S. — the 2nd card, ALWAYS present. One intelligence hub folding three tiers:
          機関シグナル (institutional views) + イベント分析 (pre/post) + ニュース (market news).
          News is always live, so the card never disappears even when intel/events are empty. */}
      {/* v11.14.0: 新着のcritical/high通知だけ最上部に一帯表示(全リストはベル) */}
      {(() => {
        const hot = listNotifications().filter((n) => n.deliveryState === 'new'
          && (n.severity === 'critical' || n.severity === 'high')).slice(0, 2);
        if (!hot.length) return null;
        return hot.map((n) => (
          <p key={n.id} style={{ margin: '0 0 4px', fontSize: 12, padding: '5px 9px',
                                 border: `1px solid ${SEV_TONE[n.severity]}`, borderRadius: 8 }}>
            <b style={{ color: SEV_TONE[n.severity] }}>[{SEV_JA[n.severity]}]</b>
            <b style={{ marginLeft: 5 }}>{n.titleJa}</b>
            <span style={{ marginLeft: 6, color: 'var(--text-sub)' }}>{n.bodyJa}</span>
          </p>
        ));
      })()}

      {/* v11.16.0: バックアップ未保護×保有あり → 一行警告(保護済みなら非表示) */}
      {(() => {
        const b = assessBackupSafety(assets);
        if (b.protectionLevel === 'unprotected') {
          return (
            <p style={{ margin: '0 0 4px', fontSize: 12, padding: '5px 9px',
                        border: '1px solid var(--value-negative)', borderRadius: 8 }}>
              <b style={{ color: 'var(--value-negative)' }}>バックアップ未保護：</b>
              <span style={{ color: 'var(--text-sub)' }}>保有データはこの端末内にあります。暗号化バックアップを有効化してください(Core Portfolio → BACKUP SAFETY)。</span>
            </p>
          );
        }
        return null;
      })()}

      {/* SESSION BRIEF (v11.13.0) — 今日の作戦。Brief=作戦/AP=見る順番 */}
      <SessionBriefSection brief={sessionBrief} />

      {/* v11.19.0: 戦略の一行注意 — 出すべき警告がある時だけ(通常は非表示)。 */}
      {(() => {
        const note = todayStrategicNoteJa(portfolioStrategy);
        if (!note) return null;
        return (
          <p style={{ margin: '0 0 6px', fontSize: 12, borderLeft: `2px solid ${note.tone}`,
                      paddingLeft: 8, color: 'var(--text-sub)' }}>
            <b style={{ color: note.tone }}>{note.textJa}</b>
            <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
              詳細はCore Portfolio→PORTFOLIO STRATEGY(助言ではない)
            </span>
          </p>
        );
      })()}

      {/* v11.19.1: FIRE Coreの一行注意 — 評価額未更新/未入力/戦術枠比の時だけ。 */}
      {(() => {
        const note = fireCoreTodayNoteJa(latestFireCore());
        if (!note) return null;
        return (
          <p style={{ margin: '0 0 6px', fontSize: 12, borderLeft: `2px solid ${note.tone}`,
                      paddingLeft: 8, color: 'var(--text-sub)' }}>
            <b style={{ color: note.tone }}>{note.textJa}</b>
          </p>
        );
      })()}

      {/* ACTION PRIORITY (v11.12.0) — 開いた瞬間「今日これを見る」。売買指示なし */}
      {/* v11.20.0: AI Review Pack — Todayから直接コピー(自動送信なし) */}
      <p style={{ margin: '0 0 6px' }}><ProHandoffButton /></p>

      <ActionPrioritySection items={apItems}
        scenarios={new Map(scenarioSets.map((s) => [s.symbol, s]))} />

      {/* POSITION PLAN (v11.18.0) — 今日の計画上位のみ(P0-P2/保有リスク/追いかけ注意/
          追加候補/イベント待ち)。Todayを溢れさせない。売買指示ではない。 */}
      <PositionPlanSection plans={positionPlans} apItems={apItems} />

      <CaosHub />

      {/* v11.21.0: 低優先セクションは「件数+一行結論」に圧縮(既定折りたたみ・
          開くまでレンダリングしない)。P0/P1と保有リスクは上のAP/PLANで既出。 */}
      <CollapsibleSection title="BIG MONEY / FLOW"
        countLabel={`${flowRecords.filter((r) => r.flowClass !== 'unknown').length}件`}
        severityTone={flowRecords.some((r) => ['panic_selling', 'distribution'].includes(r.flowClass))
          ? 'var(--amber, #fbbf24)' : undefined}
        conclusionJa={(() => {
          const bad = flowRecords.filter((r) => ['panic_selling', 'distribution'].includes(r.flowClass)).length;
          const acc = flowRecords.filter((r) => r.flowClass === 'institutional_accumulation').length;
          return bad || acc ? `売り圧力推定${bad}件 / 大口買い推定${acc}件` : '本日の大きなフロー推定はありません';
        })()}>
        {() => <FlowAttributionSection />}
      </CollapsibleSection>

      <CollapsibleSection title="PORTFOLIO EXPOSURE"
        countLabel={positionExposure.noHoldings ? '未入力' : `リスク${positionExposure.risks.length}件`}
        severityTone={positionExposure.risks.some((r) => ['high', 'critical'].includes(r.riskLevel))
          ? 'var(--value-negative)' : undefined}
        defaultOpen={positionExposure.risks.some((r) => ['high', 'critical'].includes(r.riskLevel))}
        conclusionJa={positionExposure.noHoldings ? '保有数量未入力(監視のみ)'
          : `集中度: ${positionExposure.singleNameRisk ?? '不明'} / 詳細は展開`}>
        {() => <PositionRiskSection exposure={positionExposure} />}
      </CollapsibleSection>

      <CollapsibleSection title="SUPPLY / DEMAND"
        countLabel={`${sdSignals.filter((s) => s.supplyDemandRank !== 'Unknown').length}件`}
        severityTone={sdSignals.some((s) => ['D', 'E'].includes(s.supplyDemandRank))
          ? 'var(--amber, #fbbf24)' : undefined}
        conclusionJa={(() => {
          const de = sdSignals.filter((s) => ['D', 'E'].includes(s.supplyDemandRank)).length;
          const sq = sdSignals.filter((s) => s.condition === 'squeeze_prone').length;
          const heavy = sdSignals.filter((s) => s.condition === 'improving_but_heavy').length;
          const parts = [de ? `D/E ${de}件` : '', sq ? `踏み上げ候補${sq}件` : '', heavy ? `改善中だが重い${heavy}件` : ''].filter(Boolean);
          return parts.length ? parts.join(' / ') : '需給に大きな偏りなし';
        })()}>
        {() => <SupplyDemandSection signals={sdSignals} />}
      </CollapsibleSection>

      <AssetCategorySection title="JAPAN · WATCHLIST" cards={cardGroups.jpWatch} emptyJa="日本株の登録銘柄はありません" positionNotes={positionExposure.notes} supplyDemandSignals={sdSignals} actionPriorities={apItems} scenarios={scenarioSets} plans={positionPlans} />
      <AssetCategorySection title="US · WATCHLIST" cards={cardGroups.usWatch} emptyJa="米国株の登録銘柄はありません" positionNotes={positionExposure.notes} supplyDemandSignals={sdSignals} actionPriorities={apItems} scenarios={scenarioSets} plans={positionPlans} />

      {/* RECOMMEND — what ARGUS judges is the best to BUY NOW (high-conviction buy signal).
          The raw surge/stop-high feed was removed (v10.180): the goal is "buy now", not
          "what spiked". Watchlist-外の発掘。 */}
      <CollapsibleSection title="RECOMMEND / 発掘"
        conclusionJa="ウォッチリスト外の高確信候補(開いて確認)">
        {() => <BuyCandidates />}
      </CollapsibleSection>
      <AssetCategorySection title="CRYPTO" cards={cardGroups.crypto} emptyJa="暗号資産の登録はありません" positionNotes={positionExposure.notes} scenarios={scenarioSets} plans={positionPlans} />

      {/* FX / MACRO — the macro backdrop (USDJPY / US10Y / VIX). */}
      <CollapsibleSection title="FX / MACRO" conclusionJa="ドル円・米金利・VIXの背景(開いて確認)">
        {() => <FxMacroSection />}
      </CollapsibleSection>

      <CollapsibleSection title="HISTORY / JUDGMENT LOG"
        conclusionJa="自己採点と判断履歴(開いて確認)">
        {() => (
        <div className="card jlog">
          <p className="jlog__diff">{diffLineJa}</p>
          {aiStateJa && <p className="jlog__diff" style={{ marginTop: 6 }}>{aiStateJa}</p>}
          {!ledger.loading && !ledger.data?.overall && (
            <div className="jlog__acc">📊 自己採点: 採点データはまだありません(次の平日16:05に初回の答え合わせが走ります)。</div>
          )}
          {ledger.data?.overall && (
            <div className="jlog__acc">
              📊 自己採点(予測台帳・{ledger.data.overall.days}営業日 / {ledger.data.overall.n}件):
              方向の的中率 <b>{Math.round((ledger.data.overall.hitRate ?? 0) * 100)}%</b>
              {typeof ledger.data.overall.brierMean === 'number' && (
                <> ・確率スキル <b>{Math.round(Math.max(-100, (0.667 - ledger.data.overall.brierMean) / 0.667 * 100))}%</b>
                <span className="jlog__brier-hint">（方向とは別＝確率の当たり具合。あてずっぽう=0%／完璧=100%・元Brier {ledger.data.overall.brierMean.toFixed(2)}）</span></>
              )}
              {ledger.data.aiDirectional.hitRate != null && (
                <> ・AI方向的中 <b>{Math.round(ledger.data.aiDirectional.hitRate * 100)}%</b>({ledger.data.aiDirectional.n}件)</>
              )}
              {ledger.data.classes?.hitRate != null && (
                <> ・資産クラス <b>{Math.round(ledger.data.classes.hitRate * 100)}%</b>({ledger.data.classes.n}件)</>
              )}
              {ledger.data.posture?.hitRate != null && (
                <> ・姿勢の的中 <b>{Math.round(ledger.data.posture.hitRate * 100)}%</b>({ledger.data.posture.n}回)</>
              )}
              {ledger.data.layers?.layer1?.byHorizon?.['1']?.hitRate != null && (
                <> ・センサー1日 <b>{Math.round((ledger.data.layers.layer1.byHorizon['1'].hitRate ?? 0) * 100)}%</b>({ledger.data.layers.layer1.byHorizon['1'].n}件)</>
              )}
              <div className="jlog__acc-note">{ledger.data.noteJa}</div>
              {/* Sample-size honesty (v10.35): n counts predictions, not independent
                  trials — same-day/same-theme names are correlated. */}
              <div className="jlog__acc-warn">
                ※ {ledger.data.overall.n}件は{ledger.data.overall.days}営業日分で、同日・同テーマの相関した銘柄を含むため独立試行ではありません。実効サンプルは件数より小さく、20営業日ほど貯まるまでは参考値です。
              </div>
            </div>
          )}
          {/* closepin-v1: same-day 14:30-pin → close scoring,独立した第二台帳 */}
          {ledger.closepin?.overall?.hitRate != null ? (
            <div className="jlog__acc">
              🎯 引けピン(14:30→同日終値・{ledger.closepin.overall.days}日 / {ledger.closepin.overall.n}件):
              方向の的中率 <b>{Math.round((ledger.closepin.overall.hitRate ?? 0) * 100)}%</b>
              {typeof ledger.closepin.overall.brierMean === 'number' && (
                <> ・確率スキル <b>{Math.round(Math.max(-100, (0.667 - ledger.closepin.overall.brierMean) / 0.667 * 100))}%</b>
                <span className="jlog__brier-hint">（あてずっぽう=0%／完璧=100%・元Brier {ledger.closepin.overall.brierMean.toFixed(2)}）</span></>
              )}
              <div className="jlog__acc-note">
                ※「その日の終値が上/下/横ばいのどれか」をARGUSが当てられたかの自己採点(短期判断の校正)。
                銘柄横断の集計値で、個別銘柄の売買シグナルでも翌日の上昇予測でもありません。
              </div>
            </div>
          ) : (!ledger.loading && ledger.data && (
            <div className="jlog__acc">🎯 引けピン台帳: 蓄積開始前(毎営業日14:30にピン → 16:05に同日採点)。</div>
          ))}
          {recent.length > 0 && (
            <div className="jlog__strip">
              {recent.map((e) => (
                <div className="jlog__row" key={e.date}>
                  <span className="jlog__date">{e.date.slice(5)}</span>
                  <ActionPill action={e.overall} size="sm" />
                  <span className="jlog__posture">{e.posture}</span>
                  <span className="jlog__conf">{e.confidence != null ? `${Math.round(e.confidence * 100)}%` : '—'}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        )}
      </CollapsibleSection>

      {/* v11.21.0: モバイル専用の下部要約バー(10秒把握・720px以下のみ) */}
      <MobileStickyCommand
        ownerModeJa={sessionBrief.ownerModeJa}
        p0Count={apItems.filter((i) => i.priorityRank === 'P0').length}
        nextEventJa={(() => {
          const ie = (impEvents?.events ?? []).find((e) => e.countdown === 'D' || e.countdown === 'D-1')
            ?? (impEvents?.events ?? [])[0];
          return ie ? `${ie.eventCode} ${ie.countdown === 'D' ? '当日' : ie.countdown}` : null;
        })()}
        unreadCount={unreadCounts().total}
      />
    </PageShell>
  );
};

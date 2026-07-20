import { useMemo } from 'react';
import { useAssets } from './useAssets';
import { useAIJudgment } from './useAIJudgment';
import { useActionLabels } from './useActionLabels';
import { useCryptoWatchlist } from './useCryptoWatchlist';
import { useMarketRegime } from './useMarketRegime';
import { useEventRadar } from './useEventRadar';
import { useDownsideIncidents } from './useDownsideIncidents';
import { useVisibilityGuard } from './useVisibilityGuard';
import { useEventsActive } from './useEventsActive';
import { useImportantEvents } from './useImportantEvents';
import { useRatesSnapshot } from './useRatesSnapshot';
import { useJapanWatchlist } from './useJapanWatchlist';
import { useUSWatchlist } from './useUSWatchlist';
import { useFlowAttributionList } from './useFlowAttribution';
import { useSupplyDemandList } from './useSupplyDemand';
import { useMarketLedger } from './useMarketLedger';
import { coingeckoIdOf } from '../lib/cryptoIds';
import { groupAssetCards, type LinkedEventTag, type AssetCardModel } from '../domain/assetCard';
import { mergeAiPrimary, resolveAssetDecision, type AssetDecisionView, type AiMeta } from '../domain/assetDecision';
import { buildPositionExposure, themeOf } from '../domain/positionExposure';
import {
  publishExposure, publishActionPriorities, publishSessionBrief,
  publishScenarios, publishPlans, publishStrategy, publishFireCore,
} from '../lib/positionExposureShare';
import { listDQ } from '../lib/decisionQuality';
import { buildItem as buildAPItem, rankItems as rankAPItems, type APItem } from '../domain/actionPriority';
import { buildLocalBrief } from '../domain/sessionBrief';
import { buildScenarioSet, type LocalScenarioSet } from '../domain/scenario';
import { buildPlan, marketOpenNow, type LocalPlan } from '../domain/positionPlan';
import { resolvePrimaryStance, type ResolvedStance } from '../domain/primaryStance';
import { resolveCommandSummary, SIGNALS as CS_SIGNALS } from '../domain/commandSummary';
import { classifyRole, buildStrategy, type LocalStrategy } from '../domain/portfolioStrategy';
import { buildLocalFireCore, type LocalFireCore } from '../lib/fireCore';
import { deriveTodayJudgment, combinePhase, type TodayPhase } from '../lib/todayCall';

// ── V12.2.12: Asset Intelligence(TodayとAsset Deskの共有データ組み立て) ──────
//
// 旧CommandCenter内にあった個別銘柄系のuseMemoパイプライン(AI優先マージ→カード
// →ポジション/優先度/シナリオ/計画/戦略/構え)をそのまま移設した唯一の正本。
// Today(publish:true)とAsset Desk(publish:false)が同じフックを呼ぶため、
// 同一銘柄の判断・件数・構えがページ間で構造的に一致する。
//
// publish副作用(Pro Handoff / AI Review / スナップショットが読む共有ストアへの
// 書き込み)は従来どおりTodayのみ: publish:false では一切書き込まない。
// この層は新しい投資判断を生成しない — 既存レイヤーの出力の組み立てのみ。

export interface AssetIntel {
  assets: ReturnType<typeof useAssets>['assets'];
  aiJ: ReturnType<typeof useAIJudgment>;
  al: ReturnType<typeof useActionLabels>;
  guard: ReturnType<typeof useVisibilityGuard>;
  regime: ReturnType<typeof useMarketRegime>;
  downside: ReturnType<typeof useDownsideIncidents>['data'];
  events247: ReturnType<typeof useEventsActive>['events'];
  impEvents: ReturnType<typeof useImportantEvents>['data'];
  rates: ReturnType<typeof useRatesSnapshot>;
  /** 実クオートhook(Asset Deskがname/volume/date/status付きで再利用 — 二重fetch防止)。 */
  jpQuotes: ReturnType<typeof useJapanWatchlist>;
  usQuotes: ReturnType<typeof useUSWatchlist>;
  cryptoWatch: ReturnType<typeof useCryptoWatchlist>;
  flowRecords: ReturnType<typeof useFlowAttributionList>['records'];
  sdSignals: ReturnType<typeof useSupplyDemandList>['signals'];
  cardGroups: ReturnType<typeof groupAssetCards>;
  cardBySym: Map<string, AssetCardModel>;
  ownerCritical: AssetCardModel[];
  positionExposure: ReturnType<typeof buildPositionExposure>;
  apItems: APItem[];
  sessionBrief: ReturnType<typeof buildLocalBrief>;
  scenarioSets: LocalScenarioSet[];
  portfolioStrategy: LocalStrategy;
  fireCore: LocalFireCore;
  positionPlans: LocalPlan[];
  phase: TodayPhase;
  judgment: ReturnType<typeof deriveTodayJudgment>;
  overlay: { globalRegime: string; jpIntradayOverlay: string; holderRiskOverlay: string };
  isPartial: boolean;
  visLimited: boolean;
  cappedConf: number | null;
  commandSummary: ReturnType<typeof resolveCommandSummary>;
  globalAddProhibited: boolean;
  positionRisk: { alert: boolean; ja: string };
  stanceBySymbol: Map<string, ResolvedStance>;
  aiMeta: AiMeta;
  decisionBySym: Map<string, AssetDecisionView>;
}

export function useAssetIntel(opts: { publish: boolean }): AssetIntel {
  const publish = opts.publish;
  const { assets } = useAssets();
  const aiJ = useAIJudgment();
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
  const marketLedger = useMarketLedger();
  const ev = useEventRadar();
  const { data: downside } = useDownsideIncidents();
  const guard = useVisibilityGuard();   // Visibility Risk Guard (v10.195)
  const { events: events247 } = useEventsActive();
  const { data: impEvents } = useImportantEvents();

  // AI-AS-PRIMARY merge (v10.160→v12.2.12): the single source of truth lives in
  // domain/assetDecision.ts — Today and Asset Desk both consume THIS result.
  const merged = useMemo(
    () => mergeAiPrimary(aiJ.data, al.data?.labels ?? [], Date.now()),
    [aiJ.data, al.data]);

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
    return groupAssetCards({
      assets, labels: merged.labels, incidents: downside?.incidents ?? [],
      events: events247 ?? [], linked, aiFreshness: merged.meta.freshness, cryptoQuotes,
    });
  }, [assets, merged, downside, events247, impEvents, cryptoQuotes]);
  const cardBySym = useMemo(() => new Map(
    [...cardGroups.jpWatch, ...cardGroups.usWatch, ...cardGroups.crypto]
      .map((c) => [c.symbol.toUpperCase(), c])), [cardGroups]);

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
  // v12.0.6 (owner: 保有銘柄の需給が全く出ない): デバイスのウォッチリスト銘柄を
  // サーバーへ渡し、固定リスト外(6965/7011等)にも需給ランクを出す。ソート済み
  // カンマ結合で参照安定化(不要な再fetchを防ぐ)。
  const sdExtraSymbols = useMemo(() =>
    assets.filter((a) => a.market === 'JP' || a.market === 'US')
      .map((a) => a.symbol.toUpperCase()).sort().join(','),
    [assets]);
  const { signals: sdSignals } = useSupplyDemandList(sdExtraSymbols);   // v11.10.0 需給ランク
  // Card prices vanish outside sessions (labels carry no price) — fall back to
  // the same real quote hooks Core Portfolio uses (delayed close = real data).
  const peJp = useJapanWatchlist(jpSyms);
  const peUs = useUSWatchlist(usSyms);
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
    if (publish) publishExposure(pe);   // Pro Handoff / AI Review read this at copy time (device-local)
    return pe;
  }, [assets, cardGroups, rates.data, flowRecords, sdSignals, impEvents, regime.data, peJp.data, peUs.data, publish]);

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
    if (publish) publishActionPriorities(ranked);   // Handoff/AIReview read at copy time
    return ranked;
  }, [assets, positionExposure, sdSignals, flowRecords, impEvents, regime.data, publish]);

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
      marketCalendar: marketLedger.ledger?.phase3?.calendar,
    });
    if (publish) publishSessionBrief(b);
    return b;
  }, [apItems, impEvents, regime.data, positionExposure, marketLedger.ledger, publish]);

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
    if (publish) publishScenarios(sets);   // Handoff/AIReview/Regime/CorePortfolio read at render/copy time
    return sets;
  }, [assets, positionExposure, sdSignals, flowRecords, impEvents, regime.data, publish]);

  // v11.19.0: PORTFOLIO STRATEGY — 役割分類(コア/サテライト/戦術枠/ヘッジ)と
  // FIRE整合・リスク予算を端末内で合成。計画層(下)へ制約を供給する。
  // v12.2.12: FIRE Core(fc)はストア経由でなく戻り値で下流に渡す — Asset Deskが
  // Today未訪問でも同一値になる(Todayではpublishで従来どおりストアにも書く)。
  const strategyAndFire = useMemo(() => {
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
    if (publish) publishFireCore(fc);
    const s = buildStrategy(positionExposure, roles, {
      eventPending: eventSyms.size > 0,
      recurringAccumulationKnown: fc.contributionDataStatus === 'complete',
      fireCore: { known: fc.fireCoreTotal != null,
        tacticalToCoreBand: fc.tacticalToCoreBand,
        contributionKnown: fc.contributionDataStatus === 'complete' },
    });
    if (publish) publishStrategy(s);   // CorePortfolio/Handoff/AIReview read at render/copy time
    return { strategy: s, fireCore: fc };
  }, [assets, positionExposure, impEvents, publish]);
  const portfolioStrategy = strategyAndFire.strategy;
  const fireCore = strategyAndFire.fireCore;

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
    const fcPos = new Map(fireCore.positions.map((x) => [x.symbol, x]));
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
    if (publish) publishPlans(plans);   // Handoff/AIReview/CorePortfolio read at render/copy time
    return plans;
  }, [assets, positionExposure, sdSignals, flowRecords, scenarioSets, apItems, impEvents, regime.data, portfolioStrategy, fireCore, publish]);

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

  // v12.0.8追補: ヒーローと同じ解決器で総合コマンドを一度だけ解決 —
  // Today's Stanceカードとadd可否判定が同一のsummaryを共有する。
  const commandSummary = useMemo(() => resolveCommandSummary({
    legacyAction: judgment.overall, globalRegime: overlay?.globalRegime,
    jpOverlay: overlay?.jpIntradayOverlay, ownerRisk: overlay?.holderRiskOverlay,
    risk: judgment.risk, isPartial: isPartial || visLimited,
    confidence: cappedConf, nextConditionJa: judgment.nextCondition,
  }), [judgment, overlay, isPartial, visLimited, cappedConf]);
  const globalAddProhibited = useMemo(() => {
    try {
      return CS_SIGNALS[commandSummary.signalCode].permissions.add === 'BLOCKED';
    } catch { return false; }
  }, [commandSummary]);

  // v12.0.8追補: 保有リスクチップ(市場リスクと分離) — 保有×P0/P1件数から。
  const positionRisk = useMemo(() => {
    if (positionExposure.noHoldings) return { alert: false, ja: '保有数量未入力' };
    const n = apItems.filter((it) => it.isHeld && (it.priorityRank === 'P0' || it.priorityRank === 'P1')).length
      + positionExposure.risks.filter((r) => ['high', 'critical'].includes(r.riskLevel)).length;
    return n > 0 ? { alert: true, ja: `保有銘柄に要確認あり(${n}件)` }
                 : { alert: false, ja: '明確な警報なし' };
  }, [positionExposure, apItems]);

  // v12.0.8 Part C: 銘柄ごとの「単一の構え」(全カード共通チップ) — Session Brief /
  // AP / Plan / カードの矛盾(P1なのに対応不要 等)を構造的に排除。売買指示ではない。
  const stanceBySymbol = useMemo(() => {
    const m = new Map<string, ResolvedStance>();
    const apBySym = new Map(apItems.map((it) => [it.symbol, it]));
    const planBySym = new Map(positionPlans.map((pl) => [pl.symbol, pl]));
    const scBySym = new Map(scenarioSets.map((sc) => [sc.symbol, sc]));
    const sdBySym = new Map(sdSignals.map((sg) => [sg.symbol.toUpperCase(), sg]));
    const flowBySym = new Map(flowRecords.map((r) => [r.symbol.toUpperCase(), r.flowClass]));
    const riskBySym = new Map(positionExposure.risks.map((r) => [r.symbol, r.riskLevel]));
    const heldSyms = new Set(positionExposure.notes ? Object.keys(positionExposure.notes) : []);
    const eventSyms = new Set<string>();
    for (const ie of impEvents?.events ?? []) {
      if (ie.countdown === 'D' || ie.countdown === 'D-1') {
        for (const a of ie.linkedAssets ?? []) eventSyms.add(String(a).toUpperCase());
      }
    }
    for (const a of assets) {
      const sym = a.symbol.toUpperCase();
      const ap = apBySym.get(sym);
      const pl = planBySym.get(sym);
      m.set(sym, resolvePrimaryStance({
        isHeld: heldSyms.has(sym) || !!ap?.isHeld,
        apRank: ap?.priorityRank, apLabel: ap?.actionLabel,
        planStance: pl?.currentStance, scenarioDominant: scBySym.get(sym)?.dominant,
        sdCondition: sdBySym.get(sym)?.condition, sdLevel: sdBySym.get(sym)?.supplyDemandLevel,
        flowClass: flowBySym.get(sym), eventWait: eventSyms.has(sym),
        riskLevel: riskBySym.get(sym), dataPartial: isPartial || visLimited,
        baseConfidence: ap?.confidence,
        globalAddProhibited,
      }));
    }
    return m;
  }, [assets, apItems, positionPlans, scenarioSets, sdSignals, flowRecords,
      positionExposure, impEvents, isPartial, visLimited, globalAddProhibited]);

  // ── V12.2.12: 銘柄別の判断ビュー(AI PRIMARY / RULE TEMPORARY・source追跡) ──
  const decisionBySym = useMemo(() => {
    const m = new Map<string, AssetDecisionView>();
    const mergedBySym = new Map(merged.labels.map((l) => [l.symbol.toUpperCase(), l]));
    const ruleBySym = new Map((al.data?.labels ?? []).map((l) => [l.symbol.toUpperCase(), l]));
    const aiBySym = new Map((aiJ.data?.labels ?? []).map((l) => [l.symbol.toUpperCase(), l]));
    for (const a of assets) {
      const sym = a.symbol.toUpperCase();
      m.set(sym, resolveAssetDecision({
        symbol: sym,
        merged: mergedBySym.get(sym),
        ruleLabel: ruleBySym.get(sym),
        aiLabel: aiBySym.get(sym),
        meta: merged.meta,
        symbolHasAi: aiBySym.has(sym),
      }));
    }
    return m;
  }, [assets, merged, al.data, aiJ.data]);

  return {
    assets, aiJ, al, guard, regime, downside, events247, impEvents, rates,
    jpQuotes: peJp, usQuotes: peUs, cryptoWatch: cw,
    flowRecords, sdSignals,
    cardGroups, cardBySym, ownerCritical,
    positionExposure, apItems, sessionBrief, scenarioSets,
    portfolioStrategy, fireCore, positionPlans,
    phase, judgment, overlay, isPartial, visLimited, cappedConf,
    commandSummary, globalAddProhibited, positionRisk, stanceBySymbol,
    aiMeta: merged.meta, decisionBySym,
  };
}

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
import { publishExposure } from '../lib/positionExposureShare';
import { maybeDailySnapshot } from '../lib/portfolioSync';
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
    // v11.9.0: one automatic LOCAL snapshot per JST day once holdings price —
    // 「あの日ARGUSが何を言っていたか」を将来の答え合わせ用に残す(送信なし)。
    try { maybeDailySnapshot(pe, __APP_VERSION__, flowBySymbol,
      sdSignals.map((s) => ({ symbol: s.symbol, rank: s.supplyDemandRank, condition: s.condition }))); } catch { /* quota */ }
    return pe;
  }, [assets, cardGroups, rates.data, flowRecords, sdSignals, impEvents, regime.data, peJp.data, peUs.data]);

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
      <CaosHub />

      {/* BIG MONEY / FLOW (v11.7.0) — who is likely behind today's moves.
          推定は推定と明示・実測と分離・売買指示なし。 */}
      <FlowAttributionSection />

      {/* PORTFOLIO EXPOSURE (v11.8.0) — held-position risks, concentration,
          add-more readiness. Device-local math; never a trade order. */}
      <PositionRiskSection exposure={positionExposure} />

      {/* SUPPLY / DEMAND (v11.10.0) — 日本株の需給ランク。数値の読解はエンジン、
          生数値は折りたたみ。状態評価であり売買指示ではない。 */}
      <SupplyDemandSection signals={sdSignals} />

      <AssetCategorySection title="JAPAN · WATCHLIST" cards={cardGroups.jpWatch} emptyJa="日本株の登録銘柄はありません" positionNotes={positionExposure.notes} supplyDemandSignals={sdSignals} />
      <AssetCategorySection title="US · WATCHLIST" cards={cardGroups.usWatch} emptyJa="米国株の登録銘柄はありません" positionNotes={positionExposure.notes} />

      {/* RECOMMEND — what ARGUS judges is the best to BUY NOW (high-conviction buy signal).
          The raw surge/stop-high feed was removed (v10.180): the goal is "buy now", not
          "what spiked". Watchlist-外の発掘。 */}
      <BuyCandidates />
      <AssetCategorySection title="CRYPTO" cards={cardGroups.crypto} emptyJa="暗号資産の登録はありません" positionNotes={positionExposure.notes} />

      {/* FX / MACRO — the macro backdrop (USDJPY / US10Y / VIX). */}
      <FxMacroSection />

      <section>
        <div className="section-head">
          <span className="section-head__title">HISTORY / JUDGMENT LOG</span>
          <span className="section-head__count">device-local memory</span>
        </div>
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
      </section>
    </PageShell>
  );
};

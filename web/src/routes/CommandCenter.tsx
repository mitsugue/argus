import React, { useEffect, useMemo, useState } from 'react';
import { PageShell } from './PageShell';
import { ImportantEventsCard } from '../components/dashboard/ImportantEventsCard';
import { TodayStanceCard } from '../components/today/TodayStanceCard';
import { OvernightChangesCard } from '../components/today/OvernightChangesCard';
import { YourExposureCard } from '../components/today/YourExposureCard';
import { TodayActionQueue } from '../components/today/TodayActionQueue';
import { NextCheckCard } from '../components/today/NextCheckCard';
import { TodayDetails, type DetailGroup } from '../components/today/TodayDetails';
import { TodayAttention } from '../components/today/TodayAttention';
import { TodayAssetExceptions, type AssetExceptionRow } from '../components/today/TodayAssetExceptions';
import { PRIMARY_EN } from '../components/assetDesk/deskFormat';
import { buildTodayOverview } from '../domain/todayOverview';
import { FxMacroSection } from '../components/dashboard/FxMacroSection';
import { CaosHub } from '../components/dashboard/CaosHub';
import { FlowAttributionSection } from '../components/dashboard/FlowAttributionSection';
import { BuyCandidates } from '../components/dashboard/BuyCandidates';
import { useLocale, t, tEn } from '../i18n';
import { MarketSessionLamps } from '../components/dashboard/MarketSessionLamps';
import { ActionPill } from '../components/action/ActionBadge';
import { recordJudgment, previousJudgment, recentJudgments } from '../lib/judgmentLog';
import { useLedgerSummary } from '../hooks/useLedgerSummary';
import { useAssetIntel } from '../hooks/useAssetIntel';
import { SupplyDemandSection } from '../components/dashboard/SupplyDemandSection';
import { latestActionPriorities, latestSessionBrief, latestFireCore, publishEventsJa, publishDataQuality, latestDataQuality } from '../lib/positionExposureShare';
import { maybeDailySnapshot } from '../lib/portfolioSync';
import { maybeUpdateOutcomes } from '../lib/decisionQuality';
import { ActionPrioritySection } from '../components/dashboard/ActionPrioritySection';
import { PositionPlanSection } from '../components/dashboard/PositionPlanSection';
import { ProHandoffButton } from '../components/dashboard/ProHandoffButton';
import { nextUpcomingEvent } from '../lib/eventClock';
import { MobileStickyCommand } from '../components/dashboard/MobileStickyCommand';
import { unreadCounts } from '../lib/notifications';
import { todayStrategicNoteJa } from '../domain/portfolioStrategy';
import { fireCoreTodayNoteJa } from '../lib/fireCore';
import { SessionBriefSection } from '../components/dashboard/SessionBriefSection';
import { runNotificationEngine, listNotifications, SEV_TONE, SEV_JA } from '../lib/notifications';
import { assessBackupSafety } from '../lib/backupSafety';
import { listSnapshots } from '../lib/portfolioSync';
import { PositionRiskSection } from '../components/dashboard/PositionRiskSection';
import type { RouteKey } from '../components/NavRail';
import '../components/dashboard/Dashboard.css';

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
    assets, aiJ, al, guard, regime, downside, impEvents, rates,
    flowRecords, sdSignals, cardGroups, ownerCritical, positionExposure,
    apItems, sessionBrief, scenarioSets, portfolioStrategy, fireCore, positionPlans,
    phase, judgment, isPartial, visLimited, cappedConf, commandSummary,
    positionRisk, stanceBySymbol, decisionBySym,
  } = useAssetIntel({ publish: true });
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
    // v12.2.12: 実行を保証できない状態では16:05を約束しない(状態別の正確な文言)。
    const st = aiJ.data?.status;
    if (st === 'disabled') return '🤖 AI見解: 無効化中(自動実行なし) — ルール判定で稼働中。';
    if (st === 'no_cached_result') return '🤖 AI見解: まだ未実行(次の平日16:05に自動実行。それまではルール判定で稼働中)。';
    return '🤖 AI見解: 未取得(接続待ちまたは取得失敗) — ルール判定で稼働中。';
  }, [aiJ.data, aiJ.phase]);
  // (個別銘柄カード/OWNER CRITICAL/Exposure/AP/Brief/Scenarios/Plans/Strategy/
  //  FireCore/構え/判断コンテキストは全て useAssetIntel から供給 — v12.2.12)

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
  const [dqNote, setDqNote] = useState<{ tone: string; textJa: string } | null>(null);
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
          if (d.overallStatus === 'critical' || d.overallStatus === 'warning') {
            setDqNote({ tone: d.overallStatus === 'critical' ? 'var(--value-negative)' : 'var(--amber, #fbbf24)',
              textJa: `データ品質${d.overallStatusJa}: ${(d.topIssuesJa ?? [])[0] ?? d.ownerReadableSummaryJa}` });
          }
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

  // ── V12.2.11: Today Overview view model(表示用の選択・優先順位付け・重複排除
  // のみ — 新しい投資判断は生成しない。既存レイヤーの出力を渡すだけ)。
  const eventLinkedHeldSymbols = useMemo(() => {
    const held = new Set(Object.entries(positionExposure.notes)
      .filter(([, n]) => n.held).map(([sym]) => sym));
    const out = new Set<string>();
    for (const ie of impEvents?.events ?? []) {
      if (ie.countdown === 'D' || ie.countdown === 'D-1') {
        for (const a of ie.linkedAssets ?? []) {
          const sym = String(a).toUpperCase();
          if (held.has(sym)) out.add(sym);
        }
      }
    }
    return [...out];
  }, [impEvents, positionExposure]);
  const overview = useMemo(() => {
    void logTick;   // 判断ログ記録後に前回比較を再読込
    return buildTodayOverview({
      sessionType: sessionBrief.sessionType,
      marketStatusJa: sessionBrief.marketStatusJa,
      prevJudgment: previousJudgment(judgment.date),
      todayOverall: judgment.overall,
      todayPosture: al.data?.marketPosture?.label ?? '—',
      usdJpy: rates.data?.usdJpy ?? null,
      us10y: rates.data?.us10y ?? null,
      nextEvent: nextUpcomingEvent(impEvents?.events ?? [], Date.now(), { highImpactOnly: true }),
      apItems, plans: positionPlans, brief: sessionBrief,
      exposure: positionExposure, strategy: portfolioStrategy,
      eventLinkedHeldSymbols,
    });
  }, [logTick, judgment, al.data, rates.data, impEvents, apItems, positionPlans,
      sessionBrief, positionExposure, portfolioStrategy, eventLinkedHeldSymbols]);

  // PARTIAL DATAの理由(実際に該当するものだけ・上位4件) — 判断の詳細で表示
  const partialReasonsJa = useMemo(() => {
    const rs: string[] = [];
    if (guard?.coverageLineJa) rs.push(guard.coverageLineJa);
    const dqc = latestDataQuality();
    if (dqc && dqc.overallStatus !== 'ok') rs.push(`データ品質: ${dqc.overallStatusJa}(${dqc.topIssuesJa[0] ?? '一部ソースが古い/不明'})`);
    rs.push('日本株リアルタイムはmoomoo側メンテナンス中(サポート確認済み) — 代替データで判定');
    if (al.data?.status === 'partial') rs.push('判定ソースの一部が未取得(コールドキャッシュ/巡回待ち)');
    return rs;
  }, [guard, al.data]);

  // ── V12.2.12: 銘柄の例外サマリー(Todayの銘柄カード全リストの置き換え) ──
  // 個別銘柄の正本はAsset Desk。ここは例外(保有×撤退/防衛・保有×P0/P1・急落・
  // AIとルールの不一致)の選択のみ — 判断はuseAssetIntel(Asset Deskと同一)。
  const assetExceptions: AssetExceptionRow[] = useMemo(() => {
    const apBySym = new Map(apItems.map((it) => [it.symbol, it]));
    const rows: (AssetExceptionRow & { rank: number })[] = [];
    for (const c of [...cardGroups.jpWatch, ...cardGroups.usWatch, ...cardGroups.crypto]) {
      const sym = c.symbol.toUpperCase();
      const dec = decisionBySym.get(sym);
      const ap = apBySym.get(sym);
      const tags: string[] = [];
      let rank = 9;
      if (c.held && (c.signalCode === 'EXIT' || c.signalCode === 'DEFEND')) {
        tags.push(c.signalCode === 'EXIT' ? '保有×撤退判断' : '保有×資金防衛'); rank = Math.min(rank, 0);
      }
      if (c.held && ap?.priorityRank === 'P0') { tags.push('P0'); rank = Math.min(rank, 1); }
      else if (c.held && ap?.priorityRank === 'P1') { tags.push('P1'); rank = Math.min(rank, 2); }
      if (c.hasIncident) { tags.push('急落対応中'); rank = Math.min(rank, 3); }
      if (dec?.rule.disagreementJa) { tags.push(`AIとルール不一致(${dec.rule.disagreementJa})`); rank = Math.min(rank, 4); }
      if (!tags.length) continue;
      rows.push({ symbol: c.symbol, nameJa: c.name, tagJa: tags.join(' / '),
        actionEn: PRIMARY_EN[c.signalCode],
        sourceTagEn: dec ? dec.sourceTagEn : 'RULE',
        reasonJa: dec?.reasonJa && dec.reasonJa !== '判断根拠を取得中' ? dec.reasonJa : (c.causeOneLineJa ?? ''),
        rank });
    }
    // 決定論: 深刻度→symbol(入力順に依存しない)
    return rows.sort((a, b) => a.rank - b.rank || (a.symbol < b.symbol ? -1 : 1))
      .slice(0, 8).map(({ rank: _r, ...row }) => row);
  }, [cardGroups, decisionBySym, apItems]);
  const assetCountsJa = useMemo(() => {
    const f = assets.filter((a) => a.market !== 'JP' && a.market !== 'US' && a.market !== 'CRYPTO').length;
    return `JP ${cardGroups.jpWatch.length} · US ${cardGroups.usWatch.length} · 暗号 ${cardGroups.crypto.length}${f ? ` · 投信等 ${f}` : ''}`;
  }, [assets, cardGroups]);

  // ── Details / Deep Dive(役割別5グループ・初期は閉じる) ─────────────────────
  const detailGroups: DetailGroup[] = [
    {
      title: 'MARKET DETAILS', persistKey: 'g-market',
      conclusionJa: 'セッション・重要イベント・FX/金利・ニュース/機関シグナル(開いて確認)',
      render: () => (
        <>
          <MarketSessionLamps />
          <ImportantEventsCard onNavigate={onNavigate} />
          <CaosHub />
          <FxMacroSection />
        </>
      ),
    },
    {
      title: 'POSITION DETAILS', persistKey: 'g-position',
      countLabel: positionExposure.noHoldings ? '未入力' : `リスク${positionExposure.risks.length}件`,
      severityTone: positionExposure.risks.some((r) => ['high', 'critical'].includes(r.riskLevel))
        ? 'var(--value-negative)' : undefined,
      defaultOpen: positionExposure.risks.some((r) => ['high', 'critical'].includes(r.riskLevel)),
      conclusionJa: positionExposure.noHoldings ? '保有数量未入力(監視のみ)'
        : `集中度: ${positionExposure.singleNameRisk ?? '不明'} / 作戦・優先度・計画・リスクの全詳細`,
      render: () => (
        <>
          <SessionBriefSection brief={sessionBrief} />
          <ActionPrioritySection items={apItems} stances={stanceBySymbol}
            scenarios={new Map(scenarioSets.map((s) => [s.symbol, s]))} />
          <PositionPlanSection plans={positionPlans} apItems={apItems} />
          <PositionRiskSection exposure={positionExposure} />
        </>
      ),
    },
    {
      title: 'RESEARCH & SIGNALS', persistKey: 'g-research',
      countLabel: `${sdSignals.filter((s) => s.supplyDemandRank !== 'Unknown').length + flowRecords.filter((r) => r.flowClass !== 'unknown').length}件`,
      severityTone: flowRecords.some((r) => ['panic_selling', 'distribution'].includes(r.flowClass))
        || sdSignals.some((s) => ['D', 'E'].includes(s.supplyDemandRank))
        ? 'var(--amber, #fbbf24)' : undefined,
      conclusionJa: (() => {
        const bad = flowRecords.filter((r) => ['panic_selling', 'distribution'].includes(r.flowClass)).length;
        const de = sdSignals.filter((s) => ['D', 'E'].includes(s.supplyDemandRank)).length;
        const parts = [bad ? `売り圧力推定${bad}件` : '', de ? `需給D/E ${de}件` : ''].filter(Boolean);
        return parts.length ? `${parts.join(' / ')} / 例外サマリー・発掘` : '例外サマリー・フロー・需給・発掘(開いて確認)';
      })(),
      render: () => (
        <>
          <FlowAttributionSection />
          <SupplyDemandSection signals={sdSignals} />
          {/* V12.2.12: 銘柄カード全リストはAsset Deskへ一本化(情報マトリクスで
              全項目の移設を確認済み)。Todayは例外サマリー+deep-linkのみ。 */}
          <TodayAssetExceptions rows={assetExceptions} totalCount={assets.length}
            countsJa={assetCountsJa} aiStateJa={aiStateJa}
            onOpenAsset={(sym) => onNavigateToAsset?.(sym)}
            onOpenDesk={() => onNavigate('watchlist')} />
          <BuyCandidates />
        </>
      ),
    },
    {
      title: 'DECISION REVIEW', persistKey: 'g-review',
      conclusionJa: '自己採点と判断履歴(開いて確認)',
      render: () => (
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
      ),
    },
    {
      title: 'DATA & SYSTEM', persistKey: 'g-system',
      severityTone: dqNote ? dqNote.tone : undefined,
      conclusionJa: dqNote ? dqNote.textJa : 'データ品質・バックアップ・監視カバレッジ(開いて確認)',
      render: () => {
        const b = assessBackupSafety(assets);
        const dqc = latestDataQuality();
        return (
          <div className="card" style={{ fontSize: 12, color: 'var(--text-sub)', lineHeight: 1.7 }}>
            <p style={{ margin: 0 }}>
              <b style={{ color: 'var(--text-main)' }}>データ品質:</b> {dqc ? `${dqc.overallStatusJa}${dqc.topIssuesJa[0] ? ` — ${dqc.topIssuesJa[0]}` : ''}` : '未取得(Data Qualityページで確認)'}
            </p>
            {guard?.coverageLineJa && <p style={{ margin: '4px 0 0' }}>{guard.coverageLineJa}</p>}
            <p style={{ margin: '4px 0 0' }}>
              <b style={{ color: 'var(--text-main)' }}>バックアップ:</b> {b.protectionLevelJa ?? b.protectionLevel}
            </p>
            <p style={{ margin: '8px 0 0' }}>
              <button type="button" className="texp__cta" onClick={() => onNavigate('quality')}>Data Quality</button>
              <button type="button" className="texp__cta" style={{ marginLeft: 8 }} onClick={() => onNavigate('backup')}>Backup</button>
            </p>
          </div>
        );
      },
    },
  ];

  return (
    <PageShell
      title={tEn('page.today')}
      subtitle={<span>{formatDate(judgment.date)}</span>}
    >
      {/* OWNER CRITICAL — a held position on EXIT/DEFEND is surfaced at the very top
          (small), so a held emergency is never missed below the fold (v10.145). */}
      {ownerCritical.length > 0 && (
        <div className="owner-critical" role="alert">
          <span className="owner-critical__tag">OWNER CRITICAL</span>
          <span className="owner-critical__items">
            {ownerCritical.map((c) => (
              <button type="button" key={c.id} className="owner-critical__item owner-critical__item--link"
                title="Asset Deskでこの銘柄を開く"
                onClick={() => onNavigateToAsset?.(c.symbol)}>
                {c.symbol} {c.name} · {c.signalCode === 'EXIT' ? '撤退判断' : '資金防衛'} ↗
              </button>
            ))}
          </span>
        </div>
      )}

      {/* ── V12.2.11 ファーストビュー: 姿勢→変化→保有影響→行動→次の確認 ── */}
      <div className="today-grid">
        <div className="tg-span-12">
          <TodayStanceCard summary={commandSummary} positionRisk={positionRisk}
            isPartial={isPartial || visLimited}
            partialReasonsJa={partialReasonsJa}
            partialRaiseJa="JPリアルタイム復旧(ret=0確認後) / イベント・機関データの巡回更新 / 需給キャッシュのウォームで上限が上がります"
            visibilityReasonJa={al.data?.visibility?.downgradeReasonJa}
            coverageLineJa={guard?.coverageLineJa ?? null}
            judgment={judgment}
            sessionStatusJa={overview.sessionStatusJa} />
        </div>

        {/* ── ATTENTION(v12.2.11): 非critical警告を1領域に集約。構造上の最大4行
            (通知は1行に集約・展開で全文到達/他の行は対応ページへ遷移) — 項目が
            無言で消えることはない。同一問題の重複表示はしない(通知はnewのみ・
            戦略/FIRE/バックアップは各1行のソース関数が唯一の出所)。 */}
        <TodayAttention
          notifications={listNotifications()
            .filter((x) => x.deliveryState === 'new'
              && (x.severity === 'critical' || x.severity === 'high'))
            .map((n) => ({ id: n.id, severity: n.severity,
              toneVar: SEV_TONE[n.severity],
              titleJa: `[${SEV_JA[n.severity]}] ${n.titleJa}`, bodyJa: n.bodyJa }))}
          backupUnprotected={assessBackupSafety(assets).protectionLevel === 'unprotected'}
          strategyNote={todayStrategicNoteJa(portfolioStrategy)}
          fireNote={fireCoreTodayNoteJa(fireCore)}
          onNavigate={onNavigate}
        />

        <OvernightChangesCard headingEn={overview.sessionHeadingEn} changes={overview.changes} />
        <YourExposureCard exposures={overview.exposures}
          noHoldings={positionExposure.noHoldings} onNavigate={onNavigate}
          onOpenAsset={(sym) => onNavigateToAsset?.(sym)} />
        <TodayActionQueue actions={overview.actions}
          onOpenAsset={(sym) => onNavigateToAsset?.(sym)} />
        <NextCheckCard nextCheck={overview.nextCheck} />
      </div>

      {/* v11.20.0: AI Review Pack — Todayから直接コピー(自動送信なし) */}
      <p style={{ margin: '0 0 6px' }}><ProHandoffButton /></p>

      {/* ── Details / Deep Dive(役割別グループ・既存セクションを内包) ──
          重要イベントはMARKET DETAILS内(ヘッダーNextチップは
          argus:open-today-sectionイベントでグループを開いてからスクロール)。 */}
      <TodayDetails groups={detailGroups} />

      {/* v11.21.0: モバイル専用の下部要約バー(10秒把握・720px以下のみ) */}
      <MobileStickyCommand
        ownerModeJa={sessionBrief.ownerModeJa}
        p0Count={apItems.filter((i) => i.priorityRank === 'P0').length}
        nextEventJa={(() => {
          // v12.0.8追補: スティッキーバーも単一のイベント時計(右上Next/カードと一致)
          const pick = nextUpcomingEvent(impEvents?.events ?? [], Date.now());
          return pick ? pick.shortJa : null;
        })()}
        unreadCount={unreadCounts().total}
      />
    </PageShell>
  );
};

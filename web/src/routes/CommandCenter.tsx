import React, { useEffect, useMemo, useState } from 'react';
import { PageShell } from './PageShell';
import { HeroCard } from '../components/dashboard/HeroCard';
import { EventIntelligenceCard } from '../components/dashboard/EventIntelligenceCard';
import { MarketNewsCard } from '../components/dashboard/MarketNewsCard';
import { DownsideIncidentCard } from '../components/dashboard/DownsideIncidentCard';
import { useDownsideIncidents } from '../hooks/useDownsideIncidents';
import { MarketSessionLamps } from '../components/dashboard/MarketSessionLamps';
import { ActionPill } from '../components/action/ActionBadge';
import { recordJudgment, previousJudgment, recentJudgments } from '../lib/judgmentLog';
import { useLedgerSummary } from '../hooks/useLedgerSummary';
import { useAIJudgment } from '../hooks/useAIJudgment';
import { useActionLabels } from '../hooks/useActionLabels';
import { useMarketRegime } from '../hooks/useMarketRegime';
import { useEventRadar } from '../hooks/useEventRadar';
import { useAssets } from '../hooks/useAssets';
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
  const regime = useMarketRegime();
  const ev = useEventRadar();
  const { data: downside } = useDownsideIncidents();

  const phase = combinePhase(al.phase as TodayPhase, regime.phase as TodayPhase);
  const judgment = useMemo(
    () => deriveTodayJudgment(al.data, regime.data, ev.data, Date.now()),
    [al.data, regime.data, ev.data],
  );

  // 3-layer risk overlay for the hero (v10.103): a green global regime must not
  // hide a weak Japan tape or holder risk.
  const overlay = useMemo(() => ({
    globalRegime: downside?.globalRegime || regime.data?.regime?.label || 'UNKNOWN',
    jpIntradayOverlay: downside?.jpIntradayOverlay || 'NORMAL',
    holderRiskOverlay: downside?.holderRiskOverlay || 'NONE',
  }), [downside, regime.data]);
  const ownerAffected = !!downside?.ownerAffected;
  // Partial-data discipline: when data is incomplete, cap confidence at 0.60 and
  // flag PARTIAL so a HOLD never looks high-confidence on thin data.
  const isPartial = phase === 'partial';
  const baseConf = regime.data?.regime?.confidence ?? null;
  const cappedConf = isPartial && baseConf != null ? Math.min(baseConf, 0.60) : baseConf;

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
      title="Daily Command Center"
      subtitle={<span>{formatDate(judgment.date)}</span>}
    >
      <MarketSessionLamps />

      {/* When an owner/held asset is in a downside incident, the defense layer
          comes BEFORE the call so HOLD is never read in isolation (v10.103). */}
      {ownerAffected && <DownsideIncidentCard />}

      <HeroCard judgment={judgment} overlay={overlay} isPartialData={isPartial} confidence={cappedConf} />

      {!ownerAffected && <DownsideIncidentCard />}

      <MarketNewsCard />

      <EventIntelligenceCard />

      <section>
        <div className="section-head">
          <span className="section-head__title">Judgment Log</span>
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
              シナリオ的中率 <b>{Math.round((ledger.data.overall.hitRate ?? 0) * 100)}%</b>
              ・Brier <b>{ledger.data.overall.brierMean?.toFixed(3) ?? '—'}</b>
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
              的中率 <b>{Math.round((ledger.closepin.overall.hitRate ?? 0) * 100)}%</b>
              ・Brier <b>{ledger.closepin.overall.brierMean?.toFixed(3) ?? '—'}</b>
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

import React, { useEffect, useMemo, useState } from 'react';
import { PageShell } from './PageShell';
import { HeroCard } from '../components/dashboard/HeroCard';
import { TopRotations } from '../components/regime/TopRotations';
import { CompactWatchRow } from '../components/dashboard/CompactWatchRow';
import { CompactEventRow } from '../components/dashboard/CompactEventRow';
import { CompactCoreRow } from '../components/dashboard/CompactCoreRow';
import { ActionPill } from '../components/action/ActionBadge';
import { recordJudgment, previousJudgment, recentJudgments } from '../lib/judgmentLog';
import { useLedgerSummary } from '../hooks/useLedgerSummary';
import { useAIJudgment } from '../hooks/useAIJudgment';
import { useActionLabels } from '../hooks/useActionLabels';
import { useMarketRegime } from '../hooks/useMarketRegime';
import { useEventRadar } from '../hooks/useEventRadar';
import { useJapanWatchlist } from '../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../hooks/useUSWatchlist';
import { useMarketNews } from '../hooks/useMarketNews';
import { useAssets } from '../hooks/useAssets';
import {
  deriveTodayJudgment, toMarketEvents, mapRuleAction, coreActionFor, combinePhase,
  type TodayPhase,
} from '../lib/todayCall';
import { topRotations as mockRotations } from '../mock/regime';
import { genreOf } from '../types/assetItem';
import type { ActionKey } from '../types/action';
import type { TopRotation, } from '../types/regime';
import type { CorePosition } from '../types/dashboard';
import type { WatchEntry } from '../types/watch';
import type { RouteKey } from '../components/NavRail';
import '../components/dashboard/Dashboard.css';

interface Props {
  onNavigate: (key: RouteKey) => void;
}

// Today is a SUMMARY composed from LIVE data (action-labels + market-regime +
// events + watchlist quotes). Detail lives on the respective detail pages.
const URGENCY: Record<ActionKey, number> = {
  EXIT: 0,
  TRIM: 1,
  WAIT_FOR_PULLBACK: 2,
  WAIT: 3,
  BUY_DIP: 4,
  ADD: 5,
  HOLD: 6,
};

const PRIORITY_WATCH_LIMIT = 3;
const PREVIEW_EVENT_LIMIT = 3;

// Compact aliases for the core preview, keyed by the asset symbol.
const CORE_SHORT: Record<string, string> = {
  'EMAXIS-ACWI':  'Global Core (NISA)',
  'EMAXIS-SP500': 'US Core (NISA)',
};

const PHASE_COLOR: Record<TodayPhase, string> = {
  live: 'var(--green)', partial: 'var(--amber)', mock: 'var(--text-muted)', connecting: 'var(--text-muted)',
};

const formatDate = (iso: string) => {
  const d = new Date(`${iso}T00:00:00+09:00`);
  return d.toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  });
};

export const CommandCenter: React.FC<Props> = ({ onNavigate }) => {
  const { assets } = useAssets();
  const ledger = useLedgerSummary();
  const news = useMarketNews();
  const aiJ = useAIJudgment();
  const aiStateJa = useMemo(() => {
    if (aiJ.phase === 'connecting') return null;
    if (aiJ.data && (aiJ.data.status === 'live' || aiJ.data.status === 'partial')) {
      const t = Date.parse(aiJ.data.asOf);
      const m = Number.isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 60000)) : null;
      const age = m == null ? '' : m < 60 ? `${m}分前` : `${Math.round(m / 60)}時間前`;
      return `🤖 AI見解: ${age}の実行(${aiJ.data.status})。次回は平日16:05に自動実行。`;
    }
    return '🤖 AI見解: 直近の実行なし(平日16:05に自動実行。それまではルール判定のみ)。';
  }, [aiJ.data, aiJ.phase]);
  // The engine follows the USER's actual watchlist (dynamic symbols, v9.8).
  const jpSyms = useMemo(() => assets.filter((a) => a.market === 'JP').map((a) => a.symbol), [assets]);
  const usSyms = useMemo(() => assets.filter((a) => a.market === 'US').map((a) => a.symbol), [assets]);
  const al = useActionLabels({ jp: jpSyms, us: usSyms });
  const regime = useMarketRegime();
  const ev = useEventRadar();
  const jp = useJapanWatchlist(jpSyms);
  const us = useUSWatchlist(usSyms);

  const phase = combinePhase(al.phase as TodayPhase, regime.phase as TodayPhase);
  const judgment = useMemo(
    () => deriveTodayJudgment(al.data, regime.data, ev.data, Date.now()),
    [al.data, regime.data, ev.data],
  );

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
      confidence: regime.data?.regime?.confidence ?? null,
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

  // Live Top Rotations (mock fallback only when the regime engine is unreachable).
  const rotations: TopRotation[] = useMemo(() => {
    const live = regime.data?.topRotations ?? [];
    if (live.length === 0) return regime.phase === 'mock' ? mockRotations : [];
    return live.map((t) => {
      const [from, to] = t.label.split(' -> ');
      return { from: from ?? t.label, to: to ?? '' };
    });
  }, [regime.data, regime.phase]);

  // Priority watchlist: real action labels + live quotes, most urgent first.
  // Rows without a quote are skipped — no fake prices on the home page.
  const { priority, totalNamed } = useMemo(() => {
    // LIVE quotes only — a mock fallback price must never appear on Today.
    const quotes = new Map<string, { price: number; changePct: number; changeAbs: number; volume: number }>();
    for (const s of jp.data?.stocks ?? []) if (s.status === 'live') quotes.set(s.symbol, s);
    for (const s of us.data?.stocks ?? []) if (s.status === 'live') quotes.set(s.symbol, s);
    const entries: (WatchEntry & { __conf: number })[] = [];
    for (const l of al.data?.labels ?? []) {
      const q = quotes.get(l.symbol);
      if (!q) continue;
      const base = {
        symbol: l.symbol, name: l.name,
        price: q.price, changePct: q.changePct, changeAbs: q.changeAbs,
        action: mapRuleAction(l.action), reason: l.reasonJa,
        updatedAt: judgment.updatedAt, confidence: l.confidence,
        __conf: l.confidence,
      };
      entries.push(l.market === 'JP'
        ? { ...base, market: 'JP', volume: q.volume }
        : { ...base, market: 'US', volume: q.volume });
    }
    entries.sort((a, b) =>
      (URGENCY[a.action] - URGENCY[b.action]) ||
      (Math.abs(b.changePct) - Math.abs(a.changePct)));
    return { priority: entries.slice(0, PRIORITY_WATCH_LIMIT), totalNamed: entries.length };
  }, [al.data, jp.data, us.data, judgment.updatedAt]);

  // Live event preview (urgent first).
  const events = useMemo(
    () => toMarketEvents(ev.data, judgment.updatedAt).slice(0, PREVIEW_EVENT_LIMIT),
    [ev.data, judgment.updatedAt],
  );

  // Core preview from the user's actual core/fund assets + posture-aware label.
  const corePositions: CorePosition[] = useMemo(() => {
    const act = coreActionFor(al.data?.marketPosture?.label);
    return assets
      .filter((a) => genreOf(a) === 'funds')
      .slice()
      .sort((a, b) => a.sortOrder - b.sortOrder)
      .map((a) => ({
        symbol: a.symbol,
        name: a.displayNameJa || a.displayName,
        market: 'JP' as const,
        action: act.action,
        reason: act.reason,
      }));
  }, [assets, al.data]);

  return (
    <PageShell
      title="Daily Command Center"
      subtitle={
        <span>
          {formatDate(judgment.date)}
          <span className="today-phase" style={{ color: PHASE_COLOR[phase] }}>
            {' '}· {phase === 'connecting' ? 'connecting…' : phase}
          </span>
        </span>
      }
    >
      <HeroCard judgment={judgment} />

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
            </div>
          )}
          {/* closepin-v1: same-day 14:30-pin → close scoring,独立した第二台帳 */}
          {ledger.closepin?.overall?.hitRate != null ? (
            <div className="jlog__acc">
              🎯 引けピン(14:30→同日終値・{ledger.closepin.overall.days}日 / {ledger.closepin.overall.n}件):
              的中率 <b>{Math.round((ledger.closepin.overall.hitRate ?? 0) * 100)}%</b>
              ・Brier <b>{ledger.closepin.overall.brierMean?.toFixed(3) ?? '—'}</b>
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

      {news.data && news.data.items.length > 0 && (
        <section>
          <div className="section-head">
            <span className="section-head__title">Market News</span>
            <span className="section-head__count">速報・参考(英語)</span>
          </div>
          <div className="card mnews">
            {news.data.items.slice(0, 6).map((n) => (
              <a className={`mnews__row${n.major ? ' mnews__row--major' : ''}`}
                 key={n.url || n.headline} href={n.url} target="_blank" rel="noreferrer">
                <span className="mnews__flag">{n.major ? '⚡' : '・'}</span>
                <span className="mnews__head">{n.headline}</span>
                <span className="mnews__meta">
                  {n.source}{n.datetime ? ` · ${Math.max(0, Math.round((Date.now() / 1000 - n.datetime) / 60))}分前` : ''}
                </span>
              </a>
            ))}
            <div className="mnews__note">{news.data.noteJa}</div>
          </div>
        </section>
      )}

      <section>
        <div className="section-head">
          <span className="section-head__title">Top Rotations</span>
          <button
            className="section-head__link"
            onClick={() => {
              // Signal Market Regime to scroll to the full board after it mounts.
              try { sessionStorage.setItem('argus.scrollTo', 'full-board'); } catch { /* ignore */ }
              onNavigate('regime');
            }}
          >
            full board
          </button>
        </div>
        {rotations.length > 0 ? (
          <TopRotations rotations={rotations} />
        ) : (
          <div className="card"><p className="today-connecting">
            {regime.phase === 'connecting'
              ? 'connecting… 資金ローテーションを取得中'
              : '現在、明確な資金ローテーション(優位な資金移動)は検出されていません。'}
          </p></div>
        )}
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Priority watchlist</span>
          <button className="section-head__link" onClick={() => onNavigate('watchlist')}>
            {priority.length} of {totalNamed} names · view all
          </button>
        </div>
        <div className="card watch-list">
          {priority.length > 0
            ? priority.map((row) => <CompactWatchRow key={row.symbol} entry={row} />)
            : <p className="today-connecting">connecting… ライブ価格と行動ラベルを取得中</p>}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Event Radar</span>
          <button className="section-head__link" onClick={() => onNavigate('events')}>
            next {events.length}
          </button>
        </div>
        <div className="card event-list">
          {events.length > 0
            ? events.map((e) => <CompactEventRow key={e.id} event={e} />)
            : <p className="today-connecting">connecting… イベントカレンダーを取得中</p>}
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">Core Portfolio</span>
          <button className="section-head__link" onClick={() => onNavigate('core')}>
            {corePositions.length} positions
          </button>
        </div>
        <div className="card core-list">
          {corePositions.map((p) => (
            <CompactCoreRow
              key={p.symbol}
              position={p}
              shortLabel={CORE_SHORT[p.symbol]}
            />
          ))}
        </div>
      </section>
    </PageShell>
  );
};

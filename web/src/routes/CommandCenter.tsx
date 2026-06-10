import React, { useMemo } from 'react';
import { PageShell } from './PageShell';
import { HeroCard } from '../components/dashboard/HeroCard';
import { TopRotations } from '../components/regime/TopRotations';
import { CompactWatchRow } from '../components/dashboard/CompactWatchRow';
import { CompactEventRow } from '../components/dashboard/CompactEventRow';
import { CompactCoreRow } from '../components/dashboard/CompactCoreRow';
import { useActionLabels } from '../hooks/useActionLabels';
import { useMarketRegime } from '../hooks/useMarketRegime';
import { useEventRadar } from '../hooks/useEventRadar';
import { useJapanWatchlist } from '../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../hooks/useUSWatchlist';
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
  const al = useActionLabels();
  const regime = useMarketRegime();
  const ev = useEventRadar();
  const jp = useJapanWatchlist();
  const us = useUSWatchlist();
  const { assets } = useAssets();

  const phase = combinePhase(al.phase as TodayPhase, regime.phase as TodayPhase);
  const judgment = useMemo(
    () => deriveTodayJudgment(al.data, regime.data, ev.data, Date.now()),
    [al.data, regime.data, ev.data],
  );

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
    const quotes = new Map<string, { price: number; changePct: number; changeAbs: number; volume: number }>();
    for (const s of jp.data?.stocks ?? []) quotes.set(s.symbol, s);
    for (const s of us.data?.stocks ?? []) quotes.set(s.symbol, s);
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

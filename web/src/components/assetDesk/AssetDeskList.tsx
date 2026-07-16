import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  DndContext, closestCenter, PointerSensor, KeyboardSensor, useSensor, useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, arrayMove, useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useAssetIntel } from '../../hooks/useAssetIntel';
import { useCatalysts } from '../../hooks/useCatalysts';
import { useFundNav } from '../../hooks/useFundNav';
import { coingeckoIdOf } from '../../lib/cryptoIds';
import { deriveStrategy, type QuoteLite } from '../../lib/assetStrategy';
import { holderPosture } from '../../lib/holderPosture';
import { GENRES, genreOf, type AssetItem } from '../../types/assetItem';
import type { ActionLabel } from '../../types/actionLabels';
import type { CatalystItem } from '../../types/catalysts';
import type { DownsideIncident } from '../../hooks/useDownsideIncidents';
import { deskRank, DESK_RANK_JA, type DeskRankInput, type DeskGenre } from '../../domain/assetDesk';
import type { DeskCardData, DeskEventTag, DeskSection } from './types';
import { sectionAnchorId, DESK_SECTIONS } from './types';
import { AssetDecisionCard } from './AssetDecisionCard';
import { t } from '../../i18n';
import './AssetDesk.css';

// V12.2.12 — Asset Deskリスト(旧AssetStrategySectionの後継)。
// データ組み立てはuseAssetIntel(publish:false — 閲覧でpublish副作用なし)+
// 判断はdomain/assetDecision経由 — Todayと構造的に同一の判断を表示する。
// 並び: デフォルト=優先順(domain/assetDesk決定論ソート)/手動順=従来のDnD。

export interface AssetFocusIntent { symbol: string; section?: string; nonce: number }

interface Props {
  assets: AssetItem[];
  onReorder: (orderedIds: string[]) => void;
  onRemove: (id: string) => void;
  onUpdateHolding: (id: string, h: { quantity?: number | null; avgCost?: number | null }) => void;
  focus?: AssetFocusIntent | null;
}

// 手動順モードの行(DnDハンドル+カード)
const SortableCardRow: React.FC<{
  id: string; children: (handle: React.ReactNode) => React.ReactNode;
}> = ({ id, children }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const style: React.CSSProperties = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.6 : 1 };
  return (
    <div ref={setNodeRef} style={style}>
      {children(
        <button className="ad-handle" aria-label={`Reorder ${id}`} {...attributes} {...listeners}>⋮⋮</button>,
      )}
    </div>
  );
};

export const AssetDeskList: React.FC<Props> = ({ assets, onReorder, onRemove, onUpdateHolding, focus }) => {
  const intel = useAssetIntel({ publish: false });
  const cat = useCatalysts();
  const { funds: navFunds } = useFundNav();
  const mountTs = useMemo(() => Date.now(), []);
  const [nowMs] = useState(() => Date.now());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<'priority' | 'manual'>('priority');
  const [filter, setFilter] = useState<'all' | 'risk' | 'held'>('all');
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // ── quotes/labels/cats/incidents(旧AssetStrategySection.mapsを移設) ──
  const maps = useMemo(() => {
    const quotes = new Map<string, QuoteLite>();
    for (const s of intel.jpQuotes.data?.stocks ?? []) quotes.set(s.symbol, { price: s.price, changePct: s.changePct, volume: s.volume, date: s.date, status: s.status, flow: s.flow ?? null, name: s.name });
    for (const s of intel.usQuotes.data?.stocks ?? []) quotes.set(s.symbol, { price: s.price, changePct: s.changePct, volume: s.volume, date: s.date, status: s.status, flow: s.flow ?? null, name: s.name });
    for (const a of assets) {
      if (a.market !== 'CRYPTO') continue;
      const id = coingeckoIdOf(a);
      const q = id ? intel.cryptoWatch.byId[id] : undefined;
      if (q) quotes.set(a.symbol, { price: q.priceUsd, changePct: q.changePct, volume: q.volume, date: q.date, status: q.status });
    }
    const labels = new Map<string, ActionLabel>();
    for (const l of intel.al.data?.labels ?? []) labels.set(l.symbol, l);
    const cats = new Map<string, CatalystItem>();
    for (const c of cat.data?.items ?? []) cats.set(c.symbol, c);
    const downsideBySym = new Map<string, DownsideIncident>();
    for (const inc of intel.downside?.incidents ?? []) downsideBySym.set(inc.symbol, inc);
    // 投信(基準価額): fund資産をカタログNAVへ名寄せ(旧実装のまま)
    const navByName = (a: AssetItem) => {
      const sym = (a.symbol || '').toUpperCase();
      const nm = `${a.displayName || ''} ${a.displayNameJa || ''}`.toLowerCase();
      const want = (kw: string) => sym.includes(kw) || nm.includes(kw.toLowerCase());
      for (const f of navFunds) {
        const fn = (f.name || '').toLowerCase();
        if (fn.includes('全世界') && (want('ACWI') || nm.includes('全世界') || nm.includes('オルカン') || nm.includes('オール'))) return f;
        if (fn.includes('s&p500') && (want('SP500') || want('S&P') || nm.includes('米国'))) return f;
        if (fn.includes('国内') && (want('N225') || want('NIKKEI') || nm.includes('国内') || nm.includes('日経'))) return f;
      }
      return null;
    };
    for (const a of assets) {
      if (genreOf(a) === 'funds') {
        const f = navByName(a);
        if (f) quotes.set(a.symbol, { price: f.navYen, changePct: f.changePct ?? 0, volume: 0, date: f.date, status: 'live' });
      }
    }
    return { quotes, labels, cats, downsideBySym };
  }, [intel.jpQuotes.data, intel.usQuotes.data, intel.cryptoWatch.byId, intel.al.data, cat.data, intel.downside, navFunds, assets]);

  // イベントタグ(全countdown — 閉じたカードは先頭2件のみ表示)
  const eventTagsBySym = useMemo(() => {
    const m = new Map<string, DeskEventTag[]>();
    for (const ie of intel.impEvents?.events ?? []) {
      for (const a of ie.linkedAssets ?? []) {
        const k = String(a).toUpperCase();
        const arr = m.get(k) ?? [];
        arr.push({ code: ie.eventCode, countdown: ie.countdown, impact: ie.displayImpact.toUpperCase() });
        m.set(k, arr);
      }
    }
    return m;
  }, [intel.impEvents]);

  // ── カードデータ束の組み立て(表示専用・判断は生成しない) ──
  const rows = useMemo(() => {
    const aiBySym = new Map((intel.aiJ.data?.labels ?? []).map((l) => [l.symbol.toUpperCase(), l]));
    const sdBySym = new Map(intel.sdSignals.map((s) => [s.symbol.toUpperCase(), s]));
    const apBySym = new Map(intel.apItems.map((it) => [it.symbol, it]));
    const scBySym = new Map(intel.scenarioSets.map((s) => [s.symbol, s]));
    const plBySym = new Map(intel.positionPlans.map((p) => [p.symbol, p]));
    const riskBySym = new Map(intel.positionExposure.risks.map((r) => [r.symbol, r.riskLevel]));
    return assets.map((a) => {
      const sym = a.symbol.toUpperCase();
      const genre = genreOf(a) as DeskGenre;
      const quote = maps.quotes.get(a.symbol);
      const strat = deriveStrategy(a, maps.labels.get(a.symbol), quote, maps.cats.get(a.symbol), mountTs);
      const incident = maps.downsideBySym.get(a.symbol);
      const card = intel.cardBySym.get(sym);
      const decision = (genre === 'jp' || genre === 'us') ? intel.decisionBySym.get(sym) : undefined;
      const apx = apBySym.get(sym);
      const pn = intel.positionExposure.notes[sym];
      const eventTags = eventTagsBySym.get(sym) ?? [];
      const held = !!pn?.held || (a.quantity ?? 0) > 0;
      const rankInput: DeskRankInput = {
        symbol: sym, genre, held,
        signalCode: card?.signalCode ?? null,
        apRank: apx?.priorityRank ?? null,
        positionRiskLevel: riskBySym.get(sym) ?? null,
        hasIncident: !!incident,
        aiRuleDisagree: !!decision?.rule.disagreementJa,
        eventSoon: eventTags.some((e) => e.countdown === 'D' || e.countdown === 'D-1'),
      };
      const d: DeskCardData = {
        asset: a, genre, rank: deskRank(rankInput),
        card, decision, strat, quote,
        liveName: quote?.name ?? null,
        incident,
        hp: holderPosture(a, strat, incident),
        pn,
        sdg: sdBySym.get(sym),
        apx,
        scn: scBySym.get(sym),
        ppl: plBySym.get(sym),
        pst: intel.stanceBySymbol.get(sym),
        aiLabel: aiBySym.get(sym),
        aiAgeMin: intel.aiMeta.ageMin,
        aiMeta: intel.aiMeta,
        eventTags,
      };
      return { d, rankInput };
    });
  }, [assets, maps, intel.cardBySym, intel.decisionBySym, intel.aiJ.data, intel.sdSignals,
      intel.apItems, intel.scenarioSets, intel.positionPlans, intel.positionExposure,
      intel.stanceBySymbol, intel.aiMeta, eventTagsBySym, mountTs]);

  const riskCount = useMemo(() => rows.filter((r) => !!r.d.incident).length, [rows]);
  const keep = (r: { d: DeskCardData }) => filter === 'all' ? true
    : filter === 'risk' ? !!r.d.incident
    : (r.d.asset.quantity ?? 0) > 0 || !!r.d.pn?.held;

  // 優先順(デフォルト・決定論): rank昇順→symbol昇順。
  const prioritized = useMemo(() =>
    rows.slice().sort((a, b) => a.d.rank - b.d.rank
      || (a.d.asset.symbol < b.d.asset.symbol ? -1 : a.d.asset.symbol > b.d.asset.symbol ? 1 : 0)),
    [rows]);

  // 手動順: 従来のgenreグループ+sortOrder+DnD。
  const manualGroups = useMemo(() => {
    const bySym = new Map(rows.map((r) => [r.d.asset.id, r]));
    return GENRES.map((g) => ({
      ...g,
      items: assets.filter((a) => genreOf(a) === g.key)
        .slice().sort((a, b) => a.sortOrder - b.sortOrder)
        .map((a) => bySym.get(a.id)!).filter(Boolean),
    })).filter((g) => g.items.length > 0);
  }, [rows, assets]);

  // ── Deep-link(Todayから): 展開+スクロール(即時+700ms settle再固定) ──
  const lastNonce = useRef<number>(0);
  useEffect(() => {
    if (!focus || focus.nonce === lastNonce.current) return;
    const row = rows.find((r) => r.d.asset.symbol.toUpperCase() === focus.symbol.toUpperCase());
    if (!row) return;   // 未登録銘柄: 何もしない(捏造スクロールなし)
    lastNonce.current = focus.nonce;
    setExpandedId(row.d.asset.id);
    const section = focus.section && (DESK_SECTIONS as readonly string[]).includes(focus.section)
      ? focus.section as DeskSection : undefined;
    const scroll = () => {
      const el = document.getElementById(sectionAnchorId(focus.symbol, section))
        ?? document.getElementById(sectionAnchorId(focus.symbol));
      el?.scrollIntoView({ block: 'start' });
    };
    // 展開レンダー後に即時スクロール→遅延ロードで高さが変わるため700msで再固定
    window.setTimeout(scroll, 50);
    window.setTimeout(scroll, 750);
  }, [focus, rows]);

  function onDragEnd(groupIds: string[]) {
    return (e: DragEndEvent) => {
      if (filter !== 'all' || sortMode !== 'manual') return;
      const { active, over } = e;
      if (!over || active.id === over.id) return;
      const from = groupIds.indexOf(String(active.id));
      const to = groupIds.indexOf(String(over.id));
      if (from < 0 || to < 0) return;
      onReorder(arrayMove(groupIds, from, to));
    };
  }

  if (assets.length === 0) {
    return <div className="card asset-list"><div className="asset-empty">資産がありません。「+ Add Asset」で追加できます。</div></div>;
  }

  const cal = intel.al.data?.calibration;
  const connecting = intel.jpQuotes.phase === 'connecting' && intel.usQuotes.phase === 'connecting';

  const renderCard = (r: { d: DeskCardData }, handle?: React.ReactNode) => (
    <AssetDecisionCard
      key={r.d.asset.id}
      d={r.d}
      open={expandedId === r.d.asset.id}
      onToggle={() => setExpandedId((cur) => (cur === r.d.asset.id ? null : r.d.asset.id))}
      onRemove={(id) => { setExpandedId((cur) => (cur === id ? null : cur)); onRemove(id); }}
      onUpdateHolding={onUpdateHolding}
      nowMs={nowMs}
      dragHandle={handle}
    />
  );

  return (
    <div className="asset-groups">
      {cal && (
        <div className="asset-calibration" title="予測台帳の採点成績が確信度に反映されます(calibration-v1)">
          🎯 校正: {cal.basisJa}
        </div>
      )}
      {connecting && <div className="asset-empty asset-empty--card">connecting… 最新の判断を取得中</div>}
      <div className="asset-filter">
        <button className={`asset-filter__chip${sortMode === 'priority' ? ' is-active' : ''}`}
                onClick={() => setSortMode('priority')} title="今日見るべき順(保有×緊急→リスク→イベント→その他)">優先順</button>
        <button className={`asset-filter__chip${sortMode === 'manual' ? ' is-active' : ''}`}
                onClick={() => setSortMode('manual')} title="ジャンル別・手動並べ替え(ドラッグ)">手動順</button>
        <span className="ad-filter-sep" aria-hidden>|</span>
        <button className={`asset-filter__chip${filter === 'all' ? ' is-active' : ''}`} onClick={() => setFilter('all')}>{t('wl.filterAll')}</button>
        <button className={`asset-filter__chip asset-filter__chip--risk${filter === 'risk' ? ' is-active' : ''}`} onClick={() => setFilter('risk')}>
          {t('wl.filterDanger')}{riskCount > 0 ? ` (${riskCount})` : ''}
        </button>
        <button className={`asset-filter__chip${filter === 'held' ? ' is-active' : ''}`} onClick={() => setFilter('held')}>{t('wl.filterHeld')}</button>
        {sortMode === 'manual' && filter !== 'all' && <span className="asset-filter__note">{t('wl.filterNoReorder')}</span>}
      </div>

      {sortMode === 'priority' && (
        <div className="card asset-list ad-list">
          {prioritized.filter(keep).map((r, i, arr) => (
            <React.Fragment key={r.d.asset.id}>
              {(i === 0 || arr[i - 1].d.rank !== r.d.rank) && (
                <div className="ad-rank-head">{DESK_RANK_JA[r.d.rank]}</div>
              )}
              {renderCard(r)}
            </React.Fragment>
          ))}
          {prioritized.filter(keep).length === 0 && (
            <div className="asset-empty">{filter === 'risk' ? t('wl.noDanger') : t('wl.noHeld')}</div>
          )}
        </div>
      )}

      {sortMode === 'manual' && manualGroups.map((g) => {
        const shown = g.items.filter(keep);
        if (shown.length === 0) return null;
        const ids = g.items.map((r) => r.d.asset.id);
        return (
          <section className="asset-group" key={g.key}>
            <div className="asset-group__title">{g.title}<span className="asset-group__count">{shown.length}</span></div>
            <div className="card asset-list ad-list">
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd(ids)}>
                <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                  {shown.map((r) => (
                    <SortableCardRow key={r.d.asset.id} id={r.d.asset.id}>
                      {(handle) => renderCard(r, filter === 'all' ? handle : undefined)}
                    </SortableCardRow>
                  ))}
                </SortableContext>
              </DndContext>
            </div>
          </section>
        );
      })}
    </div>
  );
};

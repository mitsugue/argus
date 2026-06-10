import React, { useMemo } from 'react';
import {
  DndContext, closestCenter, PointerSensor, KeyboardSensor, useSensor, useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, arrayMove, useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useJapanWatchlist } from '../../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../../hooks/useUSWatchlist';
import { useCryptoWatchlist } from '../../hooks/useCryptoWatchlist';
import { useActionLabels } from '../../hooks/useActionLabels';
import { useCatalysts } from '../../hooks/useCatalysts';
import { deriveStrategy, type AssetStrategy, type QuoteLite } from '../../lib/assetStrategy';
import { GENRES, genreOf, type AssetItem } from '../../types/assetItem';
import type { ActionLabel } from '../../types/actionLabels';
import type { CatalystItem } from '../../types/catalysts';

interface Props {
  assets: AssetItem[];
  onReorder: (orderedIds: string[]) => void;
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  onRemove: (id: string) => void;
}

const ACTION_COLOR: Record<string, string> = {
  EXIT: 'var(--red)', TRIM: 'var(--red)', 'WAIT FOR PULLBACK': 'var(--amber)',
  WAIT: 'var(--blue)', 'BUY DIP': 'var(--green)', ADD: 'var(--green)', HOLD: 'var(--text-sub)',
  CONTINUE: 'var(--green)', 'GRADUAL ADD': 'var(--green)', 'DEFER LUMP SUM': 'var(--amber)', 'NO SELL ACTION': 'var(--text-sub)',
};
const STATUS_COLOR: Record<string, string> = {
  live: 'var(--green)', partial: 'var(--amber)', mock: 'var(--amber)', manual: 'var(--text-muted)',
};

function fmtPrice(market: string, v?: number): string {
  if (v == null) return '—';
  if (market === 'JP') return `¥${Math.round(v).toLocaleString('en-US')}`;
  if (market === 'US') return `$${v.toFixed(2)}`;
  if (market === 'CRYPTO') {
    return v >= 1000 ? `$${Math.round(v).toLocaleString('en-US')}` : `$${v.toFixed(2)}`;
  }
  return String(v);
}
function fmtPct(p?: number): string {
  if (p == null) return '';
  const s = p > 0 ? '+' : p < 0 ? '−' : '';
  return `${s}${Math.abs(p).toFixed(2)}%`;
}
function pctClass(p?: number): string {
  if (p == null) return 'asset-row__chg';
  if (p > 0.05) return 'asset-row__chg asset-row__chg--up';
  if (p < -0.05) return 'asset-row__chg asset-row__chg--down';
  return 'asset-row__chg';
}
function ageMin(ts: number): string {
  const m = Math.max(0, Math.round((Date.now() - ts) / 60000));
  return m < 1 ? 'just now' : `${m}m ago`;
}

// ── Data-freshness honesty ──
// J-Quants free plan lags ~12 weeks: a quote can be "live" (really fetched)
// yet months old. Surface that as an amber "delayed Xw" instead of a green
// "live" — an investment app must never dress stale data as fresh.
function lagDays(date?: string | null): number | null {
  if (!date) return null;
  const t = Date.parse(`${date}T00:00:00+09:00`);
  if (!Number.isFinite(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
}

function freshnessOf(strat: AssetStrategy): { text: string; color: string } {
  if (strat.status === 'manual') return { text: 'manual', color: STATUS_COLOR.manual };
  if (strat.status === 'mock')   return { text: 'mock',   color: STATUS_COLOR.mock };
  const lag = lagDays(strat.date);
  if (lag != null && lag > 7) {
    const text = lag >= 14 ? `delayed ${Math.round(lag / 7)}w` : `delayed ${lag}d`;
    return { text, color: 'var(--amber)' };
  }
  return { text: strat.status, color: STATUS_COLOR[strat.status] ?? 'var(--text-muted)' };
}

const SortableAssetRow: React.FC<{
  asset: AssetItem; strat: AssetStrategy; expanded: boolean;
  onToggleExpand: (id: string) => void; onRemove: (id: string) => void;
}> = ({ asset, strat, expanded, onToggleExpand, onRemove }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: asset.id });
  const style: React.CSSProperties = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.6 : 1 };
  const name = asset.displayNameJa || asset.displayName;
  const fresh = freshnessOf(strat);
  // Mock rows never show plausible-but-fake numbers — "—" instead.
  const priceShown = strat.status === 'mock' ? undefined : strat.price;
  const chgShown   = strat.status === 'mock' ? undefined : strat.changePct;

  return (
    <div ref={setNodeRef} style={style} className={`asset-row${expanded ? ' asset-row--open' : ''}${isDragging ? ' asset-row--drag' : ''}`}>
      <div className="asset-row__head">
        <button className="asset-row__handle" aria-label={`Reorder ${asset.symbol}`} {...attributes} {...listeners}>⋮⋮</button>
        <button
          className="asset-row__main"
          aria-expanded={expanded}
          onClick={() => onToggleExpand(asset.id)}
        >
          <span className="asset-row__caret">{expanded ? '▾' : '▸'}</span>
          <span className="asset-row__id">
            <span className="asset-row__sym">{asset.symbol}</span>
            <span className="asset-row__name">{name}</span>
          </span>
          <span className="asset-row__price">{fmtPrice(asset.market, priceShown)}</span>
          <span className={pctClass(chgShown)}>{fmtPct(chgShown)}</span>
          <span className="asset-row__action" style={{ color: ACTION_COLOR[strat.action] ?? 'var(--text-sub)' }}>{strat.action}</span>
          <span className="asset-row__meta">
            {strat.risk !== '—' && <span>risk {strat.risk}</span>}
            {strat.confidence != null && <span>· {Math.round(strat.confidence * 100)}%</span>}
          </span>
          <span className="asset-row__status" style={{ color: fresh.color }}>{fresh.text}</span>
        </button>
      </div>

      {expanded && (
        <div className="asset-row__detail">
          <div className="asset-detail__grid">
            <div><span className="asset-detail__k">Strategy</span><span className="asset-detail__v">{strat.strategyJa}</span></div>
            <div><span className="asset-detail__k">Why</span><span className="asset-detail__v">{strat.reasonJa}</span></div>
            <div><span className="asset-detail__k">What to wait for</span><span className="asset-detail__v">{strat.nextConditionJa}</span></div>
            <div><span className="asset-detail__k">What changes it</span><span className="asset-detail__v">{strat.whatChangesJa}</span></div>
            {strat.catalystNoteJa && <div><span className="asset-detail__k">Catalyst</span><span className="asset-detail__v">{strat.catalystNoteJa}</span></div>}
          </div>
          {strat.scenarios.length > 0 && (
            <div className="asset-scen">
              <div className="asset-scen__head">Scenario probabilities · {strat.scenarioHorizonJa}</div>
              {strat.scenarios.map((s) => (
                <div className="asset-scen__row" key={s.label}>
                  <span className="asset-scen__label">{s.labelJa}</span>
                  <span className="asset-scen__bar"><span style={{ width: `${s.probability}%` }} /></span>
                  <span className="asset-scen__pct">{s.probability}%</span>
                  <span className="asset-scen__why">{s.rationaleJa}</span>
                </div>
              ))}
              <div className="asset-scen__disc">{strat.scenarioDisclaimerJa}</div>
            </div>
          )}
          {strat.dataLimitations.length > 0 && (
            <div className="asset-detail__limits">
              <span className="asset-detail__k">Data limitations</span>
              <ul>{strat.dataLimitations.map((d, i) => <li key={i}>{d}</li>)}</ul>
            </div>
          )}
          <div className="asset-detail__foot">
            <span>updated {ageMin(strat.lastUpdated)}</span>
            <span className="asset-detail__actions">
              <button className="asset-mini asset-mini--danger" aria-label={`Remove ${asset.symbol}`} onClick={() => onRemove(asset.id)}>Remove</button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export const AssetStrategySection: React.FC<Props> = ({ assets, onReorder, expandedId, onToggleExpand, onRemove }) => {
  // Dynamic mode: the engine follows the USER's actual assets — symbols added
  // via the UI get live quotes AND rule labels (no longer the fixed 11).
  const jpSyms = useMemo(() => assets.filter((a) => a.market === 'JP').map((a) => a.symbol), [assets]);
  const usSyms = useMemo(() => assets.filter((a) => a.market === 'US').map((a) => a.symbol), [assets]);
  const jp = useJapanWatchlist(jpSyms);
  const us = useUSWatchlist(usSyms);
  const al = useActionLabels({ jp: jpSyms, us: usSyms });
  const cat = useCatalysts();
  // Crypto quotes via CoinGecko: each crypto asset stores its id in the memo
  // as "coingecko:<id>" (the seed assets and symbol-search both do this).
  const cryptoPairs = useMemo(
    () => assets
      .filter((a) => a.market === 'CRYPTO')
      .map((a) => ({ symbol: a.symbol, id: (a.memo ?? '').startsWith('coingecko:') ? (a.memo as string).slice('coingecko:'.length) : '' }))
      .filter((p) => p.id),
    [assets],
  );
  const cryptoIds = useMemo(() => cryptoPairs.map((p) => p.id), [cryptoPairs]);
  const crypto = useCryptoWatchlist(cryptoIds);
  const mountTs = useMemo(() => Date.now(), []);  // stable per mount/rescan
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const maps = useMemo(() => {
    const quotes = new Map<string, QuoteLite>();
    for (const s of jp.data?.stocks ?? []) quotes.set(s.symbol, { price: s.price, changePct: s.changePct, volume: s.volume, date: s.date, status: s.status });
    for (const s of us.data?.stocks ?? []) quotes.set(s.symbol, { price: s.price, changePct: s.changePct, volume: s.volume, date: s.date, status: s.status });
    for (const p of cryptoPairs) {
      const q = crypto.byId[p.id];
      if (q) quotes.set(p.symbol, { price: q.priceUsd, changePct: q.changePct, volume: q.volume, date: q.date, status: q.status });
    }
    const labels = new Map<string, ActionLabel>();
    for (const l of al.data?.labels ?? []) labels.set(l.symbol, l);
    const cats = new Map<string, CatalystItem>();
    for (const c of cat.data?.items ?? []) cats.set(c.symbol, c);
    return { quotes, labels, cats };
  }, [jp.data, us.data, al.data, cat.data, crypto.byId, cryptoPairs]);

  // Group by genre (GENRES order), each sorted by sortOrder ascending.
  const groups = useMemo(() => {
    return GENRES.map((g) => ({
      ...g,
      items: assets.filter((a) => genreOf(a) === g.key).slice().sort((a, b) => a.sortOrder - b.sortOrder),
    })).filter((g) => g.items.length > 0);
  }, [assets]);

  const connecting = jp.phase === 'connecting' && us.phase === 'connecting';

  function onDragEnd(groupIds: string[]) {
    return (e: DragEndEvent) => {
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

  return (
    <div className="asset-groups">
      {connecting && <div className="asset-empty asset-empty--card">connecting… 最新の戦略を取得中</div>}
      {groups.map((g) => {
        const ids = g.items.map((a) => a.id);
        return (
          <section className="asset-group" key={g.key}>
            <div className="asset-group__title">{g.title}<span className="asset-group__count">{g.items.length}</span></div>
            <div className="card asset-list">
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd(ids)}>
                <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                  {g.items.map((a) => {
                    const strat = deriveStrategy(a, maps.labels.get(a.symbol), maps.quotes.get(a.symbol), maps.cats.get(a.symbol), mountTs);
                    return (
                      <SortableAssetRow
                        key={a.id} asset={a} strat={strat} expanded={expandedId === a.id}
                        onToggleExpand={onToggleExpand} onRemove={onRemove}
                      />
                    );
                  })}
                </SortableContext>
              </DndContext>
            </div>
          </section>
        );
      })}
    </div>
  );
};

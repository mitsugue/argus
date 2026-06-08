import React, { useMemo } from 'react';
import { useJapanWatchlist } from '../../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../../hooks/useUSWatchlist';
import { useActionLabels } from '../../hooks/useActionLabels';
import { useCatalysts } from '../../hooks/useCatalysts';
import { deriveStrategy, type AssetStrategy, type QuoteLite } from '../../lib/assetStrategy';
import type { AssetItem } from '../../types/assetItem';
import type { ActionLabel } from '../../types/actionLabels';
import type { CatalystItem } from '../../types/catalysts';

interface Props {
  assets: AssetItem[];
  reorderable: boolean;
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  onMove: (id: string, dir: -1 | 1) => void;
  onRemove: (id: string) => void;
  onToggleEnabled: (id: string) => void;
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

const AssetRow: React.FC<{
  asset: AssetItem; strat: AssetStrategy; expanded: boolean; index: number; total: number;
  reorderable: boolean; onToggleExpand: (id: string) => void; onMove: (id: string, dir: -1 | 1) => void;
  onRemove: (id: string) => void;
}> = ({ asset, strat, expanded, index, total, reorderable, onToggleExpand, onMove, onRemove }) => {
  const name = asset.displayNameJa || asset.displayName;
  return (
    <div className={`asset-row${expanded ? ' asset-row--open' : ''}`}>
      <div
        className="asset-row__head"
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={() => onToggleExpand(asset.id)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggleExpand(asset.id); } }}
      >
        <span className="asset-row__caret">{expanded ? '▾' : '▸'}</span>
        <span className="asset-row__id">
          <span className="asset-row__sym">{asset.symbol}</span>
          <span className="asset-row__name">{name}</span>
        </span>
        <span className="asset-row__price">{fmtPrice(asset.market, strat.price)}</span>
        <span className={pctClass(strat.changePct)}>{fmtPct(strat.changePct)}</span>
        <span className="asset-row__action" style={{ color: ACTION_COLOR[strat.action] ?? 'var(--text-sub)' }}>{strat.action}</span>
        <span className="asset-row__meta">
          {strat.risk !== '—' && <span>risk {strat.risk}</span>}
          {strat.confidence != null && <span>· {Math.round(strat.confidence * 100)}%</span>}
        </span>
        <span className="asset-row__status" style={{ color: STATUS_COLOR[strat.status] }}>{strat.status}</span>
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
              {reorderable && (
                <>
                  <button className="asset-mini" aria-label={`Move ${asset.symbol} up`} disabled={index === 0} onClick={() => onMove(asset.id, -1)}>↑</button>
                  <button className="asset-mini" aria-label={`Move ${asset.symbol} down`} disabled={index === total - 1} onClick={() => onMove(asset.id, 1)}>↓</button>
                </>
              )}
              <button className="asset-mini asset-mini--danger" aria-label={`Remove ${asset.symbol}`} onClick={() => onRemove(asset.id)}>Remove</button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export const AssetStrategySection: React.FC<Props> = ({
  assets, reorderable, expandedId, onToggleExpand, onMove, onRemove,
}) => {
  const jp = useJapanWatchlist();
  const us = useUSWatchlist();
  const al = useActionLabels();
  const cat = useCatalysts();

  const maps = useMemo(() => {
    const quotes = new Map<string, QuoteLite>();
    for (const s of jp.data?.stocks ?? []) quotes.set(s.symbol, { price: s.price, changePct: s.changePct, volume: s.volume, date: s.date, status: s.status });
    for (const s of us.data?.stocks ?? []) quotes.set(s.symbol, { price: s.price, changePct: s.changePct, volume: s.volume, date: s.date, status: s.status });
    const labels = new Map<string, ActionLabel>();
    for (const l of al.data?.labels ?? []) labels.set(l.symbol, l);
    const cats = new Map<string, CatalystItem>();
    for (const c of cat.data?.items ?? []) cats.set(c.symbol, c);
    return { quotes, labels, cats };
  }, [jp.data, us.data, al.data, cat.data]);

  const nowTs = Date.now();
  const connecting = jp.phase === 'connecting' && us.phase === 'connecting';

  if (assets.length === 0) {
    return <div className="card asset-list"><div className="asset-empty">この絞り込みに該当する資産はありません。「+ Add Asset」で追加できます。</div></div>;
  }

  return (
    <div className="card asset-list">
      {connecting && <div className="asset-empty">connecting… 最新の戦略を取得中</div>}
      {assets.map((a, i) => {
        const strat = deriveStrategy(a, maps.labels.get(a.symbol), maps.quotes.get(a.symbol), maps.cats.get(a.symbol), nowTs);
        return (
          <AssetRow
            key={a.id} asset={a} strat={strat} index={i} total={assets.length}
            reorderable={reorderable} expanded={expandedId === a.id}
            onToggleExpand={onToggleExpand} onMove={onMove} onRemove={onRemove}
          />
        );
      })}
    </div>
  );
};

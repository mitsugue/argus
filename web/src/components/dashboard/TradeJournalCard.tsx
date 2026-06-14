import React, { useMemo, useState } from 'react';
import { readTrades, addTrade, closeTrade, removeTrade, tradePnlPct, type TradeEntry } from '../../lib/tradeJournal';
import { useJapanWatchlist } from '../../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../../hooks/useUSWatchlist';
import type { AssetItem } from '../../types/assetItem';

// My Trade Journal card (v10.23): record YOUR own trades + the rationale, see
// live P/L, and build the human side of the learning loop. Device-local;
// synced via the encrypted vault. Born from the 9984 @6450 trade.

export const TradeJournalCard: React.FC<{ assets: AssetItem[] }> = ({ assets }) => {
  const [trades, setTrades] = useState<TradeEntry[]>(() => readTrades());
  const [open, setOpen] = useState(false);
  const [sym, setSym] = useState('');
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [price, setPrice] = useState('');
  const [qty, setQty] = useState('');
  const [why, setWhy] = useState('');

  // Live prices for open JP/US trades → unrealized P/L.
  const jpSyms = useMemo(() => [...new Set(trades.filter((t) => t.market === 'JP' && t.status === 'open').map((t) => t.symbol))], [trades]);
  const usSyms = useMemo(() => [...new Set(trades.filter((t) => t.market === 'US' && t.status === 'open').map((t) => t.symbol))], [trades]);
  const jp = useJapanWatchlist(jpSyms);
  const us = useUSWatchlist(usSyms);
  const priceOf = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of jp.data?.stocks ?? []) if (s.status === 'live') m.set(s.symbol, s.price);
    for (const s of us.data?.stocks ?? []) if (s.status === 'live') m.set(s.symbol, s.price);
    return (t: TradeEntry) => m.get(t.symbol);
  }, [jp.data, us.data]);

  const refresh = () => setTrades(readTrades());

  function submit() {
    const p = parseFloat(price);
    if (!sym.trim() || !Number.isFinite(p) || p <= 0 || !why.trim()) return;
    const found = assets.find((a) => a.symbol === sym.trim().toUpperCase() || a.symbol === sym.trim());
    addTrade({
      symbol: (found?.symbol ?? sym.trim().toUpperCase()),
      name: found?.displayNameJa || found?.displayName || sym.trim(),
      market: (found?.market ?? (/^[0-9]/.test(sym.trim()) ? 'JP' : 'US')) as TradeEntry['market'],
      side, price: p, qty: qty ? parseFloat(qty) : null,
      date: new Date().toISOString().slice(0, 10), rationaleJa: why.trim(),
    });
    setSym(''); setPrice(''); setQty(''); setWhy(''); setOpen(false);
    refresh();
  }

  const openTrades = trades.filter((t) => t.status === 'open').reverse();
  const closedTrades = trades.filter((t) => t.status === 'closed').reverse().slice(0, 10);

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">My Trades</span>
        <button className="section-head__link" onClick={() => setOpen((o) => !o)}>{open ? '閉じる' : '+ 記録'}</button>
      </div>
      <div className="card tj">
        {open && (
          <div className="tj__form">
            <input className="tj__in" list="tj-syms" placeholder="銘柄コード/シンボル" value={sym} onChange={(e) => setSym(e.target.value)} />
            <datalist id="tj-syms">{assets.map((a) => <option key={a.id} value={a.symbol}>{a.displayNameJa || a.displayName}</option>)}</datalist>
            <select className="tj__in" value={side} onChange={(e) => setSide(e.target.value as 'buy' | 'sell')}>
              <option value="buy">買い</option><option value="sell">売り</option>
            </select>
            <input className="tj__in" type="number" placeholder="価格" value={price} onChange={(e) => setPrice(e.target.value)} />
            <input className="tj__in" type="number" placeholder="数量(任意)" value={qty} onChange={(e) => setQty(e.target.value)} />
            <textarea className="tj__why" placeholder="根拠(なぜ入った/出た) — あなたの判断を残す" value={why} onChange={(e) => setWhy(e.target.value)} />
            <button className="asset-btn asset-btn--primary" onClick={submit}>記録する</button>
          </div>
        )}
        {openTrades.length === 0 && closedTrades.length === 0 && !open && (
          <div className="tj__empty">自分の売買と根拠を記録すると、ここで損益と「あなたの判断 vs 結果」を追えます(端末内のみ・同期対象)。</div>
        )}
        {openTrades.map((t) => {
          const pnl = tradePnlPct(t, priceOf(t));
          return (
            <div className="tj__row" key={t.id}>
              <div className="tj__head">
                <span className="tj__sym">{t.symbol} {t.name}</span>
                <span className={`tj__side tj__side--${t.side}`}>{t.side === 'buy' ? '買' : '売'} @{t.price}{t.qty ? `×${t.qty}` : ''}</span>
                {pnl != null && <span className="tj__pnl" style={{ color: pnl >= 0 ? 'var(--green)' : 'var(--risk-high)' }}>{pnl >= 0 ? '+' : ''}{pnl}%</span>}
                <span className="tj__date">{t.date}</span>
              </div>
              <div className="tj__why-text">{t.rationaleJa}</div>
              <div className="tj__actions">
                <button className="asset-mini" onClick={() => {
                  const ex = window.prompt('決済価格を入力:');
                  const exp = ex ? parseFloat(ex) : NaN;
                  if (Number.isFinite(exp)) { closeTrade(t.id, exp, new Date().toISOString().slice(0, 10)); refresh(); }
                }}>決済</button>
                <button className="asset-mini asset-mini--danger" onClick={() => { removeTrade(t.id); refresh(); }}>削除</button>
              </div>
            </div>
          );
        })}
        {closedTrades.map((t) => {
          const pnl = tradePnlPct(t, undefined);
          return (
            <div className="tj__row tj__row--closed" key={t.id}>
              <div className="tj__head">
                <span className="tj__sym">{t.symbol} {t.name}</span>
                <span className="tj__side">{t.side === 'buy' ? '買' : '売'} @{t.price} → {t.exitPrice}</span>
                {pnl != null && <span className="tj__pnl" style={{ color: pnl >= 0 ? 'var(--green)' : 'var(--risk-high)' }}>{pnl >= 0 ? '+' : ''}{pnl}%(確定)</span>}
              </div>
              <div className="tj__why-text">{t.rationaleJa}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
};

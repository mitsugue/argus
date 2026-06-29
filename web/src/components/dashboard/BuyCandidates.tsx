import React from 'react';
import './BuyCandidates.css';

// 本日の注目候補 (v10.177) — high-bar, AI-screened buy candidates from TODAY's movers
// beyond the watchlist (catalyst/theme-driven via the C.A.O.S. association engine, not
// pure momentum). Decision-support only: never advice, never auto-trade. Honest empty
// state — most days few or zero qualify.

interface BuyCandidate {
  symbol: string; name: string; market: string; changePct?: number | null;
  thesisJa: string; entryJa?: string; riskJa?: string; conviction: number; driverJa?: string | null;
}

export const BuyCandidates: React.FC = () => {
  const [items, setItems] = React.useState<BuyCandidate[] | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) return;
    let alive = true;
    const url = backend.replace(/\/$/, '') + '/api/argus/buy-candidates';
    const load = () => fetch(url).then((r) => r.json()).then((j) => { if (alive) setItems(j.items || []); }).catch(() => {});
    load();
    const iv = setInterval(load, 5 * 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  if (items === null) return null;
  return (
    <section className="buyc">
      <div className="buyc-head">
        <span className="buyc-title">本日の注目候補</span>
        <span className="buyc-sub">watchlist外・高確信のみ・要確認(買い助言ではありません)</span>
      </div>
      {items.length === 0 ? (
        <p className="buyc-empty">本日は確信度の高い候補はありません(無理に出しません)。</p>
      ) : items.map((c) => (
        <div className="buyc-row" key={`${c.market}:${c.symbol}`}>
          <div className="buyc-l1">
            <span className="buyc-sym">{c.symbol}</span>
            <span className="buyc-name">{c.name}</span>
            {typeof c.changePct === 'number' && (
              <span className={`buyc-chg buyc-chg--${c.changePct >= 0 ? 'up' : 'dn'}`}>
                {c.changePct >= 0 ? '+' : ''}{c.changePct.toFixed(2)}%
              </span>
            )}
            <span className="buyc-conv">確信 {Math.round((c.conviction || 0) * 100)}%</span>
          </div>
          <p className="buyc-thesis">{c.thesisJa}</p>
          {c.entryJa && <div className="buyc-line"><span className="buyc-h">エントリー確認</span><span className="buyc-t">{c.entryJa}</span></div>}
          {c.riskJa && <div className="buyc-line"><span className="buyc-h buyc-h--risk">リスク</span><span className="buyc-t">{c.riskJa}</span></div>}
        </div>
      ))}
      <p className="buyc-foot">watchlist外の上昇銘柄をC.A.O.S.で選別した候補。売買助言・利益保証ではなく、最終判断はご自身で。</p>
    </section>
  );
};

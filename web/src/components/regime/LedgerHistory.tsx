import React from 'react';
import './LedgerHistory.css';

// 履歴 / 台帳 (v10.185) — read-back UI for the daily ledgers that were accumulating with no
// way to see them: rotation (with Δ vs the prior record), downside incidents, and cause
// attribution. Decision-support history; minimal colour (only inflow/outflow tones).

interface RotDelta { id: string; label: string; score: number; delta: number; status: string }
interface RotHist { status?: string; count?: number; deltaFrom?: string; noteJa?: string;
  latest?: { date?: string; regime?: string }; delta?: RotDelta[] }
interface DownInc { symbol: string; assetName?: string; actionOverride?: string }
interface DownHist { status?: string; count?: number; noteJa?: string;
  latest?: { date?: string; activeCount?: number; globalRegime?: string; incidents?: DownInc[] } }
interface Attr { symbol: string; changePct?: number; unknownShare?: number; causeProbabilities?: Record<string, number> }
interface AttrHist { status?: string; count?: number; noteJa?: string; latest?: { date?: string; attributions?: Attr[] } }

const CAUSE_JA: Record<string, string> = {
  STOCK_SPECIFIC_BAD_NEWS: '個別の悪材料', LONG_LIQUIDATION: 'ロング解消', MARKET_WIDE_SELL_OFF: '全体安',
  SECTOR_SELL_OFF: 'セクター安', UNKNOWN: '原因未確認', VALUATION_REPRICING: 'バリュエーション調整',
};
const fmtPct = (v?: number) => (typeof v === 'number' ? `${v >= 0 ? '+' : ''}${v.toFixed(1)}%` : '—');
const fmtD = (v?: number) => (typeof v === 'number' ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}` : '—');
const topCause = (p?: Record<string, number>) => {
  if (!p) return null;
  const e = Object.entries(p).sort((a, b) => b[1] - a[1])[0];
  return e ? `${CAUSE_JA[e[0]] ?? e[0]} ${Math.round(e[1] * 100)}%` : null;
};

function useJson<T>(path: string): T | null {
  const [data, setData] = React.useState<T | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) return;
    let alive = true;
    fetch(backend.replace(/\/$/, '') + path).then((r) => r.json())
      .then((j) => { if (alive) setData(j); }).catch(() => {});
    return () => { alive = false; };
  }, [path]);
  return data;
}

export const LedgerHistory: React.FC = () => {
  const [open, setOpen] = React.useState(false);
  const rot = useJson<RotHist>('/api/argus/rotation-history');
  const down = useJson<DownHist>('/api/argus/downside-history');
  const attr = useJson<AttrHist>('/api/argus/attribution-history');

  const rotDelta = (rot?.delta ?? []).slice().sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 6);
  const incidents = (down?.latest?.incidents ?? []).slice(0, 5);
  const attrs = (attr?.latest?.attributions ?? []).slice(0, 5);

  return (
    <section className="lh">
      <button className="lh-head" onClick={() => setOpen((v) => !v)}>
        <span className="lh-title">履歴 / 台帳</span>
        <span className="lh-sub">毎営業日16:05に記録 — ローテーションΔ・急落・原因</span>
        <span className="lh-toggle">{open ? '▾ 閉じる' : '▸ 開く'}</span>
      </button>
      {open && (
        <div className="lh-body">
          {/* Rotation Δ */}
          <div className="lh-block">
            <div className="lh-bh">資金ローテーション(前回比Δ)
              <span className="lh-dim">{rot?.deltaFrom ? ` ${rot.deltaFrom} → ${rot.latest?.date ?? ''}` : ''}{rot?.latest?.regime ? ` · ${rot.latest.regime}` : ''}</span>
            </div>
            {rotDelta.length > 0 ? rotDelta.map((r) => (
              <div className="lh-row" key={r.id}>
                <span className="lh-label">{r.label}</span>
                <span className="lh-score">score {fmtD(r.score)}</span>
                <span className={`lh-delta lh-delta--${r.status}`}>Δ {fmtD(r.delta)}</span>
              </div>
            )) : <p className="lh-empty">記録待ち(Δは2営業日目から)。</p>}
          </div>

          {/* Downside incidents */}
          <div className="lh-block">
            <div className="lh-bh">急落インシデント
              <span className="lh-dim">{down?.count ? ` ${down.count}日分 · 最新 ${down.latest?.date ?? ''} · ${down.latest?.activeCount ?? 0}件` : ''}</span>
            </div>
            {incidents.length > 0 ? incidents.map((i) => (
              <div className="lh-row" key={i.symbol}>
                <span className="lh-sym">{i.symbol}</span>
                <span className="lh-name">{i.assetName}</span>
                <span className="lh-ovr">{i.actionOverride}</span>
              </div>
            )) : <p className="lh-empty">直近の記録はありません。</p>}
          </div>

          {/* Cause attribution */}
          <div className="lh-block">
            <div className="lh-bh">原因アトリビューション
              <span className="lh-dim">{attr?.count ? ` ${attr.count}日分 · 最新 ${attr.latest?.date ?? ''}` : ''}</span>
            </div>
            {attrs.length > 0 ? attrs.map((a) => (
              <div className="lh-row" key={a.symbol}>
                <span className="lh-sym">{a.symbol}</span>
                <span className={`lh-chg ${(a.changePct ?? 0) >= 0 ? 'up' : 'dn'}`}>{fmtPct(a.changePct)}</span>
                <span className="lh-cause">{topCause(a.causeProbabilities) ?? '—'}</span>
              </div>
            )) : <p className="lh-empty">直近の記録はありません。</p>}
          </div>

          <p className="lh-foot">{rot?.noteJa || '毎営業日に台帳へ追記。後日、結果と照合して自己採点に使われます。決定支援のみ。'}</p>
        </div>
      )}
    </section>
  );
};

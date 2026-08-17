import React, { useMemo, useState } from 'react';
import type { AssetItem } from '../../types/assetItem';
import type { ActionLabel } from '../../types/actionLabels';
import type { CatalystItem } from '../../types/catalysts';
import { deriveStrategy, bestAssetName, type QuoteLite } from '../../lib/assetStrategy';
import { fmtMoney, fmtSigned, currencyOf, type ExposureSummary } from '../../lib/portfolio';
import { simulateAdd } from '../../lib/whatif';
import { getNumericTone, TONE_VAR } from '../../lib/numericTone';

// V12.2.12 — What-ifシミュレーター(旧AssetStrategySection内から移設・計算不変)。
// 置き場所: Positions & Risk(ポートフォリオ横断機能)。
// What-if simulator (v10.1): "¥X を銘柄Y に追加したら配分とシナリオ別損益は
// どう動くか" — SCENARIO ANALYSIS over assumed bands, never a forecast.
// Client-side only; uses the same live quotes + rule scenarios as the cards.

export const WhatIfPanel: React.FC<{
  assets: AssetItem[];
  quotes: Map<string, QuoteLite>;
  labels: Map<string, ActionLabel>;
  cats: Map<string, CatalystItem>;
  exp: ExposureSummary;
  usdJpy: number | null;
  mountTs: number;
}> = ({ assets, quotes, labels, cats, exp, usdJpy, mountTs }) => {
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState('');
  const [amt, setAmt] = useState('');

  const candidates = useMemo(
    () => assets.filter((a) => {
      const q = quotes.get(a.symbol);
      return q && q.status === 'live';
    }),
    [assets, quotes],
  );
  const selAsset = candidates.find((a) => a.symbol === sel) ?? null;
  const ccy = selAsset ? currencyOf(selAsset.market) : 'JPY';

  const result = useMemo(() => {
    const amount = Number(amt);
    if (!selAsset || !(amount > 0)) return null;
    const q = quotes.get(selAsset.symbol)!;
    const strat = deriveStrategy(selAsset, labels.get(selAsset.symbol), q, cats.get(selAsset.symbol), mountTs);
    return simulateAdd({
      symbol: selAsset.symbol, currency: currencyOf(selAsset.market),
      price: q.price, amount, scenarios: strat.scenarios,
      exposure: exp, usdJpy,
    });
  }, [selAsset, amt, quotes, labels, cats, exp, usdJpy, mountTs]);

  if (candidates.length === 0) return null;
  return (
    <div className="card whatif">
      <button className="whatif__toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="whatif__caret">{open ? '▾' : '▸'}</span>
        What-if シミュレーション
        <span className="whatif__sub">追加投資の配分・シナリオ別損益(予測ではなくシナリオ整理)</span>
      </button>
      {open && (
        <div className="whatif__body">
          <div className="whatif__form">
            <label>銘柄
              <select value={sel} onChange={(e) => setSel(e.target.value)}>
                <option value="">選択…</option>
                {candidates.map((a) => (
                  <option key={a.id} value={a.symbol}>
                    {a.symbol} {bestAssetName(a, quotes.get(a.symbol)?.name)}
                  </option>
                ))}
              </select>
            </label>
            <label>追加投資額({ccy === 'JPY' ? '¥' : '$'})
              <input type="number" inputMode="decimal" min="0" step="any" value={amt}
                     placeholder={ccy === 'JPY' ? '300000' : '2000'}
                     onChange={(e) => setAmt(e.target.value)} />
            </label>
          </div>
          {result && (
            <div className="whatif__result">
              <p className="whatif__line">
                追加: <b>{result.addQuantity.toFixed(result.addQuantity >= 10 ? 0 : 4)}</b> 単位 @ {fmtMoney(result.currency, result.price)}
                （投資額 {fmtMoney(result.currency, result.amount)}）
              </p>
              {result.assetShareAfterPct != null && (
                <p className="whatif__line">
                  配分: {sel} が {result.assetShareBeforePct?.toFixed(1) ?? '0.0'}% → <b>{result.assetShareAfterPct.toFixed(1)}%</b>
                  {result.portfolioAfterJpy != null && <>（追加後ポートフォリオ ≈ {fmtMoney('JPY', result.portfolioAfterJpy)}）</>}
                </p>
              )}
              {result.warnings.map((w, i) => (
                <p className="whatif__warn" key={i}>⚠ {w}</p>
              ))}
              <div className="whatif__bands">
                <span className="whatif__bands-head">シナリオ別損益帯(1〜3営業日・仮定幅)</span>
                {result.bands.map((b) => (
                  <div className="whatif__band" key={b.label}>
                    <span className="whatif__band-label">{b.labelJa}</span>
                    <span className="whatif__band-prob">{b.probability}%</span>
                    <span className="whatif__band-range">
                      {fmtSigned(result.currency, b.plLow)} 〜 {fmtSigned(result.currency, b.plHigh)}
                    </span>
                  </div>
                ))}
                <p className="whatif__expected">
                  確率加重の中央値(参考): <b style={{ color: TONE_VAR[getNumericTone(result.expectedMid)] }}>
                    {fmtSigned(result.currency, result.expectedMid)}
                  </b>
                </p>
              </div>
              <p className="whatif__disc">
                仮定幅(下値継続 −10〜−4% / 横ばい ±2% / 反発 +3〜+8%)にルールエンジンのシナリオ確率を掛けた整理です。
                予測・推奨ではありません。
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

import React, { useState } from 'react';
import type { DeskCardData } from './types';
import { buildAssetPositionView } from '../../domain/assetDeskInternal';
import { currencyOf, fmtMoney, fmtSigned } from '../../lib/portfolio';
import { readAssetRiskLine, saveAssetRiskLine } from '../../lib/assetRiskLine';
import { getNumericTone, TONE_VAR } from '../../lib/numericTone';

// V12.2.12 — OWNER POSITION(§7-3)。旧TodayのPOSITION/EXPOSURE+旧Watchlistの
// Holding入力を統合。数量/取得単価はlocalStorageのみ(公開APIへ送らない・不変)。

const pct = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;

export const AssetPositionPanel: React.FC<{
  d: DeskCardData;
  onUpdateHolding: (id: string, h: { quantity?: number | null; avgCost?: number | null }) => void;
}> = ({ d, onUpdateHolding }) => {
  const [riskLine, setRiskLine] = useState<number | null>(
    () => readAssetRiskLine(d.asset.symbol),
  );
  const livePrice = (d.strat.status === 'live' || d.strat.status === 'partial') ? d.strat.price : undefined;
  const currency = currencyOf(d.asset.market);
  const num = (v: string) => (v.trim() === '' ? null : Number(v));
  const view = buildAssetPositionView({
    held: d.decisionFirst.held,
    quantity: d.asset.quantity,
    averageCost: d.asset.avgCost,
    currentPrice: livePrice,
    portfolioConcentrationPct: d.pn?.weightPct,
    theme: d.pn?.themeJa,
    themeConcentrationPct: d.themeConcentrationPct,
    eventLabels: d.eventTags.map((event) => `${event.code} ${event.countdown}`),
    volume: d.strat.volume,
    ownerRiskLine: riskLine,
    support: null,
    trimReviewCondition: d.ppl?.trimReviewConditionsJa[0] ?? null,
  });
  return (
    <div className="ad-position-view" data-position-kind="computed">
      <div className="ad-position-grid">
        {view.quantity != null && <div><span>QUANTITY</span><b>{view.quantity.toLocaleString()}</b></div>}
        {view.averageCost != null && <div><span>AVERAGE COST</span><b>{fmtMoney(currency, view.averageCost)}</b></div>}
        {view.currentValue != null && <div><span>CURRENT VALUE</span><b>{fmtMoney(currency, view.currentValue)}</b></div>}
        {view.unrealizedPl != null && <div><span>UNREALIZED P/L</span>
          <b style={{ color: view.unrealizedPl == null ? undefined : TONE_VAR[getNumericTone(view.unrealizedPl)] }}>
            {`${fmtSigned(currency, view.unrealizedPl)} · ${pct(view.unrealizedPlPct!)}`}
          </b>
        </div>}
        {view.portfolioConcentrationPct != null && <div><span>PORTFOLIO CONCENTRATION</span>
          <b>{view.portfolioConcentrationPct.toFixed(1)}%</b>
        </div>}
        {view.themeConcentrationPct != null && <div><span>THEME CONCENTRATION</span>
          <b>{view.theme ?? 'Theme'} {view.themeConcentrationPct.toFixed(1)}%</b>
        </div>}
        {view.breakEvenDistancePct != null && <div><span>BREAK-EVEN DISTANCE</span>
          <b>{pct(view.breakEvenDistancePct)}</b>
        </div>}
        <div><span>EVENT EXPOSURE</span><b>{view.eventExposure
          ?? (d.eventsAuthorityUnknown ? '判定不能(イベント未取得)' : '直近紐付けなし')}</b></div>
        {view.volume != null && <div><span>VOLUME</span><b>{view.volume.toLocaleString()}</b></div>}
      </div>

      {/* Holdings (v10.0) — device-local; Positions & RiskのExposureを駆動 */}
      <div className="asset-hold">
        <span className="asset-detail__k">Holding（端末内のみ）</span>
        <div className="asset-hold__body">
          <label className="asset-hold__field">数量
            <input type="number" inputMode="decimal" min="0" step="any"
              defaultValue={d.asset.quantity ?? ''}
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => onUpdateHolding(d.asset.id, { quantity: num(e.currentTarget.value) })} />
          </label>
          <label className="asset-hold__field">平均取得単価
            <input type="number" inputMode="decimal" min="0" step="any"
              defaultValue={d.asset.avgCost ?? ''}
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => onUpdateHolding(d.asset.id, { avgCost: num(e.currentTarget.value) })} />
          </label>
        </div>
      </div>

      <div className="ad-risk-line">
        <label htmlFor={`risk-line-${d.asset.id}`}>OWNER-DEFINED RISK LINE</label>
        <input id={`risk-line-${d.asset.id}`} type="number" min="0" step="any"
          inputMode="decimal" value={riskLine ?? ''}
          placeholder="価格を入力"
          onChange={(event) => {
            const value = num(event.currentTarget.value);
            setRiskLine(value);
            saveAssetRiskLine(d.asset.symbol, value);
          }} />
        <span>{view.ownerRiskLineDistancePct == null
          ? '端末内のみ・未設定'
          : `現在値から ${pct(view.ownerRiskLineDistancePct)}`}</span>
      </div>

      {view.trimReviewCondition && (
        <p className="ad-position-condition">
          <b>TRIM REVIEW CONDITION</b><span>{view.trimReviewCondition}</span>
        </p>
      )}
      <p className="ad-position-unavailable">
        <b>未算出</b><span>{view.unavailable.join(' / ')}</span>
      </p>
    </div>
  );
};

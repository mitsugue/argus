import React from 'react';
import type { DeskCardData } from './types';
import { READINESS_TONE } from '../../domain/positionExposure';
import { valueHolding, fmtMoney, fmtSigned } from '../../lib/portfolio';
import { getNumericTone, TONE_VAR } from '../../lib/numericTone';

// V12.2.12 — OWNER POSITION(§7-3)。旧TodayのPOSITION/EXPOSURE+旧Watchlistの
// Holding入力を統合。数量/取得単価はlocalStorageのみ(公開APIへ送らない・不変)。

const HP_COLOR: Record<string, string> = { red: '#F87171', amber: '#FBBF24', green: '#34D399', neutral: 'var(--text-sub)' };

export const AssetPositionPanel: React.FC<{
  d: DeskCardData;
  onUpdateHolding: (id: string, h: { quantity?: number | null; avgCost?: number | null }) => void;
}> = ({ d, onUpdateHolding }) => {
  const pn = d.pn;
  const hp = d.hp;
  const livePrice = (d.strat.status === 'live' || d.strat.status === 'partial') ? d.strat.price : undefined;
  const hv = valueHolding(d.asset, livePrice);
  const num = (v: string) => (v.trim() === '' ? null : Number(v));
  return (
    <>
      {pn && (
        <p className="uac-next" style={{ marginBottom: 2 }}>
          {pn.held ? (
            <>
              保有中{pn.quantity != null ? ` ${pn.quantity.toLocaleString()}株/口` : ''}
              {pn.avgCost != null ? ` · 取得 ${pn.avgCost.toLocaleString()}` : ''}
              {pn.pnlPct != null && (
                <b style={{ marginLeft: 4, color: pn.pnlPct >= 0 ? 'var(--value-positive)' : 'var(--value-negative)' }}>
                  {pn.pnlPct >= 0 ? '+' : ''}{pn.pnlPct.toFixed(1)}%
                </b>
              )}
              {pn.weightPct != null && ` · 全体の${pn.weightPct.toFixed(0)}%`}
              {` · ${pn.themeJa}`}
            </>
          ) : (
            <>監視のみ(保有なし) · {pn.themeJa}</>
          )}
        </p>
      )}
      {pn && (
        <p className="uac-next" style={{ marginBottom: 4 }}>
          <b style={{ color: READINESS_TONE[pn.readiness] }}>{pn.readinessJa}</b>
          <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>{pn.whyJa}</span>
        </p>
      )}
      {hp && (
        <div className="asset-detail__holder" style={{ borderColor: HP_COLOR[hp.tone] }}>
          <span className="asset-detail__holder-label" style={{ color: HP_COLOR[hp.tone] }}>保有者向け: {hp.labelJa}</span>
          {hp.plPct != null && (
            <span className="asset-detail__holder-pl" style={{ color: hp.plPct >= 0 ? '#34D399' : '#F87171' }}>
              {hp.plPct >= 0 ? '+' : '−'}{Math.abs(hp.plPct).toFixed(1)}%
            </span>
          )}
          <p className="asset-detail__holder-reason">{hp.reasonJa}</p>
        </div>
      )}
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
          {hv && (
            <span className="asset-hold__val">
              評価 <b>{fmtMoney(hv.currency, hv.value)}</b>
              {' ／ 損益 '}
              <b style={{ color: TONE_VAR[getNumericTone(hv.pl)] }}>
                {fmtSigned(hv.currency, hv.pl)}（{hv.plPct >= 0 ? '+' : ''}{hv.plPct.toFixed(1)}%）
              </b>
            </span>
          )}
        </div>
      </div>
    </>
  );
};

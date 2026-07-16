import React from 'react';
import type { DeskCardData } from './types';
import { AiExplanationBlock } from '../dashboard/AiExplanationBlock';
import { CauseStackCard } from '../dashboard/CauseStackCard';

// V12.2.12 — WHY / DOWNSIDE(§7-4)。旧WatchlistのWHY DOWN?ブロック+旧Todayの
// TIMELINE/CAUSE/原因スタック/即時調査を統合。表示のみ(判定は既存エンジン)。

const TONE: Record<string, string> = { up: 'var(--value-positive)', down: 'var(--value-negative)', flow: 'var(--event-medium)', news: 'var(--text-sub)', flat: 'var(--text-sub)' };

export const AssetWhyPanel: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const c = d.card;
  const incident = d.incident;
  return (
    <>
      {incident && (
        <div className="asset-detail__downside">
          <div className="asset-detail__downside-head">
            WHY DOWN? <span className="asset-detail__downside-pct">{typeof incident.changePct === 'number' ? `${incident.changePct.toFixed(1)}%` : ''}</span>
            <span className="asset-detail__downside-ovr"
              style={{ color: ['EXIT_WATCH', 'TRIM_WATCH'].includes(incident.actionOverride) ? '#F87171' : '#FBBF24' }}>
              Rule: {incident.currentAction} → Override: {incident.actionOverride}
            </span>
          </div>
          <div className="asset-detail__downside-causes">
            {incident.causeBuckets.slice(0, 3).map((b) => (
              <span key={b.cause} className="asset-detail__downside-cause">
                {b.cause} {Math.round(b.probability * 100)}%
              </span>
            ))}
          </div>
          <p className="asset-detail__downside-line">{incident.reasonJa}</p>
          <p className="asset-detail__downside-line"><b>やってはいけない:</b> {incident.doNotDoJa}</p>
          <p className="asset-detail__downside-line"><b>確認条件:</b> {incident.nextConditionJa}</p>
          {incident.missingData.length > 0 && (
            <p className="asset-detail__downside-line asset-detail__downside-missing">
              <b>欠損データ:</b> {incident.missingData.join(' / ')}
            </p>
          )}
        </div>
      )}
      {c?.causeOneLineJa && <p className="uac-cause" style={{ display: 'block' }}>{c.causeOneLineJa}</p>}
      {/* v12.0.6: 「理由を詳しく調べる」即時調査(公開POSTはenqueueのみ) */}
      <div className="uac-sec">
        <div className="uac-sec-t">今の動きを調べる</div>
        <AiExplanationBlock symbol={d.asset.symbol} market={d.asset.market} context="asset-card" dense labelJa="この原因を再確認(公式・ニュース・検索を再走査)" />
      </div>
      {/* 生データ(値動きタイムライン/原因スライス/原因スタック)は折りたたみ */}
      <details className="uac-sec uac-deep">
        <summary style={{ cursor: 'pointer', fontSize: 10.5, color: 'var(--text-faint)' }}>詳細データ(値動き・原因分析)を見る</summary>
        {c && c.timeline.length > 0 && (
          <div className="uac-sec">
            <div className="uac-sec-t">TIMELINE</div>
            <ul className="uac-tl">
              {c.timeline.map((t, i) => (
                <li key={i}><span className="uac-tl-time">{t.time}</span><span style={{ color: TONE[t.tone] }}>{t.textJa}</span></li>
              ))}
            </ul>
          </div>
        )}
        {c && c.causeSlices.length > 0 && (
          <div className="uac-sec">
            <div className="uac-sec-t">CAUSE</div>
            <div className="uac-cz">
              {c.causeSlices.map((sl) => (
                <div className="uac-cz-row" key={sl.labelJa}>
                  <span className="uac-cz-l">{sl.labelJa}</span>
                  <span className="uac-cz-bar"><i style={{ width: `${sl.pct}%` }} /></span>
                  <span className="uac-cz-p">{sl.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <CauseStackCard symbol={d.asset.symbol} market={d.asset.market} hideInvestigateButton />
      </details>
    </>
  );
};

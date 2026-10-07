import React from 'react';
import type { DeskCardData } from './types';
import { AiExplanationBlock } from '../dashboard/AiExplanationBlock';
import { probabilityDisplay } from '../../domain/decisionView';

// V12.2.12 — WHY / DOWNSIDE(§7-4)。旧Watchlistの値動きの原因候補ブロック+旧Todayの
// 値動きの経緯/原因の内訳/原因スタック/即時調査を統合。表示のみ(判定は既存エンジン)。

const TONE: Record<string, string> = { up: 'var(--value-positive)', down: 'var(--value-negative)', flow: 'var(--event-medium)', news: 'var(--text-sub)', flat: 'var(--text-sub)' };

export const AssetWhyPanel: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const c = d.card;
  const incident = d.incident;
  return (
    <>
      {incident && (
        <div className="asset-detail__downside">
          <div className="asset-detail__downside-head">
            値動きの原因候補 <span className="asset-detail__downside-pct">{typeof incident.changePct === 'number' ? `${incident.changePct.toFixed(1)}%` : ''}</span>
          </div>
          <div className="asset-detail__downside-causes">
            {incident.causeBuckets.slice(0, 3).map((b) => (
              <span key={b.cause} className="asset-detail__downside-cause">
                {b.cause} {probabilityDisplay(b.probability * 100).qualitative}
              </span>
            ))}
          </div>
        </div>
      )}
      {/* v12.0.6: 「理由を詳しく調べる」即時調査(公開POSTはenqueueのみ) */}
      <div className="uac-sec">
        <div className="uac-sec-t">今の動きを調べる</div>
        <AiExplanationBlock symbol={d.asset.symbol} market={d.asset.market} context="asset-card" dense labelJa="保存された原因調査を見る" />
      </div>
      {/* 生データ(値動きタイムライン/原因スライス/原因スタック)は折りたたみ */}
      <details className="uac-sec uac-deep">
        <summary style={{ cursor: 'pointer', fontSize: 10.5, color: 'var(--text-faint)' }}>保存した経緯・分析の内訳</summary>
        {c && c.timeline.length > 0 && (
          <div className="uac-sec">
            <div className="uac-sec-t">値動きの経緯</div>
            <ul className="uac-tl">
              {c.timeline.map((t, i) => (
                <li key={i}><span className="uac-tl-time">{t.time}</span><span style={{ color: TONE[t.tone] }}>{t.textJa}</span></li>
              ))}
            </ul>
          </div>
        )}
        {c && c.causeSlices.length > 0 && (
          <div className="uac-sec">
            <div className="uac-sec-t">原因の内訳</div>
            <div className="uac-cz">
              {c.causeSlices.map((sl) => (
                <div className="uac-cz-row" key={sl.labelJa}>
                  <span className="uac-cz-l">{sl.labelJa}</span>
                  <span className="uac-cz-p">{probabilityDisplay(sl.pct).qualitative}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </details>
    </>
  );
};

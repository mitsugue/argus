import React from 'react';
import type { DeskCardData } from './types';
import { RANK_TONE } from '../../hooks/useSupplyDemand';
import { InstitutionalView } from '../dashboard/InstitutionalView';
import { ExpandableReason } from '../common/CollapsibleSection';

// V12.2.12 — FLOW & SUPPLY(§7-5)。旧TodayのSUPPLY/DEMAND+機関ビューと
// 旧WatchlistのBig-money flow行を統合。逆日歩は常に「未取得」正直表示(不変)。

export const AssetFlowPanel: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const sdg = d.sdg;
  const flow = d.strat.bigFlowRatio;
  const ev = sdg?.evidence ?? {};
  const balanceChange = ev.marginBalanceChange as { buyPct?: number | null; sellPct?: number | null } | null;
  const detailRows = sdg ? [
    ev.marginBuyingBalance != null ? `信用買い残 ${Number(ev.marginBuyingBalance).toLocaleString()}` : null,
    ev.marginSellingBalance != null ? `信用売り残 ${Number(ev.marginSellingBalance).toLocaleString()}` : null,
    ev.lendingBorrowingRatio != null ? `信用・貸借倍率 ${Number(ev.lendingBorrowingRatio).toFixed(2)}` : null,
    balanceChange?.buyPct != null || balanceChange?.sellPct != null
      ? `前週差 買${balanceChange?.buyPct == null ? '未取得' : `${balanceChange.buyPct > 0 ? '+' : ''}${balanceChange.buyPct.toFixed(1)}%`} / 売${balanceChange?.sellPct == null ? '未取得' : `${balanceChange.sellPct > 0 ? '+' : ''}${balanceChange.sellPct.toFixed(1)}%`}` : null,
    sdg.levelJa ? `買い残の重さ ${sdg.levelJa}` : null,
    d.strat.volume != null && d.strat.volume > 0 ? `出来高 ${d.strat.volume.toLocaleString()}` : null,
    typeof ev.volumeTrend === 'string' ? ev.volumeTrend : null,
    typeof ev.closeLocation === 'number' ? `終値位置 ${(ev.closeLocation * 100).toFixed(0)}%` : null,
    ev.daysToCover != null ? `買い戻し ${String(ev.daysToCover)}日分` : null,
  ].filter((row): row is string => !!row) : [];
  return (
    <>
      {sdg ? (
        <div style={{ marginBottom: 4 }}>
          <p className="uac-next" style={{ marginBottom: 2 }}>
            <b style={{ color: RANK_TONE[sdg.supplyDemandRank] }}>需給ランク {sdg.supplyDemandRank}</b>
            <span style={{ marginLeft: 6 }}>{sdg.conditionJa}</span>
            <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
              {sdg.directnessJa} · 確度{Math.round(sdg.confidence * 100)}%
            </span>
          </p>
          <ExpandableReason className="uac-next" style={{ marginBottom: 2, color: 'var(--text-sub)' }} text={sdg.ownerReadableWhyJa} />
          <details>
            <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>詳細データを見る</summary>
            {detailRows.length > 0 && <p style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
              {detailRows.join(' / ')}
            </p>}
            <p style={{ margin: '2px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
              逆日歩 未取得。需給Turning Pointと過去の価格反応は下のCHART INTELLIGENCE、判断履歴の結果はRESEARCH &amp; NOTESで確認できます。
            </p>
          </details>
        </div>
      ) : (
        <p className="uac-next" style={{ margin: '0 0 4px', color: 'var(--text-faint)' }}>
          需給ランク未取得(この銘柄/資産クラスのデータ不在は「良い需給」を意味しません)。
        </p>
      )}
      {flow != null && (
        <p className="uac-next" style={{ marginBottom: 4 }}>
          <span className="asset-detail__k" style={{ marginRight: 6 }}>Big-money flow</span>
          <span style={{ color: flow >= 0.2 ? 'var(--green)' : flow <= -0.2 ? 'var(--red)' : 'var(--text-sub)' }}>
            大口純流入率 {(flow * 100).toFixed(1)}%（本日累計・moomoo）
          </span>
        </p>
      )}
      {/* Named institutional views (public metadata) — 見解であり取引ポジションではない */}
      <InstitutionalView symbol={d.asset.symbol} />
    </>
  );
};

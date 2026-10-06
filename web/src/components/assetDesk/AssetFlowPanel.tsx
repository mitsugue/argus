import React from 'react';
import type { DeskCardData } from './types';
import { outlookDay } from '../../domain/assetOutlook';
import { InstitutionalView } from '../dashboard/InstitutionalView';
import { ExpandableReason } from '../common/CollapsibleSection';

// V12.2.12 — FLOW & SUPPLY(§7-5)。旧TodayのSUPPLY/DEMAND+機関ビューと
// 旧Watchlistの大口取引の集計行を統合。逆日歩は常に「未取得」正直表示(不変)。

export const AssetFlowPanel: React.FC<{ d: DeskCardData }> = ({ d }) => {
  const isUS = d.asset.market === 'US';
  const sdg = isUS && d.sdg?.market !== 'US' ? undefined : d.sdg;
  const flow = d.strat.bigFlowRatio;
  const ev = sdg?.evidence ?? {};
  const balanceChange = ev.marginBalanceChange as { buyPct?: number | null; sellPct?: number | null } | null;
  const confidenceJa = sdg
    ? sdg.confidence >= 0.7 ? 'データの確かさ 高' : sdg.confidence >= 0.4 ? 'データの確かさ 中' : 'データの確かさ 低'
    : '';
  const detailRows = sdg ? [
    ...(!isUS ? [
    ev.marginBuyingBalance != null ? `信用買い残 ${Number(ev.marginBuyingBalance).toLocaleString()}` : null,
    ev.marginSellingBalance != null ? `信用売り残 ${Number(ev.marginSellingBalance).toLocaleString()}` : null,
    sdg.ratios?.margin != null ? `信用倍率 ${sdg.ratios.margin.toFixed(2)}倍` : null,
    sdg.ratios?.jsf != null ? `日証金の貸借倍率 ${sdg.ratios.jsf.toFixed(2)}倍` : null,
    !sdg.ratios && ev.lendingBorrowingRatio != null ? `倍率（旧保存値・参照元未確認） ${Number(ev.lendingBorrowingRatio).toFixed(2)}` : null,
    balanceChange?.buyPct != null || balanceChange?.sellPct != null
      ? `前週差 買${balanceChange?.buyPct == null ? '未取得' : `${balanceChange.buyPct > 0 ? '+' : ''}${balanceChange.buyPct.toFixed(1)}%`} / 売${balanceChange?.sellPct == null ? '未取得' : `${balanceChange.sellPct > 0 ? '+' : ''}${balanceChange.sellPct.toFixed(1)}%`}` : null,
    ] : []),
    d.strat.volume != null && d.strat.volume > 0 ? `出来高 ${d.strat.volume.toLocaleString()}` : null,
    typeof ev.volumeTrend === 'string' ? ev.volumeTrend : null,
    typeof ev.closeLocation === 'number' ? `終値位置 ${(ev.closeLocation * 100).toFixed(0)}%` : null,
    ev.daysToCover != null ? `買い戻し ${String(ev.daysToCover)}日分` : null,
  ].filter((row): row is string => !!row) : [];
  return (
    <>
      {sdg ? (
        <div style={{ marginBottom: 4 }}>
          <ExpandableReason className="uac-next" text={sdg.ownerReadableWhyJa} />
          <p className="ad-detail-note">{sdg.directnessJa} · {confidenceJa}</p>
          <ul className="ad-flow-facts">{detailRows.map((row, i) => <li key={i}>{row}</li>)}</ul>
          <p className="ad-detail-note">
            {!isUS && sdg.sourceDates?.weeklyMargin && `信用残 ${outlookDay(sdg.sourceDates.weeklyMargin)}週`}
            {!isUS && sdg.sourceDates?.jsfDaily && ` · 日証金 ${outlookDay(sdg.sourceDates.jsfDaily)}`}
          </p>
          <p className="ad-detail-note">
            {d.asset.market === 'US'
              ? '米国株は実測大口フローによる簡易評価です。日本の信用残・日証金の残高とは別の指標です。'
              : '信用残は公表された残高、日証金は証券会社の調達分です。現在の注文量ではありません。逆日歩 未取得（取得経路なし）。'}
          </p>
        </div>
      ) : (
        <p className="uac-next" style={{ margin: '0 0 4px', color: 'var(--text-faint)' }}>
          {d.asset.market === 'US' ? '実測フローは未取得です。価格や出来高だけで資金流入・流出とは判定しません。'
            : '需給の根拠は未取得です。データがないことを「需給が良い」とは評価しません。'}
        </p>
      )}
      {flow != null && (
        <p className="uac-next" style={{ marginBottom: 4 }}>
          <span className="asset-detail__k" style={{ marginRight: 6 }}>大口取引の集計</span>
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

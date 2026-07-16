import React from 'react';
import './Today.css';

// V12.2.12 — RESEARCH & SIGNALS内の「銘柄の例外サマリー」。
// Todayの銘柄カード全リスト(旧AssetCategorySection×3)の置き換え: 個別銘柄の
// 正本はAsset Deskに一本化し、Todayは「例外(保有×撤退/防衛・P0/P1・急落・
// AIとルールの不一致)だけ」を要約して当該カードへ飛ばす。判断・件数は
// useAssetIntel(Asset Deskと同一の正本)から供給 — この層は選択と表示のみ。

export interface AssetExceptionRow {
  symbol: string;
  nameJa: string;
  /** 何の例外か(保有×撤退判断 / P0 / 急落対応 / AI・ルール不一致 …) */
  tagJa: string;
  actionEn: string;
  sourceTagEn: string;    // AI PRIMARY / RULE TEMPORARY / RULE
  reasonJa: string;
}

export const TodayAssetExceptions: React.FC<{
  rows: AssetExceptionRow[];
  totalCount: number;
  countsJa: string;                 // "JP 8 · US 4 · 投信 3 · 暗号 2"
  aiStateJa: string | null;         // ページ単位のAI状態(RULE TEMPORARY理由)
  onOpenAsset: (symbol: string) => void;
  onOpenDesk: () => void;
}> = ({ rows, totalCount, countsJa, aiStateJa, onOpenAsset, onOpenDesk }) => (
  <div className="card" aria-label="Asset exceptions">
    <div className="uac-sec-t" style={{ marginBottom: 4 }}>ASSETS — 例外サマリー</div>
    <p style={{ margin: '0 0 6px', fontSize: 11, color: 'var(--text-sub)' }}>
      登録{totalCount}銘柄({countsJa})。個別銘柄の判断と根拠は<b>Asset Desk</b>に一本化しました。
      ここでは要確認の例外だけを表示します。
    </p>
    {aiStateJa && <p style={{ margin: '0 0 6px', fontSize: 10.5, color: 'var(--text-faint)' }}>{aiStateJa}</p>}
    {rows.length === 0 ? (
      <p style={{ margin: 0, fontSize: 11.5, color: 'var(--text-sub)' }}>
        例外はありません(保有×撤退/防衛・P0/P1・急落対応・AIとルールの不一致に該当なし)。
      </p>
    ) : (
      rows.map((r) => (
        <div className="tex-sum__row" key={r.symbol}>
          <button type="button" className="tex-sum__sym" title="Asset Deskでこの銘柄を開く"
                  onClick={() => onOpenAsset(r.symbol)}>{r.symbol} {r.nameJa} ↗</button>
          <span className="tex-sum__tag">{r.tagJa}</span>
          <span style={{ fontSize: 10.5, fontWeight: 700 }}>{r.actionEn}</span>
          <span className="tex-sum__src">{r.sourceTagEn}</span>
          {r.reasonJa && <p className="tex-sum__reason">{r.reasonJa}</p>}
        </div>
      ))
    )}
    <p className="tex-sum__foot">
      <button type="button" className="texp__cta" onClick={onOpenDesk}>Asset Deskで全銘柄を見る</button>
    </p>
  </div>
);

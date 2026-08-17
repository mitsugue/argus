import React from 'react';
import type { SupplyDemandSignal } from '../../hooks/useSupplyDemand';
import { RANK_TONE } from '../../hooks/useSupplyDemand';

// V11.10.0 — SUPPLY / DEMAND on Today (JP). オーナーの質問は「数値」ではなく
// 「需給は良いのか悪いのか」— だからランク+状態+日本語のなぜ、が主役で、
// 生数値(信用残・貸借倍率・回転日数)は「詳細データを見る」の中にだけ出す。
// 状態評価であり売買指示ではない。

const fmtNum = (v: unknown): string =>
  typeof v === 'number' ? (v >= 10000 ? `${Math.round(v / 1000).toLocaleString()}千` : String(v)) : '—';

export const SupplyDemandSection: React.FC<{ signals: SupplyDemandSignal[] }> = ({ signals }) => {
  if (signals.length === 0) return null;
  const shown = signals.slice(0, 5);
  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">SUPPLY / DEMAND</span>
        <span className="section-head__count">日本株の需給ランク · 売買指示なし</span>
      </div>
      {shown.map((s) => (
        <div key={s.id + s.symbol}
             style={{ borderLeft: `2px solid ${RANK_TONE[s.supplyDemandRank] || 'var(--line)'}`,
                      paddingLeft: 8, margin: '6px 0' }}>
          <p style={{ margin: 0, fontSize: 12.5 }}>
            <b>{s.symbol}</b>
            {s.name && s.name !== s.symbol && <span style={{ marginLeft: 4, color: 'var(--text-sub)' }}>{s.name}</span>}
            <b style={{ marginLeft: 8, color: RANK_TONE[s.supplyDemandRank] }}>
              需給ランク {s.supplyDemandRank}
            </b>
            {s.chips.map((c) => (
              <span key={c} style={{ marginLeft: 6, fontSize: 9.5, color: 'var(--text-faint)',
                                     border: '1px solid var(--line)', borderRadius: 999, padding: '0 6px' }}>
                {c}
              </span>
            ))}
            <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
              {s.directnessJa} · 確度{Math.round(s.confidence * 100)}%
            </span>
          </p>
          {(s.levelJa || s.direction) && (
            <p style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
              方向: {s.direction === 'improving' ? '改善' : s.direction === 'worsening' ? '悪化' : s.direction === 'stable' ? '安定' : s.direction === 'mixed' ? '混在' : '不明'}
              {s.levelJa && <> / 買い残水準: {s.levelJa}</>}
              {s.rankCapReason && <span style={{ marginLeft: 5 }}>({s.rankCapReason})</span>}
            </p>
          )}
          <p style={{ margin: '2px 0 0', fontSize: 11.5, color: 'var(--text-sub)', lineHeight: 1.6 }}>
            {s.ownerReadableWhyJa}
          </p>
          <p style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
            次に確認: {s.checkNextJa}
          </p>
          {s.missingEvidence.length > 0 && s.confidence < 0.6 && (
            <p style={{ margin: '1px 0 0', fontSize: 10, color: 'var(--text-faint)' }}>
              未取得: {s.missingEvidence.slice(0, 3).join(' / ')}
            </p>
          )}
          {/* 生数値は主役にしない — 折りたたみの中だけ */}
          <details style={{ marginTop: 2 }}>
            <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>詳細データを見る</summary>
            <p style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)', lineHeight: 1.7 }}>
              信用買い残 {fmtNum(s.evidence.marginBuyingBalance)} / 売り残 {fmtNum(s.evidence.marginSellingBalance)}
              {s.evidence.lendingBorrowingRatio != null && <> / 貸借倍率 {String(s.evidence.lendingBorrowingRatio)}</>}
              {s.evidence.daysToCover != null && <> / 買い戻し{String(s.evidence.daysToCover)}日分</>}
              {' / 逆日歩 未取得'}
              {s.dataDate && <> / データ日付 {s.dataDate}</>}
            </p>
            <p style={{ margin: '1px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>{s.sourceLimitNote}</p>
          </details>
        </div>
      ))}
      <p style={{ margin: '4px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
        ランクの意味: S/A=上値の玉が軽い ・ B=やや良い/踏み上げ含み ・ C=中立 ・ D=重い(戻り売り注意) ・
        E=悪い(追いかけ買い回避) ・ 保留=データ不足。公表データ(週次信用残・日次貸借残)ベースで
        リアルタイムではありません。売買指示ではありません。
      </p>
    </section>
  );
};

export default SupplyDemandSection;

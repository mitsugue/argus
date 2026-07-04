import React from 'react';
import type { APItem } from '../../domain/actionPriority';
import { briefJa, RANK_TONE } from '../../domain/actionPriority';
import { jpDisplay } from '../../lib/displayName';

// V11.12.0 — ACTION PRIORITY on Today (top area). アプリを開いた瞬間に
// 「今日はこれを見る」が分かるための注意配分リスト。売買指示ではない。
// P0=保有×複合悪材料のみ(静かな日はP0ゼロが正しい)。

export const ActionPrioritySection: React.FC<{ items: APItem[] }> = ({ items }) => {
  const [showAll, setShowAll] = React.useState(false);
  const visible = items.filter((i) => i.priorityRank !== 'Ignore');
  const shown = showAll ? visible : visible.slice(0, 5);
  const ignored = items.length - visible.length;

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">ACTION PRIORITY</span>
        <span className="section-head__count">今日これを見る · 売買指示なし</span>
      </div>
      <p style={{ margin: '2px 0 4px', fontSize: 12.5, color: 'var(--text-sub)' }}>
        {briefJa(items)}
        {ignored > 0 && <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>(重要度低 {ignored}件は非表示)</span>}
      </p>
      {shown.map((it) => (
        <div key={it.symbol + it.category}
             style={{ borderLeft: `2px solid ${RANK_TONE[it.priorityRank]}`,
                      paddingLeft: 8, margin: '6px 0' }}>
          <p style={{ margin: 0, fontSize: 12.5 }}>
            <b style={{ color: RANK_TONE[it.priorityRank], border: `1px solid ${RANK_TONE[it.priorityRank]}`,
                        borderRadius: 4, padding: '0 5px', fontSize: 10.5 }}>
              {it.priorityRank}
            </b>
            <b style={{ marginLeft: 6 }}>{jpDisplay(it.symbol, it.assetName)}</b>
            {it.isHeld && <span style={{ marginLeft: 4, fontSize: 9.5, color: 'var(--amber, #fbbf24)',
                                         border: '1px solid var(--line)', borderRadius: 999, padding: '0 5px' }}>保有</span>}
            <span style={{ marginLeft: 6, color: RANK_TONE[it.priorityRank], fontWeight: 600 }}>
              {it.actionLabelJa}
            </span>
            <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
              確度{Math.round(it.confidence * 100)}%
            </span>
          </p>
          <p style={{ margin: '2px 0 0', fontSize: 11.5, color: 'var(--text-sub)', lineHeight: 1.6 }}>
            {it.whyJa}
          </p>
          <p style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
            次に確認: {it.checkNextJa}
          </p>
          <details style={{ marginTop: 1 }}>
            <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>何が変われば判断が変わるか</summary>
            <p style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>{it.whatWouldChangeJa}</p>
          </details>
        </div>
      ))}
      {visible.length > 5 && (
        <button type="button" onClick={() => setShowAll(!showAll)}
                style={{ fontSize: 11, cursor: 'pointer', background: 'transparent',
                         color: 'var(--accent)', border: '1px solid var(--line)',
                         borderRadius: 6, padding: '2px 10px' }}>
          {showAll ? '閉じる' : `他${visible.length - 5}件を表示`}
        </button>
      )}
      <p style={{ margin: '4px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
        P0=最優先(保有×複合悪材料のみ) / P1=今日の優先 / P2=重要(急がない)。
        全レイヤー(イベント・レジーム・機関・フロー・需給・保有・判断品質)の統合であり、売買指示ではありません。
      </p>
    </section>
  );
};

export default ActionPrioritySection;

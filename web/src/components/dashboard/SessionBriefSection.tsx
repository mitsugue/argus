import React from 'react';
import type { LocalBrief } from '../../domain/sessionBrief';
import { MODE_TONE } from '../../domain/sessionBrief';

// V11.13.0 — SESSION BRIEF on Today (top, above ACTION PRIORITY).
// 「今日の作戦」: Brief=作戦 / Action Priority=見る順番 / Alerts=個別注意。
// 売買指示ではない。休場中はレビュー体裁(ザラ場風の文を出さない)。

export const SessionBriefSection: React.FC<{ brief: LocalBrief }> = ({ brief: b }) => {
  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">SESSION BRIEF</span>
        <span className="section-head__count">今日の作戦 · 売買指示なし</span>
      </div>
      <div className="card" style={{ padding: '10px 12px' }}>
        <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6 }}>
          <b style={{ color: MODE_TONE[b.ownerMode], border: `1px solid ${MODE_TONE[b.ownerMode]}`,
                      borderRadius: 999, padding: '0 8px', fontSize: 11 }}>
            {b.ownerModeJa}
          </b>
          <span style={{ marginLeft: 6, fontSize: 10.5, color: 'var(--text-faint)' }}>{b.marketStatusJa}</span>
        </p>
        <p style={{ margin: '6px 0 0', fontSize: 13.5, fontWeight: 600, lineHeight: 1.6 }}>
          {b.headlineJa}
        </p>
        <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
          {b.bullets.map((x, i) => (
            <li key={i} style={{ fontSize: 12, color: 'var(--text-sub)', lineHeight: 1.7 }}>{x}</li>
          ))}
        </ul>
        <p style={{ margin: '6px 0 0', fontSize: 11.5 }}>
          <b style={{ color: 'var(--value-negative)' }}>やらないこと:</b>
          <span style={{ marginLeft: 4, color: 'var(--text-sub)' }}>{b.whatNotToDoJa.join(' / ')}</span>
        </p>
        <p style={{ margin: '2px 0 0', fontSize: 11.5 }}>
          <b style={{ color: 'var(--accent)' }}>次の確認:</b>
          <span style={{ marginLeft: 4, color: 'var(--text-sub)' }}>{b.nextChecksJa.join(' / ')}</span>
        </p>
        {b.afterCloseReviewJa.length > 0 && (
          <details style={{ marginTop: 4 }}>
            <summary style={{ cursor: 'pointer', fontSize: 10.5, color: 'var(--text-faint)' }}>引け後にやること</summary>
            <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>
              {b.afterCloseReviewJa.map((x, i) => (
                <li key={i} style={{ fontSize: 11, color: 'var(--text-faint)' }}>{x}</li>
              ))}
            </ul>
          </details>
        )}
        <p style={{ margin: '6px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
          Brief=今日の作戦 / ACTION PRIORITY=見る順番 / 各カード=個別の詳細。全レイヤーの要約であり売買指示ではありません。
        </p>
      </div>
    </section>
  );
};

export default SessionBriefSection;

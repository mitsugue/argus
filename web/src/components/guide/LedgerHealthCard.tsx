import React from 'react';
import { useLedgerHealth, type LedgerRow } from '../../hooks/useLedgerHealth';
import './LedgerHealthCard.css';

const STATUS_JA: Record<string, string> = {
  healthy: '稼働中', stale: '遅延', empty: '蓄積前', unknown: '不明',
};
const STATUS_COLOR: Record<string, string> = {
  healthy: 'var(--green, #34d399)', stale: 'var(--amber, #fbbf24)',
  empty: 'var(--text-muted, #5f6b78)', unknown: 'var(--text-muted, #5f6b78)',
};

function ageJa(row: LedgerRow): string {
  if (row.lastSuccessAt && row.ageMin != null) {
    const m = row.ageMin;
    return m < 60 ? `${m}分前` : m < 1440 ? `${Math.round(m / 60)}時間前` : `${Math.round(m / 1440)}日前`;
  }
  if (row.lastUpdated) {
    const sw = row.staleWeekdays;
    if (sw == null) return row.lastUpdated;
    return sw <= 0 ? `${row.lastUpdated}（直近営業日）` : `${row.lastUpdated}（${sw}営業日前）`;
  }
  return '—';
}

export const LedgerHealthCard: React.FC = () => {
  const { data, error } = useLedgerHealth();
  return (
    <div className="card lh-card">
      <div className="lh-card__head">
        <span className="lh-card__title">📒 Ledger Health — 自己採点ループの稼働状況</span>
      </div>
      {error && !data && <div className="lh-card__note">取得できませんでした({error.slice(0, 40)})。</div>}
      {!data && !error && <div className="lh-card__note">読み込み中…</div>}
      {data && (
        <div className="lh-rows">
          {data.ledgers.map((row) => (
            <div className="lh-row" key={row.id}>
              <div className="lh-row__top">
                <span className="lh-row__dot" style={{ background: STATUS_COLOR[row.status] }} />
                <span className="lh-row__label">{row.labelJa}</span>
                <span className="lh-row__status" style={{ color: STATUS_COLOR[row.status] }}>
                  {STATUS_JA[row.status] ?? row.status}
                </span>
              </div>
              <div className="lh-row__meta">
                <span>最終: <b>{ageJa(row)}</b></span>
                {row.sampleCount != null && (
                  <span>· {row.sampleCount}件{row.tradingDays != null ? ` / ${row.tradingDays}営業日` : ''}</span>
                )}
                {row.hitRate != null && <span>· 的中 <b>{Math.round(row.hitRate * 100)}%</b></span>}
                {row.models?.primary && <span>· {row.models.primary}+{row.models.checker}</span>}
              </div>
              <div className="lh-row__sub">
                次回 {row.nextRunJa} · トリガー {row.trigger}
              </div>
              <div className="lh-row__note">{row.noteJa}</div>
            </div>
          ))}
          <div className="lh-card__foot">
            稼働中＝直近営業日に記録あり / 遅延＝2営業日以上更新なし / 蓄積前＝まだ記録なし。
            {data.asOf ? ` 更新 ${data.asOf.slice(11, 16)} UTC` : ''}
          </div>
        </div>
      )}
    </div>
  );
};

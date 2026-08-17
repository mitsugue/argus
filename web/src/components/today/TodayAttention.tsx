import React from 'react';
import type { RouteKey } from '../NavRail';
import './Today.css';

// V12.2.11 — ATTENTION: 非critical警告の集約領域。
// 構造上の最大行数=4(通知1行に集約+バックアップ+戦略+FIRE)なので
// 「ほかN件」は発生しない — 項目が無言で消えることはない。
// 通知行は展開で全文へ到達でき、他の行は対応ページへ遷移できる。

export interface AttentionNotification {
  id: string; severity: string; toneVar: string; titleJa: string; bodyJa: string;
}

interface Props {
  notifications: AttentionNotification[];   // critical/high・new のみ(呼び出し側)
  backupUnprotected: boolean;
  strategyNote: { tone: string; textJa: string } | null;
  fireNote: { tone: string; textJa: string } | null;
  onNavigate: (key: RouteKey) => void;
}

export const TodayAttention: React.FC<Props> = ({
  notifications, backupUnprotected, strategyNote, fireNote, onNavigate,
}) => {
  const [notifOpen, setNotifOpen] = React.useState(false);
  const rows = (notifications.length ? 1 : 0) + (backupUnprotected ? 1 : 0)
    + (strategyNote ? 1 : 0) + (fireNote ? 1 : 0);
  if (!rows) return null;
  const notifTone = notifications.some((n) => n.severity === 'critical')
    ? 'var(--value-negative)' : 'var(--amber, #fbbf24)';
  return (
    <div className="tg-span-12 tcard tattn" role="status" aria-label="Attention">
      <div className="tcard__head">
        <span className="tcard__title">Attention</span>
        <span className="tcard__meta">{rows}件</span>
      </div>

      {notifications.length > 0 && (
        <>
          <button type="button" className="tattn__row tattn__row--btn"
            style={{ borderLeftColor: notifTone }}
            aria-expanded={notifOpen} aria-controls="tattn-notifs"
            onClick={() => setNotifOpen((v) => !v)}>
            <b style={{ color: notifTone }}>[通知]</b> 重要通知 · {notifications.length}件
            <span className="tattn__hint">{notifOpen ? '閉じる' : '内容を見る'}</span>
          </button>
          {notifOpen && (
            <div id="tattn-notifs" className="tattn__expand">
              {notifications.map((n) => (
                <p key={n.id} className="tattn__row" style={{ borderLeftColor: n.toneVar }}>
                  <b style={{ color: n.toneVar }}>{n.titleJa}</b> — {n.bodyJa}
                </p>
              ))}
            </div>
          )}
        </>
      )}

      {backupUnprotected && (
        <button type="button" className="tattn__row tattn__row--btn"
          style={{ borderLeftColor: 'var(--value-negative)' }}
          onClick={() => onNavigate('backup')}>
          <b style={{ color: 'var(--value-negative)' }}>[バックアップ]</b>
          {' '}未保護 — 保有データはこの端末内のみ。暗号化バックアップを有効化してください。
          <span className="tattn__hint">Backupへ</span>
        </button>
      )}
      {strategyNote && (
        <button type="button" className="tattn__row tattn__row--btn"
          style={{ borderLeftColor: strategyNote.tone }}
          onClick={() => onNavigate('core')}>
          <b style={{ color: strategyNote.tone }}>[戦略]</b> {strategyNote.textJa}
          <span className="tattn__hint">Positions &amp; Riskへ</span>
        </button>
      )}
      {fireNote && (
        <button type="button" className="tattn__row tattn__row--btn"
          style={{ borderLeftColor: fireNote.tone }}
          onClick={() => onNavigate('core')}>
          <b style={{ color: fireNote.tone }}>[FIRE]</b> {fireNote.textJa}
          <span className="tattn__hint">Positions &amp; Riskへ</span>
        </button>
      )}
    </div>
  );
};

import React from 'react';
import {
  compactNotificationFeed, dismissNotification, listNotifications, markAllSeen, SEV_JA, SEV_TONE,
  type CompactNotification,
} from '../lib/notifications';
import './NotificationPanel.css';

// Lean v13 — a first-class page projection of the device-local notification
// store. Detection/storage stay unchanged; this component performs no polling.

const jstFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

function jstStamp(value: string | number | Date) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return { day: '', time: '—' };
  const parts = Object.fromEntries(jstFormatter.formatToParts(date)
    .map((part) => [part.type, part.value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}` };
}

export const NotificationPanel: React.FC = () => {
  const [, bump] = React.useReducer((x: number) => x + 1, 0);
  const items = compactNotificationFeed(listNotifications());
  React.useEffect(() => { markAllSeen(); }, []);
  const today = jstStamp(new Date()).day;
  const current = items.filter((i) => jstStamp(i.createdAt).day === today
    && !['news_intel', 'market_shock'].includes(i.eventType));
  const currentIds = new Set(current.map((i) => i.id));
  const history = items.filter((i) => !currentIds.has(i.id));
  const renderItems = (list: CompactNotification[]) => list.map((n) => (
    <article key={n.id} style={{ borderTop: '1px solid var(--line)', padding: '14px 0' }}>
      <p style={{ margin: '0 0 6px', display: 'flex', gap: 10, fontSize: 12 }}>
        <span style={{ color: SEV_TONE[n.severity] }}>{SEV_JA[n.severity]}</span>
        <time dateTime={n.createdAt} style={{ color: 'var(--text-sub)' }}>
          {jstStamp(n.createdAt).day} {jstStamp(n.createdAt).time}
          {n.occurrenceCount > 1 ? ` · ${n.occurrenceCount}回の更新` : ''}
        </time>
      </p>
      <h3 style={{ margin: 0, fontSize: 14, lineHeight: 1.6 }}>{n.titleJa}</h3>
      {n.bodyJa && !n.titleJa.includes(n.bodyJa) && <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--text-sub)', lineHeight: 1.7 }}>{n.bodyJa}</p>}
      <p style={{ margin: '6px 0', fontSize: 12, lineHeight: 1.6, color: 'var(--text-sub)' }}>次に確認: {n.checkNextJa}</p>
      <button type="button"
        onClick={() => { n.notificationIds.forEach(dismissNotification); bump(); }}
        style={{ minHeight: 44, cursor: 'pointer', background: 'transparent', fontSize: 12,
          color: 'var(--text-sub)', border: '1px solid var(--line)', borderRadius: 6, padding: '8px 12px' }}>閉じる</button>
      {n.isPrivate && <span style={{ marginLeft: 10, fontSize: 12, color: 'var(--text-sub)' }}>端末内のみ</span>}
    </article>
  ));
  return (
    <section id="asset-alerts" className="notification-center card" aria-label="通知">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontSize: 17, margin: '0 0 12px' }}>銘柄・判断の変化</h2>
      </div>
      {items.length === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)', margin: '8px 0' }}>
          新しい重要通知はありません。結論または重要条件が変わった時だけお知らせします。
        </p>
      )}
      {current.length > 0 ? renderItems(current) : items.length > 0 && <p style={{ fontSize: 13, color: 'var(--text-sub)' }}>今日の銘柄・判断の新しい通知はありません。</p>}
      {history.length > 0 && <details>
        <summary style={{ minHeight: 44, padding: '12px 0', fontSize: 13, cursor: 'pointer' }}>通知履歴を見る · {history.length}件</summary>
        <p style={{ fontSize: 12, color: 'var(--text-sub)', lineHeight: 1.7 }}>ニュースの通知記録と、以前の銘柄・判断の変化です。ニュースと現在の説明は上の一覧で確認できます。当時の通知を現在の判断として扱わないでください。</p>
        {renderItems(history)}
      </details>}
      <p style={{ margin: '12px 0 0', fontSize: 12, lineHeight: 1.7, color: 'var(--text-sub)' }}>
        ここは、この端末に保存した通知の記録です。アプリを閉じた時の通知はSettingsの外部通知から設定できます。この履歴だけでは外部通知の受信を確認できません。
      </p>
    </section>
  );
};

export default NotificationPanel;

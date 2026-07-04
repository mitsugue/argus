import React from 'react';
import {
  dismissNotification, listNotifications, markAllSeen, SEV_JA, SEV_TONE,
  type AppNotification,
} from '../lib/notifications';

// V11.14.0 — 通知センター(ベルのドロップダウン)。端末内保存・売買指示なし。

export const NotificationPanel: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [, bump] = React.useReducer((x: number) => x + 1, 0);
  const items = listNotifications();
  React.useEffect(() => { markAllSeen(); }, []);
  const today = new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);
  const groups: [string, AppNotification[]][] = [
    ['今日', items.filter((i) => i.createdAt.slice(0, 10) === today)],
    ['それ以前', items.filter((i) => i.createdAt.slice(0, 10) !== today)],
  ];
  return (
    <div role="dialog" aria-label="通知"
         style={{ position: 'absolute', top: 44, right: 8, zIndex: 60, width: 340,
                  maxHeight: '70vh', overflowY: 'auto', background: 'var(--bg-card, #0d1117)',
                  border: '1px solid var(--line)', borderRadius: 10, padding: 10,
                  boxShadow: '0 8px 30px rgba(0,0,0,.45)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <b style={{ fontSize: 13 }}>通知</b>
        <button type="button" onClick={onClose}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-faint)',
                         cursor: 'pointer', fontSize: 14 }}>✕</button>
      </div>
      {items.length === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)', margin: '8px 0' }}>
          新しい通知はありません。変化があった時だけ、静かにお知らせします。
        </p>
      )}
      {groups.map(([label, list]) => list.length > 0 && (
        <div key={label}>
          <p style={{ margin: '8px 0 2px', fontSize: 10, color: 'var(--text-faint)' }}>{label}</p>
          {list.map((n) => (
            <div key={n.id} style={{ borderTop: '1px solid var(--line)', padding: '6px 0' }}>
              <p style={{ margin: 0, fontSize: 12 }}>
                <b style={{ color: SEV_TONE[n.severity], border: `1px solid ${SEV_TONE[n.severity]}`,
                            borderRadius: 4, padding: '0 4px', fontSize: 9.5 }}>{SEV_JA[n.severity]}</b>
                <b style={{ marginLeft: 6 }}>{n.titleJa}</b>
                <span style={{ marginLeft: 6, fontSize: 9.5, color: 'var(--text-faint)' }}>
                  {n.createdAt.slice(11, 16)}
                </span>
              </p>
              <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-sub)', lineHeight: 1.6 }}>{n.bodyJa}</p>
              <p style={{ margin: '1px 0 0', fontSize: 10, color: 'var(--text-faint)' }}>次に確認: {n.checkNextJa}</p>
              <button type="button"
                      onClick={() => { dismissNotification(n.id); bump(); }}
                      style={{ marginTop: 2, fontSize: 9.5, cursor: 'pointer', background: 'transparent',
                               color: 'var(--text-faint)', border: '1px solid var(--line)',
                               borderRadius: 5, padding: '0 6px' }}>閉じる</button>
              {n.isPrivate && <span style={{ marginLeft: 6, fontSize: 9, color: 'var(--text-faint)' }}>端末内のみ</span>}
            </div>
          ))}
        </div>
      ))}
      <p style={{ margin: '8px 0 0', fontSize: 9, color: 'var(--text-faint)' }}>
        通知タイプの有用性は学習中です(閉じた回数もノイズ指標として記録)。通知は端末内で生成・保存(サーバー送信なし)。外部push/メールは未設定のため無効。注意喚起であり売買指示ではありません。
      </p>
    </div>
  );
};

export default NotificationPanel;

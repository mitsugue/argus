import React, { useEffect, useState, useSyncExternalStore } from 'react';
import { OWNER_AUTH_REQUIRED, subscribeOwner, hasOwnerSession, logoutOwner,
  revokeOwnerDevices, useOwnerPasskey } from '../../lib/ownerSession';
import './OwnerIdentityPanel.css';

/**
 * 本人確認 (owner identity) card at the top of Settings.
 *
 * Owner request 2026-09-28 after the iPhone acceptance: the passkey /
 * logout / recovery controls belong at the top of Settings, not only in
 * the header disclosure. The header `本人設定` disclosure stays because the
 * automated owner-mode acceptance uses it as the authenticated marker;
 * this card offers the same actions through the same session library and
 * performs no network call of its own.
 */
export const OwnerIdentityPanel: React.FC = () => {
  const authenticated = useSyncExternalStore(subscribeOwner, hasOwnerSession);
  const [online, setOnline] = useState(navigator.onLine);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [recovery, setRecovery] = useState(false);
  const [password, setPassword] = useState('');
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener('online', update); window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  const run = async (fn: () => Promise<unknown>, success = '') => {
    setBusy(true); setMessage('');
    try { await fn(); setMessage(success); setRecovery(false); }
    catch (error) { setMessage(error instanceof Error && error.message === 'try_later'
      ? 'しばらく待ってから、もう一度お試しください。'
      : '操作を完了できませんでした。接続と認証情報を確認してください。'); }
    finally { setBusy(false); setPassword(''); }
  };
  return (
    <section id="settings-identity" className="card owner-identity" aria-label="Owner identity">
      <div className="section-head">
        <span className="section-head__title">IDENTITY · 本人確認</span>
        <span className="owner-identity__state" data-state={!OWNER_AUTH_REQUIRED ? 'off' : authenticated ? 'on' : 'locked'}>
          {!OWNER_AUTH_REQUIRED ? '無効' : authenticated ? (online ? '認証中' : '認証中・オフライン') : '未確認'}
        </span>
      </div>
      {!OWNER_AUTH_REQUIRED && (
        <p className="cmd-alloc__note">この配信では本人確認は無効です。有効化はサーバーと配信の設定で行います。</p>
      )}
      {OWNER_AUTH_REQUIRED && (
        <>
          <p className="cmd-alloc__note">
            Face ID / Touch ID のパスキーはこの端末に保存され、サーバーには公開鍵だけが残ります。
            復旧用パスワードはパスキーが使えないときの入口です。
          </p>
          <div className="owner-identity__actions">
            <button type="button" disabled={busy || !online}
              onClick={() => void run(() => useOwnerPasskey(true), 'この端末のパスキーを登録しました。')}>
              パスキーを登録
            </button>
            <button type="button" disabled={busy || !online}
              onClick={() => void run(logoutOwner)}>
              ログアウト
            </button>
            <button type="button" disabled={busy || !online} aria-expanded={recovery}
              onClick={() => { setRecovery(!recovery); setPassword(''); setMessage(''); }}>
              端末紛失・復旧
            </button>
          </div>
          {recovery && (
            <form className="owner-identity__recovery" onSubmit={(e) => {
              e.preventDefault();
              void run(() => revokeOwnerDevices(password), '登録端末を解除しました。パスワードで入り直してください。');
            }}>
              <p className="cmd-alloc__note">すべてのパスキーとログインを解除します。保存データは残ります。</p>
              <label>復旧用パスワード
                <input type="password" autoComplete="current-password" maxLength={1024} required
                  value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <button type="submit" disabled={busy || !online}>すべての端末を解除</button>
            </form>
          )}
          <p role="status" className="owner-identity__status">{busy ? '確認しています…' : message}</p>
        </>
      )}
    </section>
  );
};

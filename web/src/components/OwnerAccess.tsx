import React, { useState, useEffect, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { OWNER_AUTH_REQUIRED, subscribeOwner, hasOwnerSession, passwordLogin,
  logoutOwner, revokeOwnerDevices, useOwnerPasskey } from '../lib/ownerSession';
import './OwnerAccess.css';

export function OwnerAccess({ children }: { children: React.ReactNode }) {
  const authenticated = useSyncExternalStore(subscribeOwner, hasOwnerSession);
  useEffect(() => {
    // Executing React bundle truth, independent of the served HTML marker.
    document.documentElement.dataset.argusOwnerAuthMode = OWNER_AUTH_REQUIRED ? '1' : '0';
  }, []);
  const [online, setOnline] = useState(navigator.onLine);
  const [header, setHeader] = useState<Element | null>(null);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener('online', update); window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  useEffect(() => { setHeader(authenticated ? document.querySelector('.shell__header') : null); }, [authenticated]);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [recovery, setRecovery] = useState(false);
  if (!OWNER_AUTH_REQUIRED) return <>{children}</>;
  const run = async (fn: () => Promise<unknown>, success = '') => {
    setBusy(true); setMessage('');
    try { await fn(); setMessage(success); setRecovery(false); }
    catch (error) { setMessage(error instanceof Error && error.message === 'try_later'
      ? 'しばらく待ってから、もう一度お試しください。'
      : '操作を完了できませんでした。接続と認証情報を確認してください。'); }
    finally { setBusy(false); setPassword(''); }
  };
  const form = <form onSubmit={(e) => { e.preventDefault(); void run(() => recovery
    ? revokeOwnerDevices(password) : passwordLogin(password), recovery ? '登録端末を解除しました。パスワードで入り直してください。' : ''); }}>
    <label>復旧用パスワード<input type="password" autoComplete="current-password" maxLength={1024}
      required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
    {recovery && <p>すべてのパスキーとログインを解除します。保存データは残ります。</p>}
    <button type="submit" disabled={busy || !online}>{recovery ? 'すべての端末を解除' : 'パスワードで開く'}</button>
  </form>;
  const status = <p role="status">{busy ? '確認しています…' : message}</p>;
  const controls = <details className={`owner-access-bar${header ? '' : ' owner-access-bar--standalone'}`}>
    <summary>本人設定</summary>
    <section aria-label="本人確認" className="owner-access-panel">
      <button disabled={busy || !online} onClick={() => void run(() => useOwnerPasskey(true), 'この端末のパスキーを登録しました。')}>パスキーを登録</button>
      <button disabled={busy || !online} onClick={() => { setRecovery(!recovery); setPassword(''); }}>端末紛失・復旧</button>
      <button disabled={busy || !online} onClick={() => void run(logoutOwner)}>ログアウト</button>
      {recovery && form}{status}
    </section>
  </details>;
  return <>
    {!authenticated && <section className="owner-access-screen" aria-label="本人確認">
      <h1>ARGUS</h1><p>内容を見るには本人確認が必要です。</p>
      {!online && <p>オフラインです。保存データは残っています。接続後に本人確認をしてください。</p>}
      <button disabled={busy || !online} onClick={() => void run(() => useOwnerPasskey(false))}>パスキーで開く</button>
      {form}{status}
    </section>}
    {authenticated && <>{children}{header ? createPortal(controls, header) : controls}</>}
  </>;
}

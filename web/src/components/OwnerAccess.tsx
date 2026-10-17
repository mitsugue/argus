import { ArgusMark } from './ArgusMark';
import React, { useState, useEffect, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { OWNER_AUTH_REQUIRED, subscribeOwner, hasOwnerSession, passwordLogin,
  logoutOwner, revokeOwnerDevices, useOwnerPasskey, restoreOwnerSession, hasSavedOwnerSession,
  ownerLockReason, ownerLoginFailure } from '../lib/ownerSession';
import './OwnerAccess.css';

/** The lock reason in owner wording, with the fixed code for a screenshot. */
export function lockNote(code: string): string {
  if (!code) return '';
  const head = code.split(':')[0];
  const words: Record<string, string> = {
    expired: 'ログインの有効期限(24時間)が切れました',
    response_401: 'サーバーがログインを認めませんでした',
    session_check_401: '定期確認でサーバーがログインを認めませんでした',
    response_unverified: '応答の確認に失敗しました',
    restore_browser_tab: 'ブラウザのタブではログインを保存しません(ホーム画面のアプリで開くと保たれます)',
    restore_nothing_saved: 'この画面に保存されたログインが見つかりませんでした',
    restore_expired: '保存されたログインの期限が切れていました',
    restore_server_rejected: 'サーバーが保存されたログインを認めませんでした',
    restore_server_unreachable: 'サーバーに1分つながらず、ログインを確かめられませんでした',
    cleared: 'ログアウトしました',
  };
  return `前回: ${words[head] ?? 'ログインが続きませんでした'}(${code})`;
}

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
  // A retained app session verifies its existing login before offering a new ceremony.
  const [restoring, setRestoring] = useState(OWNER_AUTH_REQUIRED);
  // Slow or unavailable verification does not discard a saved session or
  // turn connection recovery into another Face ID request.
  const [quiet, setQuiet] = useState(() => OWNER_AUTH_REQUIRED && hasSavedOwnerSession());
  useEffect(() => {
    let live = true;
    void restoreOwnerSession().finally(() => {
      if (live) { setRestoring(false); setQuiet(hasSavedOwnerSession()); }
    });
    return () => { live = false; };
  }, []);
  if (!OWNER_AUTH_REQUIRED) return <>{children}</>;
  const [code, setCode] = useState('');
  const run = async (fn: () => Promise<unknown>, success = '') => {
    setBusy(true); setMessage(''); setCode('');
    try { await fn(); setMessage(success); setRecovery(false); }
    catch (error) {
      const failure = ownerLoginFailure(error);
      setCode(failure.code);
      setMessage(failure.message);
    }
    finally { setBusy(false); setPassword(''); }
  };
  const retrySavedSession = async () => {
    setRestoring(true);
    try { await restoreOwnerSession(); }
    finally { setRestoring(false); setQuiet(hasSavedOwnerSession()); }
  };
  const keptLogin = quiet && hasSavedOwnerSession();
  const form = <form onSubmit={(e) => { e.preventDefault(); void run(() => recovery
    ? revokeOwnerDevices(password) : passwordLogin(password), recovery ? '登録端末を解除しました。パスワードで入り直してください。' : ''); }}>
    <label>復旧用パスワード<input type="password" autoComplete="current-password" maxLength={1024}
      required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
    {recovery && <p>すべてのパスキーとログインを解除します。保存データは残ります。</p>}
    <button type="submit" disabled={busy || !online}>{recovery ? 'すべての端末を解除' : 'パスワードで開く'}</button>
  </form>;
  const status = <p role="status" data-owner-code={busy ? 'busy' : code || undefined}>{busy ? '確認しています…' : message}</p>;
  // Signed-in mark (owner request 2026-09-28): a compact English badge in the
  // header instead of a text menu. The <summary> stays the authenticated
  // marker the owner-mode acceptance readers wait for and open.
  const controls = <details className={`owner-access-bar${header ? '' : ' owner-access-bar--standalone'}`}>
    <summary aria-label="Owner session" title={online ? 'Signed in · owner session' : 'Signed in · offline'}>
      <span className="owner-mark" data-online={online ? '1' : '0'}>
        <svg className="owner-mark__shield" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M8 1.5 3 3.4v3.9c0 3 2.1 5.6 5 6.7 2.9-1.1 5-3.7 5-6.7V3.4L8 1.5Z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
          <path d="m5.6 8 1.7 1.7 3.2-3.4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="owner-mark__text">VERIFIED</span>
        <span className="owner-mark__dot" aria-hidden="true" />
      </span>
    </summary>
    <section aria-label="本人確認" className="owner-access-panel">
      <button disabled={busy || !online} onClick={() => void run(() => useOwnerPasskey(true), 'この端末のパスキーを登録しました。')}>パスキーを登録</button>
      <button disabled={busy || !online} onClick={() => { setRecovery(!recovery); setPassword(''); }}>端末紛失・復旧</button>
      <button disabled={busy || !online} onClick={() => void run(logoutOwner)}>ログアウト</button>
      {recovery && form}{status}
    </section>
  </details>;
  return <>
    {!authenticated && <section className="owner-access-screen" aria-label="本人確認">
      {/* Owner request 2026-09-30: the sign-in screen opens on the brand itself —
          the eye-in-triangle mark and the A.R.G.U.S. Pro wordmark, quiet and precise. */}
      <div className="owner-access-brand" aria-hidden="false">
        <div className="owner-access-brand__halo" aria-hidden="true" />
        <ArgusMark size={72} className="owner-access-brand__mark" />
        <h1 className="owner-access-brand__name">A.R.G.U.S.</h1>
        <p className="owner-access-brand__tag">Autonomous Risk and Global Uncertainty Scanner</p>
        <span className="owner-access-brand__pro" aria-label="Pro">Pro</span>
        <span className="owner-access-brand__rule" aria-hidden="true" />
      </div>
      {/* A kept session only needs its existing verification. New credentials
          appear after expiry, rejection, logout or a launch with no saved login. */}
      <p className="owner-access-screen__lead">{restoring ? '前回のログインを確認しています…' : keptLogin ? '保存されたログインの確認に接続できませんでした。ログインを保ったまま再確認できます。' : '内容を見るには本人確認が必要です。'}</p>
      {!online && <p>オフラインです。保存データは残っています。接続後に本人確認をしてください。</p>}
      {keptLogin && !restoring && <button disabled={busy || !online}
        onClick={() => void run(retrySavedSession)}>接続を再確認</button>}
      {!keptLogin && <>
        <button disabled={busy || !online} onClick={() => void run(() => useOwnerPasskey(false))}>パスキーで開く</button>
        {form}{status}</>}
      {/* Owner request 2026-10-02: the running version, small and centred. */}
      <p className="owner-access-screen__version" data-argus-version={__APP_VERSION__}>v{__APP_VERSION__}</p>
      {/* 2026-10-04: why the previous login did not continue, small, so a
          screenshot names the cause (fixed code, never a credential). */}
      {!restoring && lockNote(ownerLockReason()) && <p className="owner-access-screen__version"
        data-owner-lock-reason={ownerLockReason()}>{lockNote(ownerLockReason())}</p>}
    </section>}
    {authenticated && <>{children}{header ? createPortal(controls, header) : controls}</>}
  </>;
}

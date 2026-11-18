import React, { useEffect, useState } from 'react';
import { checkThisDevicePush } from '../../lib/webPushHealth';

// 2026-11-18: one line, only when this device's notification registration is
// known to have expired. Checked when ARGUS opens and when it returns to the
// front (at most every 30 minutes).
const RECHECK_MS = 30 * 60 * 1000;

export const PushRegistrationNotice: React.FC = () => {
  const [lost, setLost] = useState(false);
  useEffect(() => {
    let alive = true; let last = 0;
    const check = () => {
      if (Date.now() - last < RECHECK_MS) return;
      last = Date.now();
      void checkThisDevicePush().then(state => {
        if (alive && state !== 'unknown') setLost(state === 'lost');
      }).catch(() => undefined);
    };
    check();
    const onVisible = () => { if (document.visibilityState === 'visible') check(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { alive = false; document.removeEventListener('visibilitychange', onVisible); };
  }, []);
  if (!lost) return null;
  return <section className="card push-lost-notice" role="status" aria-label="通知の登録切れ">
    <p>この端末の通知の登録が切れています。<a href="#settings">Settings</a> の「アプリを閉じたときの通知」で「通知を有効にする」を押してください。</p>
  </section>;
};

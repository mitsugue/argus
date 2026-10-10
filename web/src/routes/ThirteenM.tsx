import React, { useEffect, useRef, useState } from 'react';
import { THIRTEEN_M_NAVIGATION, type RouteKey } from '../navigation';
import './ThirteenM.css';

export function ThirteenM({ onBack, onNavigateToAsset, onNavigate }: {
  onBack: () => void;
  onNavigateToAsset: (symbol: string) => void;
  onNavigate: (route: RouteKey) => void;
}) {
  // Local preview uses only the offline loopback service, never owner data.
  const frameOrigin = window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8130' : THIRTEEN_M_NAVIGATION.origin;
  const embeddedUrl = frameOrigin + '/embedded/';
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      // Navigation only. No credential, owner record or API body crosses this boundary.
      if (event.origin !== frameOrigin
        || event.source !== frame.current?.contentWindow) return;
      const value = event.data;
      if (!value || typeof value !== 'object') return;
      if (value.type === 'argus-13m:ready') { setReady(true); return; }
      if (value.type !== 'argus-13m:navigate' || typeof value.hash !== 'string') return;
      if (value.hash === '#today') onBack();
      else if (value.hash === '#holdings') onNavigate('watchlist');
      else if (/^#asset\/US\.[A-Z0-9.-]{1,20}$/.test(value.hash)) {
        onNavigateToAsset(value.hash.slice('#asset/'.length));
      }
    };
    window.addEventListener('message', receive);
    const timeout = window.setTimeout(() => setSlow(true), 20000);
    return () => { window.removeEventListener('message', receive); window.clearTimeout(timeout); };
  }, [onBack, onNavigate, onNavigateToAsset, frameOrigin]);
  return <section className="thirteenm-page" aria-label="13M">
    <div className="thirteenm-page__bar">
      <button type="button" onClick={onBack} aria-label="前のページへ戻る">←</button>
      <span>13M ・機関投資家の動き</span>
    </div>
    {!ready && <p className="thirteenm-page__status" role="status">{slow
      ? '13Mを表示できていません。通信または13Mの配信状態を確認してください。'
      : '13Mを読み込んでいます…'}</p>}
    <iframe ref={frame} title="13Mの研究と実データ" src={embeddedUrl}
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
      referrerPolicy="no-referrer" className="thirteenm-page__frame" />
  </section>;
}

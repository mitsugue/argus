import React, { useState } from 'react';
import { buildReviewPackMarkdown, copyPack } from '../../lib/reviewPack';
import { latestEventsJa } from '../../lib/positionExposureShare';

// V11.20.0 — Pro Handoff 2.0: 「AIに相談」はAI Review Pack(構造化・重複なし・
// プライバシー選択つき)をコピーする。フル版のみサーバーのwatchlist文脈
// (/pro-handoff — CAOS/機関/ニュース)を末尾に添付。外部AIへの自動送信はしない。
// 旧: 各レイヤーのhandoffテキストを鎖状に連結 → パックに統合(v11.20.0)。

type S = 'idle' | 'loading' | 'copied' | 'manual' | 'error';

export const ProHandoffButton: React.FC = () => {
  const [state, setState] = useState<S>('idle');
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  async function copy(kind: 'full' | 'short' | 'redacted') {
    setOpen(false);
    setState('loading');
    try {
      let serverContextMd: string | undefined;
      if (kind === 'full' && backend) {
        try {
          const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/pro-handoff');
          if (r.ok) serverContextMd = ((await r.json()).promptText || '') as string;
        } catch { /* server context optional — pack remains local-complete */ }
      }
      const md = buildReviewPackMarkdown({
        packType: 'daily',
        privacyMode: kind === 'redacted' ? 'redacted' : 'owner_copy',
        length: kind === 'short' ? 'short' : 'full',
        appVersion: __APP_VERSION__,
        eventsJa: latestEventsJa(),
        serverContextMd,
      });
      setText(md);
      if (await copyPack(md)) {
        setState('copied');
        window.setTimeout(() => setState('idle'), 2500);
      } else {
        setState('manual');
      }
    } catch {
      setState('error');
      window.setTimeout(() => setState('idle'), 2500);
    }
  }

  const label = state === 'loading' ? '準備中…'
    : state === 'copied' ? '✓ コピー済み'
      : state === 'error' ? 'unavailable' : 'AIに相談(パックをコピー)';

  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <button type="button" onClick={() => setOpen((v) => !v)} disabled={state === 'loading'}
        style={{ fontSize: 12, cursor: 'pointer', background: 'transparent', color: 'var(--accent)',
                 border: '1px solid var(--line)', borderRadius: 6, padding: '4px 10px' }}>
        {label}
      </button>
      {open && (
        <span style={{ position: 'absolute', zIndex: 30, top: '110%', left: 0, minWidth: 240,
                       background: 'var(--bg-card, #111)', border: '1px solid var(--line)',
                       borderRadius: 8, padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <button type="button" style={mi} onClick={() => void copy('full')}>
            フルパック(サーバー文脈込み) — GPT Pro深掘り用
          </button>
          <button type="button" style={mi} onClick={() => void copy('short')}>
            短縮パック — さっと相談用(上位論点のみ)
          </button>
          <button type="button" style={mi} onClick={() => void copy('redacted')}>
            redactedパック — 個人投資情報を除外して共有
          </button>
          <span style={{ fontSize: 9.5, color: 'var(--text-faint)' }}>
            フル/短縮には個人投資情報が含まれる可能性があります。共有先に注意。
            コピーのみで自動送信はしません。
          </span>
        </span>
      )}
      {state === 'manual' && (
        <textarea readOnly value={text} onFocus={(e) => e.target.select()}
          style={{ display: 'block', width: '100%', minHeight: 120, marginTop: 6, fontSize: 10 }} />
      )}
    </span>
  );
};

const mi: React.CSSProperties = { fontSize: 11.5, cursor: 'pointer', textAlign: 'left',
  background: 'transparent', color: 'var(--accent)', border: '1px solid var(--line)',
  borderRadius: 6, padding: '4px 8px' };

export default ProHandoffButton;

import React, { useState } from 'react';
import { useAssets } from '../../hooks/useAssets';

// Layer 2B — sync the owner's watchlist MEMBERSHIP (symbols only, no holdings) so
// ARGUS can score the assets you actually care about. The owner-sync token is
// entered once and kept in localStorage on THIS device (it's a dedicated,
// low-scope token — only authorizes membership sync, never portfolio/admin).
const TOKEN_KEY = 'argus.ownerSyncToken.v1';
const SYNC_MARKETS = new Set(['JP', 'US', 'CRYPTO']); // funds (CORE) excluded — no return-scoring

export const Layer2BSyncCard: React.FC = () => {
  const { assets } = useAssets();
  const [token, setToken] = useState<string>(() => {
    try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  const items = assets
    .filter((a) => SYNC_MARKETS.has(a.market))
    .map((a) => ({ symbol: a.symbol, market: a.market, enabled: a.enabled }));

  async function sync() {
    if (!backend) { setResult('バックエンド未設定'); return; }
    if (!token.trim()) { setResult('オーナー同期トークンを入力してください'); return; }
    try { localStorage.setItem(TOKEN_KEY, token.trim()); } catch { /* ignore */ }
    setBusy(true); setResult(null);
    try {
      // The token goes in the JSON BODY (not a header): header values must be
      // ASCII, so a passphrase with Japanese/spaces/symbols would throw
      // "The string did not match the expected pattern" before the request.
      const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/calibration/watchlist-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items, ownerToken: token.trim() }),
      });
      const d = await r.json();
      if (!r.ok) { setResult(`失敗: ${d.error || r.status}${d.errors ? ' — ' + d.errors.join(', ') : ''}`); }
      else {
        setResult(d.status === 'synced'
          ? `✅ 同期完了: ${d.symbolCount}銘柄を private ストアに保存(${d.effectiveFrom})`
          : `⚠️ ${d.status}: ${d.note || ''}`);
      }
    } catch (e) {
      setResult('通信エラー: ' + String(e).slice(0, 60));
    } finally { setBusy(false); }
  }

  return (
    <div className="card guide-card">
      <div className="guide-glossary">
        <div className="guide-term">
          <span className="guide-term__en">Layer 2B 同期</span>
          <span className="guide-term__ja">
            あなたのウォッチリストの<b>銘柄だけ</b>(保有数量・取得単価は送りません)を private ストアへ同期し、
            ARGUS があなたの銘柄を採点できるようにします。対象 {items.length} 銘柄(JP/US/暗号資産)。
          </span>
        </div>
        <div className="guide-term">
          <span className="guide-term__en">オーナー同期トークン</span>
          <span className="guide-term__ja">
            <input
              type="password" value={token} placeholder="Renderに設定したパスフレーズ"
              onChange={(e) => setToken(e.target.value)}
              style={{ width: '100%', padding: '6px 8px', borderRadius: 6,
                       border: '1px solid var(--border, #2a3340)', background: 'transparent',
                       color: 'inherit', fontFamily: 'monospace' }}
            />
            <span style={{ opacity: 0.6, fontSize: '0.85em' }}>
              この端末にのみ保存。membership同期だけに使う専用トークン(管理者権限ではありません)。
            </span>
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
          <button onClick={sync} disabled={busy}
            style={{ padding: '8px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
                     background: 'var(--accent, #3b82f6)', color: '#fff', fontWeight: 600,
                     opacity: busy ? 0.6 : 1 }}>
            {busy ? '同期中…' : '今すぐ同期'}
          </button>
          {result && <span style={{ fontSize: '0.9em' }}>{result}</span>}
        </div>
        <div className="guide-note">
          注意: これは校正(自己採点)のためのメタデータ同期で、注文・自動売買は一切ありません。
          公開リポ対策で、private ストア未設定の場合は採点無効(銘柄は保存されません)。
        </div>
      </div>
    </div>
  );
};

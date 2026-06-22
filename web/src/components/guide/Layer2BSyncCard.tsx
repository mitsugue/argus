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
    const base = backend.replace(/\/$/, '');
    // Render cold-start can return a non-JSON 502/timeout for the first hit, which
    // made r.json() throw "did not match the expected pattern". Warm the dyno,
    // then POST with retries and a SAFE json parse (read text, then try parse).
    try { setResult('接続中(バックエンド起動待ち)…'); await fetch(base + '/healthz').catch(() => {}); } catch { /* ignore */ }
    let lastErr = '';
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const r = await fetch(base + '/api/argus/calibration/watchlist-sync', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ items, ownerToken: token.trim() }),
        });
        const text = await r.text();
        let d: any = null;
        try { d = text ? JSON.parse(text) : null; } catch {
          lastErr = `バックエンド起動中の応答(HTTP ${r.status})`;
          await new Promise((res) => setTimeout(res, 3000 * (attempt + 1)));
          setResult(`再試行中…(${attempt + 1}/3)`);
          continue; // cold-start non-JSON → retry
        }
        if (!r.ok || !d) {
          setResult(`失敗: ${(d && d.error) || r.status}${d && d.errors ? ' — ' + d.errors.join(', ') : ''}`);
        } else if (d.status === 'synced') {
          setResult(`✅ 同期完了: ${d.symbolCount}銘柄を private ストアに保存(${d.effectiveFrom})`);
        } else if (d.status === 'failed') {
          setResult(`⚠️ private保存に失敗: ${d.persistDetail || d.note || ''}`);
        } else {
          setResult(`⚠️ ${d.status}: ${d.note || ''}`);
        }
        setBusy(false);
        return; // got a real response — done
      } catch (e) {
        lastErr = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
        await new Promise((res) => setTimeout(res, 3000 * (attempt + 1)));
        setResult(`再試行中…(${attempt + 1}/3)`);
      }
    }
    setResult(`通信エラー: ${lastErr}(接続先: ${backend})。少し待って再度お試しください。`);
    setBusy(false);
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
              style={{ width: '100%', maxWidth: '100%', boxSizing: 'border-box',
                       padding: '6px 8px', borderRadius: 6,
                       border: '1px solid var(--border, #2a3340)', background: 'transparent',
                       color: 'inherit', fontFamily: 'monospace' }}
            />
            <span style={{ opacity: 0.6, fontSize: '0.85em' }}>
              この端末にのみ保存。membership同期だけに使う専用トークン(管理者権限ではありません)。
            </span>
          </span>
        </div>
        <div style={{ marginTop: 4 }}>
          <button onClick={sync} disabled={busy}
            style={{ padding: '8px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
                     background: 'var(--accent, #3b82f6)', color: '#fff', fontWeight: 600,
                     opacity: busy ? 0.6 : 1 }}>
            {busy ? '同期中…' : '今すぐ同期'}
          </button>
          {result && (
            <div style={{ fontSize: '0.9em', marginTop: 8, overflowWrap: 'anywhere',
                          wordBreak: 'break-word' }}>{result}</div>
          )}
        </div>
        <div className="guide-note">
          注意: これは校正(自己採点)のためのメタデータ同期で、注文・自動売買は一切ありません。
          公開リポ対策で、private ストア未設定の場合は採点無効(銘柄は保存されません)。
        </div>
      </div>
    </div>
  );
};

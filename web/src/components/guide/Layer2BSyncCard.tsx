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
  const [summary, setSummary] = useState<any>(null);
  const [syncStatus, setSyncStatus] = useState<{ synced: string[]; missing: string[] } | null>(null);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  async function restoreFromLayer2B() {
    if (!backend || !token.trim()) { setResult('復元には合言葉を入力してください'); return; }
    if (!confirm('Layer 2Bに同期済みの銘柄でこの端末のウォッチリストを置き換えます(保有数量・取得単価は対象外)。よろしいですか?')) return;
    try {
      const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/calibration/watchlist-membership', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ownerToken: token.trim() }),
      });
      const d = await r.json().catch(() => null);
      const members = d?.membership?.members;
      if (!members || !members.length) { setResult(`復元データなし: ${d?.status || r.status}`); return; }
      const now = Date.now();
      const restored = members.map((m: any, i: number) => {
        const mk = m.market;
        const at = mk === 'JP' ? 'jp_equity' : mk === 'US' ? 'us_equity' : 'crypto';
        const src = mk === 'JP' ? 'jquants' : mk === 'US' ? 'twelvedata' : 'manual';
        return {
          id: `${mk.toLowerCase()}-${m.symbol.toLowerCase()}`, symbol: m.symbol,
          displayName: m.name || m.symbol, displayNameJa: m.name || undefined,
          market: mk, assetType: at, source: src, enabled: true, sortOrder: i,
          createdAt: now, updatedAt: now,
          ...(mk === 'CRYPTO' ? { memo: `coingecko:${m.symbol.toLowerCase() === 'btc' ? 'bitcoin' : m.symbol.toLowerCase() === 'eth' ? 'ethereum' : m.symbol.toLowerCase()}` } : {}),
        };
      });
      localStorage.setItem('argus.assets.v1', JSON.stringify(restored));
      window.dispatchEvent(new Event('argus:data-synced'));
      setResult(`✅ ${restored.length}銘柄を復元しました(JP/US/暗号資産)。投信(CORE)と保有数量はバックアップから復元してください。`);
    } catch (e) {
      setResult('復元エラー: ' + String(e).slice(0, 80));
    }
  }

  async function loadSummary() {
    if (!backend || !token.trim()) { setResult('成績を見るには合言葉を入力してください'); return; }
    try {
      const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/calibration/layer2b-summary', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ownerToken: token.trim() }),
      });
      const d = await r.json().catch(() => null);
      if (d && d.status === 'ok') setSummary(d.summary);
      else setResult(`成績: ${d?.status || 'エラー'}`);
    } catch { setResult('成績の取得に失敗'); }
  }

  // Send ONLY non-monetary flags. `held` is derived from local holdings but the
  // quantity/cost are NEVER included — just the boolean state (v10.100).
  const items = assets
    .filter((a) => SYNC_MARKETS.has(a.market))
    .map((a) => {
      const held = (a.quantity ?? 0) > 0;
      return {
        symbol: a.symbol, market: a.market, enabled: a.enabled,
        ownerState: held ? 'held' : 'watch',
        downsideStrictness: held ? 'strict' : 'normal',
      };
    });
  const heldLocal = items.filter((i) => i.ownerState === 'held').map((i) => i.symbol);

  // #7 — confirm the server (private store) actually treats this device's held /
  // priority names as held/active. If a held name is missing, warn explicitly.
  async function checkSyncStatus() {
    if (!backend || !token.trim()) { setResult('同期状態の確認には合言葉を入力してください'); return; }
    try {
      const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/calibration/watchlist-membership', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ownerToken: token.trim() }),
      });
      const d = await r.json().catch(() => null);
      const members: any[] = d?.membership?.members || [];
      const serverHeld = new Set(
        members.filter((m) => ['held', 'active', 'protected'].includes(m.ownerState))
          .map((m) => String(m.symbol)),
      );
      const synced = heldLocal.filter((s) => serverHeld.has(s));
      const missing = heldLocal.filter((s) => !serverHeld.has(s));
      setSyncStatus({ synced, missing });
    } catch { setResult('同期状態の確認に失敗(合言葉/通信を確認)'); }
  }

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
            あなたのウォッチリストの<b>銘柄と「保有/監視」フラグだけ</b>(保有数量・取得単価・損益は一切送りません)を
            private ストアへ同期し、ARGUS があなたの銘柄を採点・急落時に一段厳しく扱えるようにします。
            対象 {items.length} 銘柄(うち保有 {heldLocal.length})。
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
          <button onClick={loadSummary} disabled={busy}
            style={{ marginLeft: 8, padding: '8px 14px', borderRadius: 8, cursor: 'pointer',
                     background: 'transparent', color: 'inherit',
                     border: '1px solid var(--border, #2a3340)' }}>
            採点成績を見る
          </button>
          <button onClick={restoreFromLayer2B} disabled={busy}
            style={{ marginLeft: 8, padding: '8px 14px', borderRadius: 8, cursor: 'pointer',
                     background: 'transparent', color: 'inherit',
                     border: '1px solid var(--border, #2a3340)' }}>
            銘柄を復元
          </button>
          <button onClick={checkSyncStatus} disabled={busy}
            style={{ marginLeft: 8, padding: '8px 14px', borderRadius: 8, cursor: 'pointer',
                     background: 'transparent', color: 'inherit',
                     border: '1px solid var(--border, #2a3340)' }}>
            同期状態を確認
          </button>
          {syncStatus && (
            <div style={{ fontSize: '0.85em', marginTop: 10, lineHeight: 1.6 }}>
              {heldLocal.length === 0 ? (
                <div style={{ opacity: 0.7 }}>この端末に「保有(数量&gt;0)」の銘柄はありません(監視のみ)。</div>
              ) : syncStatus.missing.length === 0 ? (
                <div style={{ color: 'var(--green, #34D399)' }}>
                  ✅ 保有{heldLocal.length}銘柄すべてサーバー側で「保有/重点監視」として同期済み。
                </div>
              ) : (
                <div style={{ color: 'var(--amber, #FBBF24)' }}>
                  ⚠️ 未同期: {syncStatus.missing.join(', ')} — これらは<b>サーバー側では保有/重点監視として扱われていません</b>。
                  「今すぐ同期」を押すと反映されます(同期後はダウンサイド判定が一段厳しくなります)。
                </div>
              )}
            </div>
          )}
          {result && (
            <div style={{ fontSize: '0.9em', marginTop: 8, overflowWrap: 'anywhere',
                          wordBreak: 'break-word' }}>{result}</div>
          )}
          {summary && (
            <div style={{ fontSize: '0.85em', marginTop: 10, lineHeight: 1.6 }}>
              <div>採点成績(あなたの銘柄・{summary.sampleStage}): 営業日 {summary.tradingDays} / 予測 {summary.nPredictions}件</div>
              {['1d', '3d', '5d'].map((h) => {
                const x = summary.byHorizon?.[h];
                return (
                  <div key={h} style={{ opacity: 0.85 }}>
                    {h}: {x && x.n ? `的中 ${Math.round(x.hitRate * 100)}% / Brier ${x.brierMean}(n=${x.n})` : '採点待ち'}
                  </div>
                );
              })}
              <div style={{ opacity: 0.6 }}>※校正の測定。利益保証ではない。proven表記なし。</div>
            </div>
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

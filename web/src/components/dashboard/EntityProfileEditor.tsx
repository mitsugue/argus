import React from 'react';
import { useAssets } from '../../hooks/useAssets';
import './EntityProfileEditor.css';

// C.A.O.S. プロフィール editor (v10.179) — the association metadata is auto-generated, but
// the owner can customize it here. Edits are saved server-side with source='owner' so they
// take precedence over the seed/AI and are never overwritten by the generator. Authenticated
// with the same owner token used for Layer-2B sync (kept on THIS device only).

const TOKEN_KEY = 'argus.ownerSyncToken.v1';

interface RelatedEntity { name: string; relationJa?: string; type?: string }
interface Profile {
  symbol: string; name?: string; businessJa?: string; sector?: string;
  themes?: string[]; relatedEntities?: RelatedEntity[]; peers?: string[]; keywords?: string[];
  source?: string;
}
interface Draft { businessJa: string; sector: string; themes: string; rel: string; peers: string; keywords: string }

const SOURCE_JA: Record<string, string> = { owner: '編集済み', seed: '初期', ai: 'AI生成', '': '未生成' };

const toLines = (a?: string[]) => (a || []).join('\n');
const fromLines = (s: string) => s.split(/\n/).map((x) => x.trim()).filter(Boolean);
const relToText = (r?: RelatedEntity[]) => (r || []).map((e) => `${e.name} ｜ ${e.relationJa || ''} ｜ ${e.type || ''}`).join('\n');
const textToRel = (s: string): RelatedEntity[] => s.split(/\n/).map((l) => {
  const [name, relationJa, type] = l.split(/｜|\|/).map((x) => x.trim());
  return name ? { name, relationJa: relationJa || '', type: type || '' } : null;
}).filter(Boolean) as RelatedEntity[];

export const EntityProfileEditor: React.FC = () => {
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
  const { assets } = useAssets();
  const [profiles, setProfiles] = React.useState<Record<string, Profile>>({});
  const [openSym, setOpenSym] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [token, setToken] = React.useState(() => { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } });
  const [status, setStatus] = React.useState('');
  const [collapsed, setCollapsed] = React.useState(true);
  const [busyGen, setBusyGen] = React.useState<string | null>(null);

  const guessMarket = (s: string) => (/^\d/.test(s) ? 'JP' : 'US');   // JP tickers start with a digit

  async function generate(sym: string, name: string): Promise<boolean> {
    if (!backend) return false;
    if (!token.trim()) { setStatus('生成には合言葉(オーナートークン)が必要です'); return false; }
    setBusyGen(sym); setStatus(`${sym} を生成中…`);
    try {
      const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/entity-profiles/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ownerToken: token.trim(), symbol: sym, name, market: guessMarket(sym) }),
      });
      if (r.status === 401) { setStatus('合言葉が違います'); return false; }
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) { setStatus(`${sym} の生成に失敗(AIキー/予算を確認)`); return false; }
      try { localStorage.setItem(TOKEN_KEY, token.trim()); } catch { /* ignore */ }
      setStatus(`${sym} を生成しました`);
      load();
      return true;
    } catch { setStatus('生成に失敗(通信エラー)'); return false; }
    finally { setBusyGen(null); }
  }

  async function generateMissing(missing: { symbol: string; name: string }[]) {
    for (let i = 0; i < missing.length; i += 1) {
      setStatus(`未生成を生成中… (${i + 1}/${missing.length})`);
      // eslint-disable-next-line no-await-in-loop
      const ok = await generate(missing[i].symbol, missing[i].name);
      if (!ok) return;   // stop on first failure (auth / key / budget)
    }
    setStatus('未生成の生成が完了しました');
  }

  const load = React.useCallback(() => {
    if (!backend) return;
    fetch(backend.replace(/\/$/, '') + '/api/argus/entity-profiles')
      .then((r) => r.json()).then((j) => setProfiles(j.profiles || {})).catch(() => {});
  }, [backend]);
  React.useEffect(() => { load(); }, [load]);

  const watch = React.useMemo(
    () => assets.map((a) => ({ symbol: a.symbol.toUpperCase(), name: a.displayNameJa || a.displayName })),
    [assets],
  );

  function startEdit(sym: string) {
    const p = profiles[sym] || {};
    setOpenSym(sym);
    setStatus('');
    setDraft({
      businessJa: p.businessJa || '', sector: p.sector || '',
      themes: toLines(p.themes), rel: relToText(p.relatedEntities),
      peers: toLines(p.peers), keywords: toLines(p.keywords),
    });
  }

  async function save(sym: string) {
    if (!backend || !draft) return;
    if (!token.trim()) { setStatus('保存には合言葉(オーナートークン)が必要です'); return; }
    setStatus('保存中…');
    try {
      const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/entity-profiles/edit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ownerToken: token.trim(), symbol: sym, name: profiles[sym]?.name,
          businessJa: draft.businessJa, sector: draft.sector,
          themes: fromLines(draft.themes), relatedEntities: textToRel(draft.rel),
          peers: fromLines(draft.peers), keywords: fromLines(draft.keywords),
        }),
      });
      if (r.status === 401) { setStatus('合言葉が違います'); return; }
      if (!r.ok) { setStatus(`保存に失敗 (${r.status})`); return; }
      try { localStorage.setItem(TOKEN_KEY, token.trim()); } catch { /* ignore */ }
      setStatus('保存しました(AIの自動生成では上書きされません)');
      setOpenSym(null); setDraft(null);
      load();
    } catch { setStatus('保存に失敗(通信エラー)'); }
  }

  return (
    <section className="epe">
      <button className="epe-head" onClick={() => setCollapsed((c) => !c)}>
        <span className="epe-title">C.A.O.S. プロフィール</span>
        <span className="epe-sub">連想メタデータ — 自動生成＋手動カスタム</span>
        <span className="epe-toggle">{collapsed ? '▸ 開く' : '▾ 閉じる'}</span>
      </button>
      {!collapsed && (
        <div className="epe-body">
          <p className="epe-note">
            ニュースを銘柄に連想で紐づけるための裏メタデータです。空欄は自動生成に任せられます。
            ここでの編集はオーナーの合言葉で保存され、<b>AIの自動生成では上書きされません</b>。
          </p>
          <input className="epe-token" type="password" placeholder="合言葉(オーナートークン・この端末に保存)"
                 value={token} onChange={(e) => setToken(e.target.value)} />
          {(() => {
            const missing = watch.filter(({ symbol }) => !profiles[symbol]);
            return missing.length > 0 ? (
              <div className="epe-genall-row">
                <button className="epe-genall" disabled={!!busyGen} onClick={() => generateMissing(missing)}>
                  未生成をまとめて生成 ({missing.length}件)
                </button>
                {status && <span className="epe-status">{status}</span>}
              </div>
            ) : null;
          })()}
          {watch.map(({ symbol, name }) => {
            const p = profiles[symbol];
            const editing = openSym === symbol;
            return (
              <div className="epe-row" key={symbol}>
                <div className="epe-row-head">
                  <span className="epe-sym">{symbol}</span>
                  <span className="epe-name">{name}</span>
                  <span className={`epe-src epe-src--${p?.source || 'none'}`}>{SOURCE_JA[p?.source || ''] ?? p?.source}</span>
                  <span className="epe-btns">
                    <button className="epe-gen" disabled={busyGen === symbol} onClick={() => generate(symbol, name)}>
                      {busyGen === symbol ? '生成中…' : (p ? '再生成' : '生成')}
                    </button>
                    <button className="epe-edit" onClick={() => (editing ? (setOpenSym(null), setDraft(null)) : startEdit(symbol))}>
                      {editing ? 'キャンセル' : '編集'}
                    </button>
                  </span>
                </div>
                {!editing && p?.businessJa && <p className="epe-biz">{p.businessJa}</p>}
                {!editing && (p?.keywords?.length ?? 0) > 0 && (
                  <p className="epe-kw">関連語: {(p!.keywords || []).slice(0, 12).join(' · ')}</p>
                )}
                {editing && draft && (
                  <div className="epe-form">
                    <label>事業内容<textarea rows={2} value={draft.businessJa} onChange={(e) => setDraft({ ...draft, businessJa: e.target.value })} /></label>
                    <label>関連語(キーワード・1行に1つ)<textarea rows={4} value={draft.keywords} onChange={(e) => setDraft({ ...draft, keywords: e.target.value })} /></label>
                    <label>関連先(1行: 名前 ｜ なぜ動くか ｜ 種別)<textarea rows={4} value={draft.rel} onChange={(e) => setDraft({ ...draft, rel: e.target.value })} /></label>
                    <label>テーマ(1行に1つ)<textarea rows={2} value={draft.themes} onChange={(e) => setDraft({ ...draft, themes: e.target.value })} /></label>
                    <label>同業(1行に1つ)<textarea rows={2} value={draft.peers} onChange={(e) => setDraft({ ...draft, peers: e.target.value })} /></label>
                    <div className="epe-actions">
                      <button className="epe-save" onClick={() => save(symbol)}>保存</button>
                      {status && <span className="epe-status">{status}</span>}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {watch.length === 0 && <p className="epe-note">ウォッチリストに銘柄がありません。</p>}
        </div>
      )}
    </section>
  );
};

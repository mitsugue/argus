import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { searchFunds } from '../../lib/fundCatalog';
import type { AssetMarket, AssetType, AssetSource } from '../../types/assetItem';

type Kind = 'Japan Stock' | 'US Stock' | 'Crypto' | 'Core / Fund';

const KIND_MAP: Record<Kind, {
  market: AssetMarket; assetType: AssetType; source: AssetSource;
  symbolHint: string; searchMarket?: 'JP' | 'US' | 'CRYPTO';
}> = {
  'Japan Stock': { market: 'JP', assetType: 'jp_equity', source: 'jquants', symbolHint: '社名 or コード (例: 三菱 / 8058)', searchMarket: 'JP' },
  'US Stock': { market: 'US', assetType: 'us_equity', source: 'twelvedata', symbolHint: 'name or ticker (e.g. apple / NVDA)', searchMarket: 'US' },
  'Crypto': { market: 'CRYPTO', assetType: 'crypto', source: 'manual', symbolHint: 'name or symbol (e.g. solana / SOL)', searchMarket: 'CRYPTO' },
  'Core / Fund': { market: 'CORE', assetType: 'manual_fund', source: 'manual', symbolHint: '例: emaxis / オルカン / S&P500' },
};
const KINDS = Object.keys(KIND_MAP) as Kind[];

interface Candidate { symbol: string; name: string; nameJa: string; exchange: string; type: string; coingeckoId?: string; }

interface Props {
  onClose: () => void;
  onAdd: (a: { market: AssetMarket; assetType: AssetType; source: AssetSource; symbol: string; displayName: string; displayNameJa?: string; memo?: string }) => string | null;
}

export const AddAssetModal: React.FC<Props> = ({ onClose, onAdd }) => {
  const [kind, setKind] = useState<Kind>('Japan Stock');
  const [symbol, setSymbol] = useState('');
  const [name, setName] = useState('');
  const [nameJa, setNameJa] = useState('');
  const [cgId, setCgId] = useState('');
  const [err, setErr] = useState('');
  const [results, setResults] = useState<Candidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const [picked, setPicked] = useState(false);
  const cfg = KIND_MAP[kind];
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
  const debounce = useRef<number | undefined>(undefined);

  // Reset candidates when switching asset type.
  useEffect(() => { setResults([]); setPicked(false); }, [kind]);

  // Debounced symbol/name search → candidate list (skips Core/Fund and after a pick).
  useEffect(() => {
    if (!cfg.searchMarket || !backend || picked) { setResults([]); return; }
    const q = symbol.trim();
    if (q.length < 1) { setResults([]); setSearching(false); setSearchErr(null); return; }
    setSearching(true); setSearchErr(null);
    window.clearTimeout(debounce.current);
    const ctrl = new AbortController();
    debounce.current = window.setTimeout(async () => {
      try {
        const url = backend.replace(/\/$/, '') + `/api/argus/symbol-search?market=${cfg.searchMarket}&q=${encodeURIComponent(q)}`;
        const r = await fetch(url, { signal: ctrl.signal });
        if (r.status === 429) { setResults([]); setSearchErr('混雑しています。数秒待って入力し直してください。'); return; }
        const d = await r.json();
        // status 'error'/'unavailable' from the backend ≠ "no such symbol" — say so
        if (d && (d.status === 'error' || d.status === 'unavailable') && (!Array.isArray(d.results) || !d.results.length)) {
          setResults([]); setSearchErr('検索が一時的に使えません。少し待って再試行してください。'); return;
        }
        setSearchErr(null);
        setResults(Array.isArray(d.results) ? d.results.slice(0, 12) : []);
      } catch (e) {
        if ((e as { name?: string })?.name !== 'AbortError') setSearchErr(null);  // network/abort → silent
      }
      finally { setSearching(false); }
    }, 300);
    return () => { ctrl.abort(); window.clearTimeout(debounce.current); };
  }, [symbol, cfg.searchMarket, backend, picked]);

  function pick(c: Candidate) {
    setPicked(true);
    setSymbol(c.symbol);
    setName(c.name || c.symbol);
    setNameJa(c.nameJa || '');
    setCgId(c.coingeckoId || '');
    setResults([]);
  }

  // Local fund-catalog search (投信 are NOT in J-Quants — listed only), v10.1.
  const fundResults = useMemo(
    () => (kind === 'Core / Fund' && !picked ? searchFunds(symbol.trim()) : []),
    [kind, symbol, picked],
  );

  function pickFund(slug: string, nameJaF: string) {
    setPicked(true);
    setSymbol(slug);
    setName(nameJaF);
    setNameJa(nameJaF);
  }

  function submit() {
    const sym = kind === 'US Stock' ? symbol.trim().toUpperCase() : symbol.trim();
    const dn = name.trim();
    if (!sym || !dn) { setErr('シンボルと表示名は必須です(候補をクリックすると自動入力)。'); return; }
    const memo = kind === 'Crypto' && cgId ? `coingecko:${cgId}` : undefined;
    const id = onAdd({
      market: cfg.market, assetType: cfg.assetType, source: cfg.source,
      symbol: sym, displayName: dn, displayNameJa: nameJa.trim() || undefined, memo,
    });
    if (!id) { setErr('追加できませんでした(重複、または上限50件)。'); return; }
    onClose();
  }

  // Portal to <body> so the fixed overlay escapes the overscroll-transformed
  // page shell (a transform ancestor was making it render far down the screen).
  return createPortal(
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Add asset" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <span className="modal__title">Add Asset</span>
          <button className="modal__close" aria-label="Close" onClick={onClose}>×</button>
        </div>

        <label className="modal__label">Asset type</label>
        <div className="modal__kinds">
          {KINDS.map((k) => (
            <button key={k} className={`asset-tab${kind === k ? ' asset-tab--on' : ''}`} onClick={() => setKind(k)}>{k}</button>
          ))}
        </div>

        <label className="modal__label" htmlFor="add-symbol">
          {cfg.searchMarket || kind === 'Core / Fund' ? 'Search (name or symbol)' : 'Symbol / code'}
        </label>
        <input id="add-symbol" className="modal__input" value={symbol} placeholder={cfg.symbolHint}
               autoComplete="off"
               onChange={(e) => { setSymbol(e.target.value); setPicked(false); }} />

        {cfg.searchMarket && !picked && (
          <div className="search-results">
            {searching && <div className="search-results__hint">検索中…</div>}
            {!searching && searchErr && <div className="search-results__hint" style={{ color: 'var(--amber,#fbbf24)' }}>{searchErr}</div>}
            {!searching && !searchErr && symbol.trim() && results.length === 0 && <div className="search-results__hint">候補なし</div>}
            {results.map((c) => (
              <button key={`${c.symbol}-${c.exchange}-${c.coingeckoId ?? ''}`} className="search-result" onClick={() => pick(c)}>
                <span className="search-result__sym">{c.symbol}</span>
                <span className="search-result__name">{c.nameJa || c.name}</span>
                {c.exchange && <span className="search-result__ex">{c.exchange}</span>}
              </button>
            ))}
          </div>
        )}

        {kind === 'Core / Fund' && !picked && symbol.trim() && (
          <div className="search-results">
            {fundResults.length === 0 && <div className="search-results__hint">カタログに候補なし(手動入力も可能)</div>}
            {fundResults.map((f) => (
              <button key={f.slug} className="search-result" onClick={() => pickFund(f.slug, f.nameJa)}>
                <span className="search-result__sym">{f.slug}</span>
                <span className="search-result__name">{f.nameJa}</span>
                <span className="search-result__ex">投信</span>
              </button>
            ))}
          </div>
        )}

        <label className="modal__label" htmlFor="add-name">Display name</label>
        <input id="add-name" className="modal__input" value={name} placeholder="表示名"
               onChange={(e) => setName(e.target.value)} />

        {cfg.market === 'JP' && (
          <>
            <label className="modal__label" htmlFor="add-nameja">Japanese name (optional)</label>
            <input id="add-nameja" className="modal__input" value={nameJa} placeholder="日本語社名"
                   onChange={(e) => setNameJa(e.target.value)} />
          </>
        )}

        <div className="modal__hint">
          {cfg.market === 'CRYPTO' && '候補は CoinGecko 検索。選ぶとライブUSD価格に自動接続されます。'}
          {cfg.market === 'CORE' && '主要投信カタログからローカル検索(ライブ基準価額は未取得)。一覧にない投信は手動入力も可能。'}
          {cfg.market === 'JP' && '候補は J-Quants 上場銘柄マスタから検索。社名やコードを入力してください。'}
          {cfg.market === 'US' && '候補は Twelve Data から検索。社名やティッカーを入力してください。'}
        </div>

        {err && <div className="modal__err">{err}</div>}

        <div className="modal__actions">
          <button className="asset-btn" onClick={onClose}>Cancel</button>
          <button className="asset-btn asset-btn--primary" onClick={submit}>Add</button>
        </div>
      </div>
    </div>,
    document.body,
  );
};

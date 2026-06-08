import React, { useState } from 'react';
import type { AssetMarket, AssetType, AssetSource } from '../../types/assetItem';

type Kind = 'Japan Stock' | 'US Stock' | 'Crypto' | 'Core / Fund';

const KIND_MAP: Record<Kind, { market: AssetMarket; assetType: AssetType; source: AssetSource; symbolHint: string }> = {
  'Japan Stock': { market: 'JP', assetType: 'jp_equity', source: 'jquants', symbolHint: 'e.g. 8058 / 285A' },
  'US Stock': { market: 'US', assetType: 'us_equity', source: 'twelvedata', symbolHint: 'e.g. NVDA' },
  'Crypto': { market: 'CRYPTO', assetType: 'crypto', source: 'manual', symbolHint: 'e.g. BTC (coingecko id optional)' },
  'Core / Fund': { market: 'CORE', assetType: 'manual_fund', source: 'manual', symbolHint: 'e.g. EMAXIS-ACWI' },
};
const KINDS = Object.keys(KIND_MAP) as Kind[];

interface Props {
  onClose: () => void;
  onAdd: (a: { market: AssetMarket; assetType: AssetType; source: AssetSource; symbol: string; displayName: string; displayNameJa?: string; memo?: string }) => string | null;
}

export const AddAssetModal: React.FC<Props> = ({ onClose, onAdd }) => {
  const [kind, setKind] = useState<Kind>('Japan Stock');
  const [symbol, setSymbol] = useState('');
  const [name, setName] = useState('');
  const [nameJa, setNameJa] = useState('');
  const [err, setErr] = useState('');
  const cfg = KIND_MAP[kind];

  function submit() {
    const sym = kind === 'US Stock' ? symbol.trim().toUpperCase() : symbol.trim();
    const dn = name.trim();
    if (!sym || !dn) { setErr('シンボルと表示名は必須です。'); return; }
    const id = onAdd({
      market: cfg.market, assetType: cfg.assetType, source: cfg.source,
      symbol: sym, displayName: dn, displayNameJa: nameJa.trim() || undefined,
    });
    if (!id) { setErr('追加できませんでした(重複、または上限50件)。'); return; }
    onClose();
  }

  return (
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

        <label className="modal__label" htmlFor="add-symbol">Symbol / code</label>
        <input id="add-symbol" className="modal__input" value={symbol} placeholder={cfg.symbolHint}
               onChange={(e) => setSymbol(e.target.value)} />

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
          {cfg.market === 'CRYPTO' && 'v9.2.0では暗号資産はライブ価格未接続(手動)。'}
          {cfg.market === 'CORE' && '長期コア/投信は手動管理(ライブ基準価額なし)。'}
          {cfg.market === 'JP' && 'シンボルと社名は推測せず正確に入力してください(例: 8058=三菱商事)。'}
        </div>

        {err && <div className="modal__err">{err}</div>}

        <div className="modal__actions">
          <button className="asset-btn" onClick={onClose}>Cancel</button>
          <button className="asset-btn asset-btn--primary" onClick={submit}>Add</button>
        </div>
      </div>
    </div>
  );
};

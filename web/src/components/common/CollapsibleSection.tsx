import React from 'react';

// V11.21.0 — Mobile UX / 情報圧縮の共通部品。
// CollapsibleSection: 低優先セクションを「件数+最重要度+一行結論」に畳む。
// 中身は開くまでレンダリングしない(lazy — モバイル性能とAPI節約)。
// ExpandableReason: 長い日本語段落を一文目+「続きを見る」に圧縮する。

// v12.0.6: 開閉状態の端末内記憶(GPT既知課題「再訪でリセット」)。localStorageのみ・
// サーバー送信なし・値は{key: boolean}だけで銘柄/保有情報を含まない。
// defaultOpen(高リスク自動展開)はtrueなら記憶より優先(安全側)。
const COLLAPSE_STORE_KEY = 'argus.todayCollapse.v1';

function readCollapseStore(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(COLLAPSE_STORE_KEY);
    const v = raw ? JSON.parse(raw) : {};
    return v && typeof v === 'object' ? v as Record<string, boolean> : {};
  } catch { return {}; }   // localStorage不可でも壊れない(記憶なしで動く)
}

function writeCollapseState(key: string, open: boolean): void {
  try {
    const cur = readCollapseStore();
    cur[key] = open;
    localStorage.setItem(COLLAPSE_STORE_KEY, JSON.stringify(cur));
  } catch { /* storage unavailable — 記憶なしで続行 */ }
}

/** 「表示リセット」— 記憶した開閉状態を全消去(既定の静かな圧縮表示へ)。 */
export function resetTodayLayout(): void {
  try { localStorage.removeItem(COLLAPSE_STORE_KEY); } catch { /* noop */ }
}

export const CollapsibleSection: React.FC<{
  title: string;
  /** 件数など右肩の短いラベル */
  countLabel?: string;
  /** 一行結論(畳んだ状態で読める要約) */
  conclusionJa?: string;
  /** 最重要度の色(チップ枠) — 無指定はニュートラル */
  severityTone?: string;
  defaultOpen?: boolean;
  /** v12.0.6: 指定すると開閉状態を端末内に記憶(再訪しても保持) */
  persistKey?: string;
  /** lazy render: 開くまで children() は呼ばれない */
  children: () => React.ReactNode;
}> = ({ title, countLabel, conclusionJa, severityTone, defaultOpen = false, persistKey, children }) => {
  const [open, setOpenRaw] = React.useState(() => {
    if (defaultOpen) return true;                       // 高リスク自動展開は記憶より優先
    if (persistKey) return readCollapseStore()[persistKey] === true;
    return false;
  });
  const setOpen = (fn: (v: boolean) => boolean) => setOpenRaw((v) => {
    const nv = fn(v);
    if (persistKey) writeCollapseState(persistKey, nv);
    return nv;
  });
  return (
    <section>
      <button type="button" onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{ display: 'flex', alignItems: 'baseline', gap: 8, width: '100%',
                 background: 'transparent', border: 'none', cursor: 'pointer',
                 padding: '6px 0', textAlign: 'left', minHeight: 34 }}>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>{open ? '▼' : '▶'}</span>
        <span className="section-head__title" style={{ fontSize: 13 }}>{title}</span>
        {countLabel && (
          <span style={{ fontSize: 10.5, color: severityTone ?? 'var(--text-faint)',
                         border: `1px solid ${severityTone ?? 'var(--line)'}`,
                         borderRadius: 999, padding: '0 7px', whiteSpace: 'nowrap' }}>
            {countLabel}
          </span>
        )}
        {!open && conclusionJa && (
          <span style={{ fontSize: 11, color: 'var(--text-sub)', overflow: 'hidden',
                         textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
            {conclusionJa}
          </span>
        )}
      </button>
      {open && children()}
    </section>
  );
};

/** 一行目だけ見せて「続きを見る」で全文展開(重複説明のスクロール圧迫を防ぐ)。 */
export const ExpandableReason: React.FC<{ text: string; style?: React.CSSProperties;
  className?: string }> = ({ text, style, className }) => {
  const [open, setOpen] = React.useState(false);
  const cut = text.indexOf('。');
  const first = cut >= 0 && cut < text.length - 1 ? text.slice(0, cut + 1) : text;
  const hasMore = first.length < text.length;
  return (
    <p className={className} style={{ margin: '2px 0 0', ...style }}>
      {open || !hasMore ? text : first}
      {hasMore && (
        <button type="button" onClick={() => setOpen((v) => !v)}
          style={{ marginLeft: 6, fontSize: 10, cursor: 'pointer', background: 'transparent',
                   color: 'var(--accent)', border: 'none', padding: '2px 4px' }}>
          {open ? '閉じる' : '続きを見る'}
        </button>
      )}
    </p>
  );
};

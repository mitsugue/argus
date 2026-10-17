import { useEffect, useState } from 'react';
import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../../lib/pollingPolicy';
import { jpDisplay } from '../../lib/displayName';

// 2026-10-17 (owner): the Nikkei 225 contributions need a member's price
// adjustment factor only when it is not in the month-end weight table (a new
// member, a split, a review). This form appears only then, with the page to
// copy it from, and disappears once the numbers add up again.
type Missing = { code: string; nameJa: string | null; since: string | null };
type State = { revision: number; inputDue: boolean; missing: Missing[];
  mismatch: { endDate: string | null; residualPoints: number | null } | null;
  entries: { code: string; factor: number; effectiveFrom: string }[]; sourceUrl: string };
const base = String(import.meta.env.VITE_ARGUS_BACKEND_URL ?? '').replace(/\/$/, '');
const route = base + '/api/argus/owner-auth/index-factors';
const today = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' });
const valid = (v: unknown): v is State => !!v && typeof v === 'object' && Number.isInteger((v as State).revision)
  && typeof (v as State).inputDue === 'boolean' && Array.isArray((v as State).missing) && Array.isArray((v as State).entries)
  && typeof (v as State).sourceUrl === 'string' && (v as State).sourceUrl.startsWith('https://indexes.nikkei.co.jp/');

export function IndexFactorInput() {
  const [state, setState] = useState<State | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [other, setOther] = useState({ code: '', factor: '', day: today() });
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  useEffect(() => {
    let alive = true;
    const read = async () => {
      try {
        const r = await fetch(route, { cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(10000) });
        if (!r.ok) return;                                   // not signed in: nothing to show
        const body: unknown = await r.json();
        if (alive && valid(body)) setState(body);
      } catch { /* the form is optional; the table states its own status */ }
    };
    if (document.visibilityState === 'visible') void read();
    const stop = subscribeInitialVisibleRead(() => { void read(); }, false);
    const timer = scheduleVisibleInterval(() => { void read(); }, 600000);
    return () => { alive = false; stop(); timer(); };
  }, []);
  if (!state?.inputDue) return null;
  const save = async (code: string, factor: string, effectiveFrom: string) => {
    if (busy) return;
    setBusy(true); setMessage('');
    try {
      const r = await fetch(route, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: state.revision, operation: 'save', code: code.trim().toUpperCase(),
          factor: Number(factor), effectiveFrom }), cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15000) });
      const result: unknown = await r.json();
      if (!r.ok || !valid(result)) {
        setMessage((result as { error?: string })?.error === 'revision_conflict'
          ? '別の画面で更新されています。少し待ってから入力してください。'
          : '保存できませんでした。係数は0.1刻みの数字(例 1.0、0.5)で、適用日は営業日を入力してください。');
        return;
      }
      setState(result); setValues({}); setOther({ code: '', factor: '', day: today() });
      setMessage('保存しました。次の更新で寄与度に反映します。');
    } catch { setMessage('保存を確認できません。入力内容はこの画面に残しています。'); }
    finally { setBusy(false); }
  };
  return <section className="lm-manual-per at-factor-input" aria-label="株価換算係数の入力" data-argus-contract="index-factor-input-v1">
    <h4>日経平均の寄与度に必要な数字の入力</h4>
    <a href={state.sourceUrl} target="_blank" rel="noopener noreferrer">日経平均プロフィルの指数情報を開く ↗</a>
    <p className="lm-note">開いたページの<strong>「株価換算係数一覧(CSV)」</strong>から、下の銘柄の「株価換算係数」を書き写してください。</p>
    {state.missing.map(row => <form key={row.code} onSubmit={e => { e.preventDefault(); void save(row.code, values[row.code] ?? '', row.since ?? today()); }}>
      <label>{jpDisplay(row.code, row.nameJa)}{row.since && <small>（{row.since}に採用）</small>}
        <input type="number" inputMode="decimal" min="0.1" step="0.1" required autoComplete="off"
          value={values[row.code] ?? ''} onChange={e => setValues(v => ({ ...v, [row.code]: e.target.value }))} /></label>
      <button type="submit" disabled={busy}>{busy ? '保存中…' : '保存'}</button>
    </form>)}
    {state.missing.length === 0 && state.mismatch && <>
      <p className="lm-note">{state.mismatch.endDate}の寄与度の合計が、日経平均の値動きと{state.mismatch.residualPoints?.toFixed(2)}円ずれています。株式分割などで係数が変わった銘柄がある可能性があります。日経のお知らせで変わった銘柄を確かめ、その銘柄の新しい係数と適用日を入力してください。</p>
      <form onSubmit={e => { e.preventDefault(); void save(other.code, other.factor, other.day); }}>
        <label>銘柄コード<input required pattern="[0-9][0-9A-Za-z]{3}" value={other.code} onChange={e => setOther(o => ({ ...o, code: e.target.value }))} /></label>
        <label>株価換算係数<input type="number" inputMode="decimal" min="0.1" step="0.1" required value={other.factor}
          onChange={e => setOther(o => ({ ...o, factor: e.target.value }))} /></label>
        <label>適用日<input type="date" required max={today()} value={other.day} onChange={e => setOther(o => ({ ...o, day: e.target.value }))} /></label>
        <button type="submit" disabled={busy}>{busy ? '保存中…' : '保存'}</button>
      </form></>}
    <p className="lm-note">入力した数字は非公開で保存し、自動では取得しません。数字がそろうとこの欄は消えます。</p>
    {message && <p role="status">{message}</p>}
  </section>;
}

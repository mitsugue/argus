import { useEffect, useState } from 'react';
import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../../lib/pollingPolicy';
import { sessionViewCheckpoint } from '../../lib/sessionViewCheckpoint';

type Drift = { inputs: number; latestPct: number | null; previousPct: number | null; warning: boolean };
type State = { revision: number; enabled: boolean; referenceDate: string | null; stale: boolean;
  inputDue: boolean; defaultDate: string; dueDate: string; appliedFromDate?: string | null; drift?: Drift };
// 2026-10-27 (owner): the estimated EPS against the official input, one line; coloured only when off.
const pct = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
const validDrift = (d: unknown): d is Drift => !!d && typeof d === 'object' && Number.isInteger((d as Drift).inputs)
  && typeof (d as Drift).warning === 'boolean'
  && ((d as Drift).latestPct === null || Number.isFinite((d as Drift).latestPct))
  && ((d as Drift).previousPct === null || Number.isFinite((d as Drift).previousPct));
const base = String(import.meta.env.VITE_ARGUS_BACKEND_URL ?? '').replace(/\/$/, '');
const source = 'https://indexes.nikkei.co.jp/nkave/archives/data?list=per';
const valid = (v: State | null | undefined): v is State => !!v && Number.isInteger(v.revision) && v.revision >= 0
  && typeof v.enabled === 'boolean' && typeof v.inputDue === 'boolean' && typeof v.stale === 'boolean'
  && /^\d{4}-\d{2}-\d{2}$/.test(v.defaultDate) && /^\d{4}-\d{2}-\d{2}$/.test(v.dueDate)
  && (v.referenceDate === null || /^\d{4}-\d{2}-\d{2}$/.test(v.referenceDate));
function remember(v: State) {
  // Status/date only. Never keep an entered PER or the calibration ratio.
  const safe = { revision: v.revision, enabled: v.enabled, referenceDate: v.referenceDate, stale: v.stale,
    inputDue: v.inputDue, defaultDate: v.defaultDate, dueDate: v.dueDate, appliedFromDate: v.appliedFromDate };
  if (sessionViewCheckpoint.keep('weighted-per-input', safe)) void sessionViewCheckpoint.flush();
}

export function WeightedPerInput() {
  const saved = sessionViewCheckpoint.restoredValue('weighted-per-input') as State | undefined;
  const restored = valid(saved);
  const [state, setState] = useState<State | null>(() => restored ? saved : null);
  const [day, setDay] = useState(() => restored ? saved.defaultDate : ''), [value, setValue] = useState('');
  const [editing, setEditing] = useState(false), [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    let alive = true;
    const read = async () => {
      try {
        const r = await fetch(base + '/api/argus/owner-auth/weighted-per', { cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(10000) });
        if (!r.ok) throw new Error('unavailable');
        const body = await r.json() as State;
        if (!valid(body)) throw new Error('invalid_status');
        if (alive) { setState(body); remember(body); setDay(d => d || body.defaultDate); }
      } catch { if (alive) setMessage('保存状態不明'); }
    };
    if (!restored && document.visibilityState === 'visible') void read();
    const stop = subscribeInitialVisibleRead(() => { void read(); }, restored);
    const timer = scheduleVisibleInterval(() => { void read(); }, 600000);
    return () => { alive = false; stop(); timer(); };
  }, []);
  const save = async (operation: 'save' | 'clear', confirmed = false) => {
    if (!state || busy) return;
    if (operation === 'clear' && !window.confirm('入力値を消して、補正なしに戻しますか？')) return;
    setBusy(true); setMessage('');
    try {
      const body = operation === 'save' ? { revision: state.revision, operation, date: day, per: Number(value), confirmed }
        : { revision: state.revision, operation };
      const r = await fetch(base + '/api/argus/owner-auth/weighted-per', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15000),
      });
      const result = await r.json();
      if (!r.ok) {
        if (result.error === 'confirmation_required') {
          setBusy(false);
          if (window.confirm('同じ日のARGUS推計と15%以上違います。左の「加重平均」と対象日を確認しましたか？')) {
            // A deliberate second submit carries the same date/value and revision.
            setMessage('確認後、「確認して保存」を押してください。'); setConfirmNeeded(true);
          }
          return;
        }
        setMessage(result.error === 'same_day_estimate_unavailable' ? 'この日の終値と完全な推計EPSがまだそろっていません。日付を確認してください。'
          : result.error === 'revision_conflict' ? '別の画面で更新されています。保存状態の更新を待ってから入力してください。'
          : '保存できませんでした。入力内容はこの画面に残しています。');
        return;
      }
      if (!valid(result)) throw new Error('invalid_status');
      setState(result); remember(result); setValue(''); setEditing(false); setConfirmNeeded(false);
      setMessage(operation === 'clear' ? '補正なしに戻しました。' : '保存しました。');
      window.dispatchEvent(new Event('argus:weighted-per-changed'));
    } catch { setMessage('保存を確認できません。入力内容はこの画面に残しています。'); }
    finally { setBusy(false); }
  };
  const [confirmNeeded, setConfirmNeeded] = useState(false);
  const show = state && (state.inputDue || editing);
  return <section className="lm-manual-per" aria-label="加重平均PERの入力" data-argus-contract="weighted-per-input-v1">
    {state && <p className="lm-note">{state.enabled ? `補正あり · 対象日 ${state.referenceDate}${state.appliedFromDate ? ` · ${state.appliedFromDate}以降に適用` : ''}` : '補正なし'}
      {state.stale && ' · 10営業日超・要更新'}
      {!show && <button type="button" onClick={() => setEditing(true)}>入力・変更</button>}</p>}
    {state && validDrift(state.drift) && state.drift.latestPct !== null && <p className={state.drift.warning ? 'lm-note lm-drift--warn' : 'lm-note'}
      data-drift-warning={state.drift.warning}>推計EPS 公式比 {pct(state.drift.latestPct)}
      {state.drift.previousPct !== null && `（前回 ${pct(state.drift.previousPct)}）`}</p>}
    {show && <form onSubmit={e => { e.preventDefault(); void save('save', confirmNeeded); }}>
      <h4>今週の加重平均を書き写す</h4>
      <a href={source} target="_blank" rel="noopener noreferrer">日経平均プロフィルのPERを見る ↗</a>
      <p className="lm-note">「予想PER」の左の列<strong>「加重平均」</strong>を入力。右の「指数ベース」ではありません。</p>
      <label>対象日<input type="date" required value={day} max={state.defaultDate} onChange={e => { setDay(e.target.value); setConfirmNeeded(false); }} /></label>
      <label>予想PER（加重平均・倍）<input type="number" inputMode="decimal" min="0.01" step="any" required autoComplete="off"
        value={value} onChange={e => { setValue(e.target.value); setConfirmNeeded(false); }} /></label>
      <button disabled={busy} type="submit">{busy ? '保存中…' : confirmNeeded ? '確認して保存' : '保存'}</button>
    </form>}
    {state?.enabled && <button type="button" disabled={busy} onClick={() => { void save('clear'); }}>入力値を消して補正をやめる</button>}
    {message && <p role="status">{message}</p>}
  </section>;
}

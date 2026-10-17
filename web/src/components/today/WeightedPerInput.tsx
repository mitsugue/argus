import { useEffect, useState } from 'react';
import { scheduleVisibleInterval, subscribeInitialVisibleRead } from '../../lib/pollingPolicy';
import { sessionViewCheckpoint } from '../../lib/sessionViewCheckpoint';

type State = { revision: number; enabled: boolean; referenceDate: string | null; stale: boolean;
  inputDue: boolean; defaultDate: string; dueDate: string; appliedFromDate?: string | null };
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
      } catch { if (alive) setMessage('入力の保存状態を確認できません。'); }
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
      setMessage(operation === 'clear' ? '補正なしに戻しました。' : '保存しました。入力後の日付のPER線・目盛りに反映します。');
      window.dispatchEvent(new Event('argus:weighted-per-changed'));
    } catch { setMessage('保存を確認できません。入力内容はこの画面に残しています。'); }
    finally { setBusy(false); }
  };
  const [confirmNeeded, setConfirmNeeded] = useState(false);
  const show = state && (state.inputDue || editing);
  return <section className="lm-manual-per" aria-label="加重平均PERの入力" data-argus-contract="weighted-per-input-v1">
    {state && <p className="lm-note">{state.enabled ? `表示用の補正設定あり · 最終入力の対象日 ${state.referenceDate}${state.appliedFromDate ? ` · ${state.appliedFromDate}以降の推計から適用` : ''}` : '表示用補正なし'}
      {state.stale && ' · 10営業日を超えています。更新してください。'}
      {!show && <button type="button" onClick={() => setEditing(true)}>入力・変更</button>}</p>}
    {show && <form onSubmit={e => { e.preventDefault(); void save('save', confirmNeeded); }}>
      <h4>今週の加重平均を書き写す</h4>
      <a href={source} target="_blank" rel="noopener noreferrer">日経平均プロフィルのPERを見る ↗</a>
      <p className="lm-note">「予想PER」の左の列<strong>「加重平均」</strong>を入力。右の「指数ベース」ではありません。</p>
      <label>対象日<input type="date" required value={day} max={state.defaultDate} onChange={e => { setDay(e.target.value); setConfirmNeeded(false); }} /></label>
      <label>予想PER（加重平均・倍）<input type="number" inputMode="decimal" min="0.01" step="any" required autoComplete="off"
        value={value} onChange={e => { setValue(e.target.value); setConfirmNeeded(false); }} /></label>
      <button disabled={busy} type="submit">{busy ? '保存中…' : confirmNeeded ? '確認して保存' : '保存'}</button>
      <p className="lm-note">週の最終営業日16:30以降に次の入力を案内します。入力値は非公開で保存し、自動取得しません。朝の固定記録・過去の成績は変えません。</p>
    </form>}
    {state?.enabled && <button type="button" disabled={busy} onClick={() => { void save('clear'); }}>入力値を消して補正をやめる</button>}
    {message && <p role="status">{message}</p>}
  </section>;
}

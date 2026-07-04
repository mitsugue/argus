import React from 'react';
import {
  annotateOwnerAction, dqSummary, lastOutcomeUpdateAt, listDQ,
  OWNER_ACTION_JA, type DQRecord,
} from '../../lib/decisionQuality';

// V11.11.0 — DECISION QUALITY (Core Portfolio). ARGUSの過去判断を後で検証する
// ための記録。履歴が浅いうちは成績として扱わない(断定しない)。記録・結果・
// オーナー行動注釈は端末内(+暗号化バックアップ)のみ — サーバーには無い。

const INTERP_TONE: Record<string, string> = {
  supported: 'var(--value-positive)', contradicted: 'var(--value-negative)',
  mixed: 'var(--amber, #fbbf24)', inconclusive: 'var(--text-faint)',
  not_applicable: 'var(--text-faint)',
};
const INTERP_JA: Record<string, string> = {
  supported: '支持', contradicted: '反証', mixed: '中間', inconclusive: '保留',
  not_applicable: '対象外',
};

export const DecisionQualityCard: React.FC = () => {
  const [, bump] = React.useReducer((x: number) => x + 1, 0);
  const s = dqSummary();
  const recent = listDQ().slice(0, 5);
  const upd = lastOutcomeUpdateAt();

  return (
    <section>
      <div className="section-head">
        <span className="section-head__title">DECISION QUALITY</span>
        <span className="section-head__count">判断の答え合わせ · 端末内のみ</span>
      </div>
      <div className="card cmd-alloc">
        <div className="cmd-alloc__note" style={{ fontSize: 12, color: 'var(--text-sub)' }}>
          ARGUSの過去判断をあとで検証するための記録です。まだ十分な履歴がないため、成績としては扱わないでください。
        </div>
        <div className="cmd-alloc__note">
          記録 {s.total}件 / 結果待ち {s.pending} / 検証可 {s.withOutcome} —
          <b style={{ color: INTERP_TONE.supported }}> 支持 {s.supported}</b> ·
          <b style={{ color: INTERP_TONE.contradicted }}> 反証 {s.contradicted}</b> ·
          中間 {s.mixed} · 保留 {s.inconclusive}
          {upd && <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>結果更新 {upd.slice(0, 16).replace('T', ' ')}</span>}
        </div>

        {recent.length === 0 ? (
          <p className="cmd-alloc__empty">
            記録はまだありません。保有数量を入力した状態でTodayを開くと、日次スナップショットと同時に自動記録されます。
          </p>
        ) : recent.map((r: DQRecord) => (
          <div key={r.id} style={{ borderTop: '1px solid var(--line)', padding: '6px 0' }}>
            <p style={{ margin: 0, fontSize: 12 }}>
              <b>{r.symbol}</b>
              <span style={{ marginLeft: 6, color: 'var(--text-sub)' }}>{r.asOf.slice(0, 10)}</span>
              <span style={{ marginLeft: 6, fontSize: 10.5, color: 'var(--text-faint)' }}>[{r.decisionContext}]</span>
              {r.supplyDemandRank && <span style={{ marginLeft: 6, fontSize: 10.5, color: 'var(--text-faint)' }}>需給{r.supplyDemandRank}</span>}
              {r.outcome?.outcomeInterpretation && (
                <b style={{ marginLeft: 6, color: INTERP_TONE[r.outcome.outcomeInterpretation] }}>
                  {INTERP_JA[r.outcome.outcomeInterpretation]}
                </b>
              )}
            </p>
            {r.outcome && (r.outcome.outcomeReturn1d != null || r.outcome.outcomeReturn5d != null) && (
              <p style={{ margin: '1px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
                その後: 1d {fmt(r.outcome.outcomeReturn1d)} / 3d {fmt(r.outcome.outcomeReturn3d)} /
                5d {fmt(r.outcome.outcomeReturn5d)} / 20d {fmt(r.outcome.outcomeReturn20d)}
              </p>
            )}
            {r.outcome?.outcomeReadableJa && (
              <p style={{ margin: '1px 0 0', fontSize: 11, color: 'var(--text-sub)' }}>{r.outcome.outcomeReadableJa}</p>
            )}
            <p style={{ margin: '2px 0 0', fontSize: 10.5 }}>
              {r.ownerAction ? (
                <span style={{ color: 'var(--text-faint)' }}>あなたの行動: {OWNER_ACTION_JA[r.ownerAction] ?? r.ownerAction}</span>
              ) : (
                <>
                  <span style={{ color: 'var(--text-faint)', marginRight: 4 }}>あなたは?</span>
                  {(['bought', 'added', 'held', 'skipped'] as const).map((a) => (
                    <button key={a} type="button" style={miniBtn}
                            onClick={() => { annotateOwnerAction(r.id, a); bump(); }}>
                      {OWNER_ACTION_JA[a]}
                    </button>
                  ))}
                </>
              )}
            </p>
          </div>
        ))}
        <p className="cmd-alloc__note" style={{ fontSize: 10 }}>
          記録・結果・あなたの行動注釈は端末内(+暗号化バックアップ)にのみ保存されます。
          売買の成績計算ではなく「ARGUSのラベルの後に何が起きたか」の記録です。
        </p>
      </div>
    </section>
  );
};

const fmt = (v: number | null | undefined): string =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;

const miniBtn: React.CSSProperties = {
  fontSize: 10, cursor: 'pointer', background: 'transparent', color: 'var(--accent)',
  border: '1px solid var(--line)', borderRadius: 5, padding: '1px 7px', marginRight: 4,
};

export default DecisionQualityCard;

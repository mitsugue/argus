import React from 'react';
import { withoutScreenNotes } from '../../lib/screenNotes';
import { useJapanMarketComparison } from '../../hooks/useJapanMarketComparison';

// Pre-registered candidate signals (2026-10-04): recorded before the outcome
// and scored by one rule. Shown outside Today's decision area; not a signal.
type Row = { candidate: string; labelJa: string; dataStatus: string; records: number; open: number; reached: number;
  broken: number; ambiguous: number; expired: number; skipped: number; medianDaysToReach: number | null;
  meanEtfReturnPct: number | null; enoughRecords: boolean };
type Candidates = { scoreboard: Row[] | null; since: string; missedSignals: Array<{ candidate: string; signalDate: string }>;
  noteJa: string; tradingSignal: false };
const STATUS_JA: Record<string, string> = { NOT_IN_PRODUCT: 'データなし',
  DATA_SHORT: '騰落レシオ 25日分待ち' };

// Owner policy 2026-10-23: the server note's 「(未検証)」 is not shown; the counts carry the record.
export function CandidateBoardView({ candidates }: { candidates: Candidates | null | undefined }) {
  if (!candidates || candidates.tradingSignal !== false || !Array.isArray(candidates.scoreboard)) return null;
  return <section aria-label="候補の事前記録">
    <div className="section-head"><span className="section-head__title">候補の事前記録</span></div>
    <div className="card cmd-alloc">
      <p className="cmd-alloc__note">{withoutScreenNotes(candidates.noteJa.replace(/[(（]未検証[)）]/g, ''))} {candidates.since}から記録</p>
      <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
        <thead><tr><th align="left">候補</th><th>記録</th><th>目標が先</th><th>崩れが先</th><th>同日両方</th><th>期限切れ</th><th>日数(中央)</th><th>ETF損益(平均)</th></tr></thead>
        <tbody>{candidates.scoreboard.map(row => <tr key={row.candidate} data-candidate={row.candidate}>
          <td>{row.candidate} {row.labelJa}{STATUS_JA[row.dataStatus] && <small style={{ display: 'block', opacity: .7 }}>{STATUS_JA[row.dataStatus]}</small>}</td>
          <td align="center">{row.records}{row.open ? `(未決${row.open})` : ''}</td>
          {row.enoughRecords
            ? <><td align="center">{row.reached}</td><td align="center">{row.broken}</td><td align="center">{row.ambiguous}</td><td align="center">{row.expired}</td></>
            : <td colSpan={4} align="center" style={{ opacity: .7 }}>件数不足{row.records ? `(${row.reached}/${row.broken}/${row.ambiguous}/${row.expired})` : ''}</td>}
          <td align="center">{row.medianDaysToReach ?? '―'}</td>
          <td align="center">{row.meanEtfReturnPct == null ? '―' : `${row.meanEtfReturnPct > 0 ? '+' : ''}${row.meanEtfReturnPct}%`}</td>
        </tr>)}</tbody>
      </table></div>
      {candidates.missedSignals.length > 0 && <p className="cmd-alloc__note">寄付前に記録できなかった合図: {candidates.missedSignals.map(m => `${m.candidate} ${m.signalDate}`).join('、')}</p>}
    </div>
  </section>;
}

export function CandidateBoard() {
  const state = useJapanMarketComparison(5);
  return <CandidateBoardView candidates={(state.levelMap as unknown as { candidates?: Candidates } | null)?.candidates} />;
}

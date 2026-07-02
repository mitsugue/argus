import React from 'react';
import { aiExplanationDisplay } from '../../lib/aiExplanationState';
import { requestExplanation, markExplainQueued, type ExplainRequestStatus } from '../../lib/queueRequests';

// ARGUS V11.5.2 — one consistent AI-explanation surface. It NEVER renders a dead button:
//  • cached      → expandable「AI解説を開く」(shows the generated text)
//  • not_generated→ clickable「理由を詳しく調べる」→ enqueues a request (no public AI start)
//  • queued/pending/… → non-clickable status chip
// After a successful click the label becomes「調査リクエスト済み」and the note explains that
// the admin/cron定期生成 will fill it in. Origin candidates / confirmed range / next-checks are
// rendered by the parent regardless (this block only owns the explanation state).

interface Props {
  explanationJa?: string | null;
  explanationStatus?: string | null;
  symbol?: string;
  market?: string;
  context: 'cause-stack' | 'mover-card' | 'downside-card' | string;
  /** compact chip styling for dense cards (downside/mover) */
  dense?: boolean;
}

export function AiExplanationBlock({ explanationJa, explanationStatus, symbol, market, context, dense }: Props) {
  const [reqState, setReqState] = React.useState<ExplainRequestStatus | 'requesting' | null>(null);
  const disp = aiExplanationDisplay(explanationJa, explanationStatus);
  const faint: React.CSSProperties = { color: 'var(--text-faint)', fontSize: dense ? 11 : 12, margin: 0 };

  // cached explanation → expandable text
  if (disp.mode === 'expandable') {
    if (dense) {
      return <p className="dic-line" style={{ margin: 0 }}><b>AI解説:</b> {explanationJa}</p>;
    }
    return (
      <details className="ai-expl" style={{ marginTop: 6 }}>
        <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--accent)' }}>{disp.labelJa}</summary>
        <p style={{ margin: '6px 0 0', fontSize: 12, lineHeight: 1.7 }}>{explanationJa}</p>
      </details>
    );
  }

  // request mode → clickable "理由を詳しく調べる" (queue only). After a click, reflect result.
  if (disp.mode === 'request') {
    if (reqState === 'queued' || reqState === 'already_queued') {
      return <p style={faint}>調査リクエスト済み — 次回の自動生成で反映されます。</p>;
    }
    if (reqState === 'cached_available') {
      return <p style={faint}>AI解説が生成されました。画面を更新すると表示されます。</p>;
    }
    if (reqState === 'rate_limited') {
      return <p style={faint}>リクエストが混み合っています。少し待って再度お試しください。</p>;
    }
    const busy = reqState === 'requesting';
    const onClick = async () => {
      if (busy || !symbol) return;
      setReqState('requesting');
      markExplainQueued(`${context}|${market}:${symbol}`);
      const res = await requestExplanation(symbol, String(market || 'JP'), context);
      setReqState(res?.status ?? 'queued');   // optimistic: assume queued if the POST returned nothing
    };
    return (
      <div style={{ marginTop: 6 }}>
        <button
          type="button"
          onClick={onClick}
          disabled={busy}
          style={{
            fontSize: dense ? 11 : 12, cursor: busy ? 'default' : 'pointer',
            background: 'transparent', color: 'var(--accent)',
            border: '1px solid var(--line)', borderRadius: 6, padding: '3px 10px',
          }}
        >{busy ? '送信中…' : disp.labelJa}</button>
        <span style={{ ...faint, display: 'block', marginTop: 4 }}>{disp.noteJa}</span>
      </div>
    );
  }

  // non-clickable status chip (queued/pending/budget_limited/disabled/error)
  return <p style={faint}>⏳ {disp.labelJa}</p>;
}

export default AiExplanationBlock;

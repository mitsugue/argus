import React from 'react';
import { aiExplanationDisplay } from '../../lib/aiExplanationState';

// Public GET-only projection. Investigation and AI execution live behind the
// authenticated operational boundary; the browser only displays cached output.
interface Props {
  explanationJa?: string | null;
  explanationStatus?: string | null;
  symbol?: string;
  market?: string;
  context: 'cause-stack' | 'mover-card' | 'downside-card' | string;
  dense?: boolean;
  labelJa?: string;
}

export function AiExplanationBlock({
  explanationJa, explanationStatus, symbol, market, context, dense,
}: Props) {
  void symbol; void market; void context;
  const display = aiExplanationDisplay(explanationJa, explanationStatus);
  if (display.mode === 'expandable') {
    return dense ? (
      <p className="dic-line" style={{ margin: 0 }}><b>AI解説:</b> {explanationJa}</p>
    ) : (
      <details className="ai-expl" style={{ marginTop: 6 }}>
        <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--accent)' }}>
          {display.labelJa}
        </summary>
        <p style={{ margin: '6px 0 0', fontSize: 12, lineHeight: 1.7 }}>{explanationJa}</p>
      </details>
    );
  }
  if (display.mode === 'chip') {
    return <span style={{ color: 'var(--text-faint)', fontSize: dense ? 10 : 11 }}>
      {display.labelJa} · バックグラウンド確認
    </span>;
  }
  return null;
}

export default AiExplanationBlock;

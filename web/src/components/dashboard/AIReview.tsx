import React from 'react';
import { useAIJudgment } from '../../hooks/useAIJudgment';
import type { AIJudgmentLabel } from '../../types/aiJudgment';

// Second-opinion layer (OpenAI primary + Gemini double-check). Calm panel — it
// never replaces the rule labels on the rows; it only adds context/caution.
// Renders nothing when the layer is disabled or has no AI content yet.

const VIEW_LABEL: Record<string, string> = {
  confirm: 'AI confirmed',
  caution: 'AI caution',
  disagree: 'AI disagrees',
  unavailable: '—',
};
const VIEW_COLOR: Record<string, string> = {
  confirm: 'var(--green)',
  caution: 'var(--amber)',
  disagree: 'var(--red)',
  unavailable: 'var(--text-muted)',
};

// Only surface rows where the AI adds something: a different final action, or a
// caution/disagreement. Confirmations and unavailable rows stay quiet.
function noteworthy(l: AIJudgmentLabel): boolean {
  return l.aiView === 'caution' || l.aiView === 'disagree' || l.aiFinalAction !== l.ruleAction;
}

export const AIReview: React.FC = () => {
  const { data, phase } = useAIJudgment();

  // Disabled / mock / connecting → render nothing (keep the page calm).
  if (!data || phase === 'disabled' || phase === 'mock' || phase === 'connecting') return null;

  const models = [data.models.primary && `GPT ${data.models.primary}`,
                  data.models.checker && `Gemini ${data.models.checker}`].filter(Boolean).join(' · ');

  // Enabled but no admin-run cached yet → calm one-line pending panel.
  if (phase === 'no_cached_result') {
    return (
      <section className="ai-review">
        <div className="ai-review__head">
          <span className="ai-review__title">AI Review</span>
          <span className="watch-status watch-status--partial">no cached result</span>
          <span className="ai-review__models">{models || 'GPT-5.5 + Gemini'}</span>
        </div>
        <div className="ai-review__summary">AI判定は未実行です(管理者による実行待ち)。ルールラベルが現在の判断です。</div>
      </section>
    );
  }

  const notes = data.labels.filter(noteworthy);
  const flags = data.globalRedFlags ?? [];
  return (
    <section className="ai-review">
      <div className="ai-review__head">
        <span className="ai-review__title">AI Review</span>
        <span className={`watch-status watch-status--${phase}`}>{phase}</span>
        <span className="ai-review__models">{models || 'second opinion'}</span>
      </div>
      {data.summaryJa && <div className="ai-review__summary">{data.summaryJa}</div>}
      {data.marketRiskJa && <div className="ai-review__risk">リスク: {data.marketRiskJa}</div>}
      {flags.length > 0 && (
        <div className="ai-review__risk">⚑ {flags.join(' / ')}</div>
      )}
      {notes.length > 0 && (
        <div className="ai-review__notes">
          {notes.map((l) => (
            <div className="ai-review__note" key={l.symbol}>
              <span className="ai-review__sym">{l.symbol}</span>
              <span className="ai-review__flow">
                {l.ruleAction}{l.aiFinalAction !== l.ruleAction ? ` → ${l.aiFinalAction}` : ''}
              </span>
              <span className="ai-review__view" style={{ color: VIEW_COLOR[l.aiView] }}>
                {VIEW_LABEL[l.aiView] ?? l.aiView}
              </span>
              <span className="ai-review__reason">{l.reasonJa}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

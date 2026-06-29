import React from 'react';
import { useAIJudgment } from '../../hooks/useAIJudgment';

// Market-level second opinion (GPT primary + Gemini check). The page-2 header shows ONLY
// the whole-market read — summary / risk / red flags. Per-stock AI notes used to be
// duplicated here; they now live on the stock cards instead (v10.176), so this stays a
// clean market overview. Renders nothing when disabled or there's no AI content yet.

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
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>市場全体の見立て</span>
          <span className="watch-status watch-status--partial">no cached result</span>
          <span className="ai-review__models">{models || 'GPT-5.5 + Gemini'}</span>
        </div>
        <div className="ai-review__summary">AI判定は未実行です(管理者による実行待ち)。ルールラベルが現在の判断です。</div>
      </section>
    );
  }

  const flags = data.globalRedFlags ?? [];
  return (
    <section className="ai-review">
      <div className="ai-review__head">
        <span className="ai-review__title">AI Review</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>市場全体の見立て(個別銘柄は各カードに表示)</span>
        <span className={`watch-status watch-status--${phase}`}>{phase}</span>
        <span className="ai-review__models">{models || 'second opinion'}</span>
      </div>
      {data.summaryJa && <div className="ai-review__summary">{data.summaryJa}</div>}
      {data.marketRiskJa && <div className="ai-review__risk">リスク: {data.marketRiskJa}</div>}
      {flags.length > 0 && (
        <div className="ai-review__risk">⚑ {flags.join(' / ')}</div>
      )}
    </section>
  );
};

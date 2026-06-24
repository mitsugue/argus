import React from 'react';
import type { DailyJudgment } from '../../types/dashboard';
import { ActionLevelCard } from '../action/ActionLevel';

export interface HeroOverlay {
  globalRegime: string;
  jpIntradayOverlay: string;   // NORMAL | CAUTION | RISK_OFF_WATCH
  holderRiskOverlay: string;   // NONE | REVIEW_REQUIRED | ...
}

interface Props {
  judgment: DailyJudgment;
  overlay?: HeroOverlay | null;
  isPartialData?: boolean;
  confidence?: number | null;   // already capped by the caller when partial
}

const fmtEnum = (s?: string): string => (s || '').replace(/_/g, ' ');
function jpTone(v: string): string {
  if (v === 'RISK_OFF_WATCH') return 'risk-off';
  if (v === 'CAUTION') return 'caution';
  return 'normal';
}
function ownerTone(v: string): string {
  if (['REVIEW_REQUIRED', 'TRIM_WATCH', 'EXIT_WATCH', 'DO_NOT_ADD', 'DEFEND'].includes(v)) return 'risk-off';
  if (v === 'WATCH' || v === 'CAUTION' || v === 'REVIEW') return 'caution';
  return 'normal';
}
// Owner field display — NO "CLEAR". Only meaningful states are shown (v10.120).
const OWNER_DISPLAY: Record<string, string> = {
  REVIEW_REQUIRED: 'REVIEW', DO_NOT_ADD: 'REVIEW', TRIM_WATCH: 'DEFEND',
  EXIT_WATCH: 'DEFEND', WATCH: 'WATCH', NOT_SYNCED: 'NOT SYNCED',
};

// COMMAND-FIRST Today hero (v10.120): the actionable command (Action Level +
// permissions) is the first thing; market context sits BELOW it; "Why" is the
// detail. No ambiguous CLEAR; raw enums (EVENT_WAIT) are formatted for display.
export const HeroCard: React.FC<Props> = ({ judgment, overlay, isPartialData, confidence }) => {
  const ownerCode = overlay?.holderRiskOverlay;
  const ownerRisk = !!(ownerCode && ownerCode !== 'NONE');
  return (
    <article className={`card card--hero hero${isPartialData ? ' hero--partial' : ''}`}>
      {/* 1. COMMAND — what am I allowed to do now? (above the fold) */}
      <ActionLevelCard
        legacyAction={judgment.overall}
        ctx={{ downsideOverride: ownerRisk ? 'REVIEW_REQUIRED' : null, materialDownside: ownerRisk }}
        risk={judgment.risk}
        dataQuality={isPartialData ? 'PARTIAL' : 'LIVE'}
        confidence={confidence}
        reason={judgment.reasons?.[0] || judgment.summary}
        next={judgment.nextCondition}
      />

      {/* 2. MARKET CONTEXT — supporting, below the command. No CLEAR; Owner only when relevant. */}
      {overlay && (
        <div className="hero__context">
          <span className="hero__context-h">Market context</span>
          <div className="hero__overlay-row">
            <div className="hero__ov">
              <span className="hero__ov-label">Global</span>
              <span className="hero__ov-value">{fmtEnum(overlay.globalRegime)}</span>
            </div>
            <div className="hero__ov">
              <span className="hero__ov-label">Japan</span>
              <span className={`hero__ov-value hero__ov-value--${jpTone(overlay.jpIntradayOverlay)}`}>{fmtEnum(overlay.jpIntradayOverlay)}</span>
            </div>
            {ownerRisk && (
              <div className="hero__ov">
                <span className="hero__ov-label">Owner</span>
                <span className={`hero__ov-value hero__ov-value--${ownerTone(ownerCode!)}`}>{OWNER_DISPLAY[ownerCode!] ?? fmtEnum(ownerCode!)}</span>
              </div>
            )}
          </div>
          {judgment.regime.length > 0 && (
            <div className="hero__regime-tags">
              {judgment.regime.map((r) => (<span className="hero__tag" key={r}>{r}</span>))}
            </div>
          )}
        </div>
      )}

      {/* 3. WHY — detail (no duplicated summary/next; those live in the command). */}
      <div className="hero__reasons">
        <span className="hero__reasons-label">Why</span>
        {judgment.reasons.map((r, i) => (
          <div className="hero__reason" key={i}>
            <span className="hero__reason-num">{String(i + 1).padStart(2, '0')}</span>
            <span>{r}</span>
          </div>
        ))}
      </div>

      <div className="hero__lists">
        <div className="hero__list-block">
          <span className="hero__list-label">Touch today</span>
          <div className="hero__list-items">
            {judgment.assetsToTouch.map((a) => <span key={a}>{a}</span>)}
          </div>
        </div>
        <div className="hero__list-block">
          <span className="hero__list-label">Avoid today</span>
          <div className="hero__list-items hero__list-items--avoid">
            {judgment.assetsToAvoid.map((a) => <span key={a}>{a}</span>)}
          </div>
        </div>
      </div>
    </article>
  );
};

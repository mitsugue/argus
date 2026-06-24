import React from 'react';
import type { DailyJudgment } from '../../types/dashboard';
import { RiskIndicator } from './RiskIndicator';
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

function jpTone(v: string): string {
  if (v === 'RISK_OFF_WATCH') return 'risk-off';
  if (v === 'CAUTION') return 'caution';
  return 'normal';
}
function ownerTone(v: string): string {
  if (['REVIEW_REQUIRED', 'TRIM_WATCH', 'EXIT_WATCH', 'DO_NOT_ADD'].includes(v)) return 'risk-off';
  if (v === 'WATCH' || v === 'CAUTION') return 'caution';
  return 'normal';
}
const OWNER_JA: Record<string, string> = {
  NONE: 'CLEAR', REVIEW_REQUIRED: 'REVIEW REQUIRED', WATCH: 'WATCH',
  DO_NOT_ADD: 'DO NOT ADD', TRIM_WATCH: 'TRIM WATCH', EXIT_WATCH: 'EXIT WATCH',
};

// The single most important card: today's overall judgment. Designed to
// answer the user's 10-second question — what is the call and why. The 3-layer
// overlay (Global / JP intraday / Owner risk) and the PARTIAL DATA badge keep a
// green global regime or a high-confidence HOLD from hiding holder risk (v10.103).
export const HeroCard: React.FC<Props> = ({ judgment, overlay, isPartialData, confidence }) => {
  const ownerRisk = !!(overlay?.holderRiskOverlay && overlay.holderRiskOverlay !== 'NONE');
  return (
    <article className={`card card--hero hero${isPartialData ? ' hero--partial' : ''}`}>
      {overlay && (
        <div className="hero__overlay-row">
          <div className="hero__ov">
            <span className="hero__ov-label">Global Regime</span>
            <span className="hero__ov-value">{overlay.globalRegime}</span>
          </div>
          <div className="hero__ov">
            <span className="hero__ov-label">Japan Intraday</span>
            <span className={`hero__ov-value hero__ov-value--${jpTone(overlay.jpIntradayOverlay)}`}>
              {overlay.jpIntradayOverlay}
            </span>
          </div>
          <div className="hero__ov">
            <span className="hero__ov-label">Owner Risk</span>
            <span className={`hero__ov-value hero__ov-value--${ownerTone(overlay.holderRiskOverlay)}`}>
              {OWNER_JA[overlay.holderRiskOverlay] ?? overlay.holderRiskOverlay}
            </span>
          </div>
        </div>
      )}
      {isPartialData && (
        <div className="hero__partial">
          ⚠ PARTIAL DATA — 情報欠損あり。完全判断ではないため、HOLDの信頼度を下げています
          {typeof confidence === 'number' ? `(信頼度上限 ${Math.round(confidence * 100)}%)` : ''}。
        </div>
      )}
      {ownerRisk && (
        <div className="hero__owner-warn">
          保有/重点監視の銘柄にダウンサイド警戒。通常のHOLDとして扱わず、下の「Downside Watch」を確認してください。
        </div>
      )}
      {/* Action Level (v10.119) — the signal word is never shown alone; explicit
          permissions block accidental new entry on a cautious "HOLD ONLY". */}
      <ActionLevelCard
        legacyAction={judgment.overall}
        ctx={{ downsideOverride: ownerRisk ? 'REVIEW_REQUIRED' : null, materialDownside: ownerRisk }}
        risk={judgment.risk}
        dataQuality={isPartialData ? 'PARTIAL' : 'LIVE'}
        reason={judgment.reasons?.[0] || judgment.summary}
        next={judgment.nextCondition}
      />
      <div className="hero__row hero__row--meta">
        <div className="hero__attr">
          <span className="hero__label">Risk Level</span>
          <span className="hero__attr-value"><RiskIndicator level={judgment.risk} /></span>
        </div>
        <div className="hero__attr">
          <span className="hero__label">Market Regime</span>
          <div className="hero__regime-tags">
            {judgment.regime.map((r) => (<span className="hero__tag" key={r}>{r}</span>))}
          </div>
        </div>
      </div>

      <p className="hero__summary">{judgment.summary}</p>

      <div className="hero__reasons">
        <span className="hero__reasons-label">Top reasons</span>
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

      <div className="hero__next">
        <span className="hero__next-label">Next condition</span>
        <span className="hero__next-text">{judgment.nextCondition}</span>
      </div>
    </article>
  );
};

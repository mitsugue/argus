import React from 'react';
import { resolveCommandSummary, SIGNALS, type SummaryInput } from '../../domain/commandSummary';
import { SIGNAL_ORDER } from '../../domain/actionLevel';
import { useLocale, t, tEn } from '../../i18n';
import './CommandSummaryCard.css';

// Existing-position permission code → Japanese (shown in ja mode; the perm row is
// explanatory, so it follows the Japanese-prose preference, v10.129).
const EXISTING_JA: Record<string, string> = {
  EXIT: '撤退', REDUCE_RISK: 'リスク削減', REASSESS: '再点検', MONITOR: '監視', MAINTAIN: '維持',
};

// One resolved command (v10.122). The PRIMARY COMMAND is the largest text; the
// abstract signal is secondary metadata; the labeled ladder lives only in help.
// English chrome (owner preference); detailed ja rationale sits in Market Context.

// v12.0.8追補: 保有リスクは市場リスクと別チップ(裸の LOW RISK が保有警報と
// 矛盾して見える問題の根治)。
type CardProps = SummaryInput & { positionRisk?: { alert: boolean; ja: string } };

export const CommandSummaryCard: React.FC<CardProps> = ({ positionRisk, ...input }) => {
  const loc = useLocale();
  const s = resolveCommandSummary(input);
  const sigColor = `var(${SIGNALS[s.signalCode].token})`;
  const blocked = SIGNALS[s.signalCode].permissions.newEntry === 'BLOCKED';
  const addBlocked = SIGNALS[s.signalCode].permissions.add === 'BLOCKED';
  const partial = ['PARTIAL', 'DELAYED', 'STALE', 'UNKNOWN', 'UNAVAILABLE'].includes(s.dataQuality);
  const ja = loc === 'ja';
  // The primary command is the punchy action keyword (NO NEW ENTRY / EXIT POSITION):
  // always English, even in Japanese mode — per the owner's preference (v10.129).
  // The signal line is already English; everything else (reason/next) follows locale.
  const primary = s.primaryCommandEn;
  const reason = ja ? s.reasonJa : s.reasonEn;
  const next = ja ? s.nextReviewJa : s.nextReviewEn;

  return (
    <div className="cs-card">
      {/* PRIMARY COMMAND — largest, highest contrast */}
      <div className="cs-primary" style={{ color: sigColor }}>{primary}</div>
      <div className="cs-signal">
        <span className="cs-sig-code">{s.signalCode.replace('_', ' ')}</span>
        {/* 7-light scale (red caution → green clear). Current segment lit; the rest
            stay color-tinted so the scale reads even when unlit. (v10.131) */}
        <span className="cs-gauge" role="img"
          aria-label={ja ? `アクション ${s.signalLevel}/7(左=注意・右=良好)` : `Action ${s.signalLevel} of 7 (left caution, right clear)`}>
          {SIGNAL_ORDER.map((code) => (
            <span key={code}
              className={`cs-gauge-seg${code === s.signalCode ? ' cs-gauge-seg--on' : ''}`}
              style={{ ['--seg' as string]: `var(${SIGNALS[code].token})` }}
              title={`${SIGNALS[code].level}. ${ja ? SIGNALS[code].labelJa : SIGNALS[code].labelEn}`} />
          ))}
        </span>
      </div>

      {/* Permissions */}
      <div className="cs-perms">
        <span className={`cs-perm cs-perm--${blocked ? 'blk' : 'ok'}`}>{t('cmd.newEntry')}: {blocked ? t('cmd.blocked') : t('cmd.allowed')}</span>
        <span className={`cs-perm cs-perm--${addBlocked ? 'blk' : 'ok'}`}>{t('cmd.add')}: {addBlocked ? t('cmd.blocked') : t('cmd.allowed')}</span>
        <span className="cs-perm cs-perm--neutral">{t('cmd.existing')}: {ja ? (EXISTING_JA[s.existingPositionCode] ?? s.existingPositionCode) : s.existingPositionCode.replace('_', ' ')}</span>
      </div>

      {/* One status line — RISK/DATA are short status keywords: English always
          (no カタカナ), even in Japanese mode (owner preference, v10.134). */}
      {/* v12.0.8追補: リスクの分離チップ — 市場リスク/保有リスク/データ品質を
          別概念として表示(保有×P1がある日に裸のLOW RISKを出さない)。 */}
      <div className="cs-status">
        <span className={`cs-stat${s.riskLevel === 'HIGH' ? ' cs-stat--bad' : ''}`}>MARKET RISK: {s.riskLevel}</span>
        <span className="cs-stat-sep">·</span>
        {positionRisk && (
          <>
            <span className={`cs-stat${positionRisk.alert ? ' cs-stat--bad' : ''}`}>POSITION RISK: {positionRisk.ja}</span>
            <span className="cs-stat-sep">·</span>
          </>
        )}
        <span className={`cs-stat${partial ? ' cs-stat--warn' : ''}`}>{s.dataQuality} {tEn('cmd.data')}</span>
      </div>
      {partial && typeof s.confidence === 'number' && (
        <p className="cs-conf">{t('cmd.confCap')} {Math.round(s.confidence * 100)}%.</p>
      )}
      {/* v12.0.8追補: なぜHOLD/買い増し禁止なのかを一行で(保有リスクがある日) */}
      {addBlocked && (
        <p className="cs-conf">
          {positionRisk?.alert
            ? '新規・買い増しは保留。保有銘柄のリスク確認が先。'
            : '新規・買い増しは保留(総合コマンド)。'}
        </p>
      )}

      {/* WHY NOW — ≤3 drivers, one line */}
      {s.drivers.length > 0 && (
        <div className="cs-block">
          <span className="cs-h">{t('cmd.whyNow')}</span>
          <span className="cs-drivers">{s.drivers.map((d) => (ja ? d.labelJa : d.labelEn)).join(' · ')}</span>
        </div>
      )}

      {/* NEXT REVIEW — one line */}
      <div className="cs-block">
        <span className="cs-h">{t('cmd.nextReview')}</span>
        <span className="cs-next">{next}</span>
      </div>

      {/* Labeled ladder + disclaimer — help only (no anonymous gauge in the card). */}
      <details className="cs-help">
        <summary>{t('cmd.whatMeans')}</summary>
        <div className="cs-ladder" aria-label="Capital deployment permission ladder">
          <div className="cs-ladder-cap">{t('cmd.ladderCap')}</div>
          {[...SIGNAL_ORDER].reverse().map((c) => (
            <div key={c} className={`cs-rung${c === s.signalCode ? ' cs-rung--cur' : ''}`}>
              <span className="cs-rung-n">{SIGNALS[c].level}</span>
              <span className="cs-rung-l" style={c === s.signalCode ? { color: `var(${SIGNALS[c].token})`, fontWeight: 700 } : undefined}>
                {ja ? SIGNALS[c].labelJa : SIGNALS[c].labelEn}
              </span>
              {c === s.signalCode && <span className="cs-rung-cur">{t('cmd.current')}</span>}
            </div>
          ))}
        </div>
        <p className="cs-disc">{t('cmd.disclaimer')}</p>
      </details>
    </div>
  );
};

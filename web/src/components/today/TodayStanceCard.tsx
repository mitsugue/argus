import React from 'react';
import type { CommandSummary } from '../../domain/commandSummary';
import { SIGNALS } from '../../domain/commandSummary';
import { SIGNAL_ORDER } from '../../domain/actionLevel';
import type { DailyJudgment } from '../../types/dashboard';
import { t } from '../../i18n';
import '../action/CommandSummaryCard.css';
import './Today.css';

// 既存ポジション許可コード→日本語(CommandSummaryCardと同一の対応表)。
const EXISTING_JA: Record<string, string> = {
  EXIT: '撤退', REDUCE_RISK: 'リスク削減', REASSESS: '再点検', MONITOR: '監視', MAINTAIN: '維持',
};

// V12.2.11 — Today's Stance: 最初の10秒で「今日の基本姿勢」だけに答えるカード。
// 主判断(既存の英語アクション語彙)+日本語1文+4チップ+主要因≤3。
// ラダー全体/permissions/PARTIAL全理由/Touch・Avoid/免責は「判断の詳細」へ。
// 判定はresolveCommandSummary(既存)の出力をそのまま表示 — ここで再計算しない。

interface Props {
  summary: CommandSummary;
  positionRisk: { alert: boolean; ja: string };
  isPartial: boolean;
  partialReasonsJa: string[];
  partialRaiseJa?: string;
  visibilityReasonJa?: string;
  coverageLineJa?: string | null;
  judgment: DailyJudgment;
  sessionStatusJa: string;
}

const RISK_WORD: Record<string, string> = { HIGH: 'HIGH', MED: 'CAUTIOUS', MEDIUM: 'CAUTIOUS', LOW: 'NORMAL' };

function confWord(c: number | null): string {
  if (c == null) return '—';
  return c >= 0.75 ? 'HIGH' : c >= 0.5 ? 'MEDIUM' : 'LOW';
}

export const TodayStanceCard: React.FC<Props> = ({
  summary: s, positionRisk, isPartial, partialReasonsJa, partialRaiseJa,
  visibilityReasonJa, coverageLineJa, judgment, sessionStatusJa,
}) => {
  const [open, setOpen] = React.useState(false);
  const sigColor = `var(${SIGNALS[s.signalCode].token})`;
  const blocked = SIGNALS[s.signalCode].permissions.newEntry === 'BLOCKED';
  const addBlocked = SIGNALS[s.signalCode].permissions.add === 'BLOCKED';
  const partial = isPartial || ['PARTIAL', 'DELAYED', 'STALE', 'UNKNOWN', 'UNAVAILABLE'].includes(s.dataQuality);
  // 欠損が実際に主判断を制限している時だけ短い結果文(チップだけでは意味が伝わらない場合)
  const partialLimits = partial && (blocked || addBlocked || (s.confidence != null && s.confidence <= 0.6));

  return (
    <article className="tcard tstance" aria-label="Today's stance">
      <div className="tcard__head">
        <span className="tcard__title">Today&rsquo;s Stance</span>
        <span className="tcard__meta">{sessionStatusJa}</span>
      </div>

      <h2 className="tstance__primary" style={{ color: sigColor }}>{s.primaryCommandEn}</h2>
      <p className="tstance__reason">{s.reasonJa}</p>

      <div className="tstance__chips" role="list">
        <span className="tstance__chip" role="listitem">CONFIDENCE
          <b>{confWord(s.confidence)}{s.confidence != null ? ` (${Math.round(s.confidence * 100)}%)` : ''}</b></span>
        <span className={`tstance__chip${partial ? ' tstance__chip--warn' : ''}`} role="listitem">DATA
          <b>{s.dataQuality}</b></span>
        <span className={`tstance__chip${s.riskLevel === 'HIGH' ? ' tstance__chip--bad' : ''}`} role="listitem">MARKET
          <b>{RISK_WORD[s.riskLevel] ?? s.riskLevel}</b></span>
        <span className={`tstance__chip${positionRisk.alert ? ' tstance__chip--bad' : ''}`} role="listitem">POSITION
          <b>{positionRisk.alert ? positionRisk.ja : 'NORMAL'}</b></span>
      </div>

      {s.drivers.length > 0 && (
        <div className="tstance__drivers" aria-label="Drivers">
          {s.drivers.slice(0, 3).map((d) => (
            <span key={d.code} className="tstance__driver">{d.labelJa}</span>
          ))}
        </div>
      )}

      {partialLimits && (
        <p className="tstance__partial">一部データ不足のため、判断の確度を通常より抑えています。</p>
      )}
      {coverageLineJa && <p className="tstance__coverage">{coverageLineJa}</p>}

      {/* ── 判断の詳細(初期は閉じる・同じ文章を繰り返さない) ── */}
      <button type="button" onClick={() => setOpen((v) => !v)}
        aria-expanded={open} aria-controls="tstance-detail"
        style={{ marginTop: 10, fontSize: 11.5, color: 'var(--accent)', background: 'transparent',
                 border: 'none', cursor: 'pointer', padding: '6px 0', minHeight: 32 }}>
        {open ? '▼ 判断の詳細を閉じる' : '▶ 判断の詳細'}
      </button>
      {open && (
        <div id="tstance-detail">
          {/* permissions(常時表示から詳細へ移動) */}
          <div className="tstance__detail-block">
            <b>PERMISSIONS</b>
            <div className="cs-perms" style={{ marginTop: 4 }}>
              <span className={`cs-perm cs-perm--${blocked ? 'blk' : 'ok'}`}>{t('cmd.newEntry')}: {blocked ? t('cmd.blocked') : t('cmd.allowed')}</span>
              <span className={`cs-perm cs-perm--${addBlocked ? 'blk' : 'ok'}`}>{t('cmd.add')}: {addBlocked ? t('cmd.blocked') : t('cmd.allowed')}</span>
              <span className="cs-perm cs-perm--neutral">{t('cmd.existing')}: {EXISTING_JA[s.existingPositionCode] ?? s.existingPositionCode.replace(/_/g, ' ')}</span>
            </div>
            {addBlocked && (
              <p style={{ margin: '4px 0 0', fontSize: 11.5 }}>
                {positionRisk.alert ? '新規・買い増しは保留。保有銘柄のリスク確認が先。' : '新規・買い増しは保留(総合コマンド)。'}
              </p>
            )}
          </div>

          {/* フルアクションラダー */}
          <div className="tstance__detail-block">
            <b>ACTION LADDER</b>
            <div className="cs-ladder" aria-label="Capital deployment permission ladder" style={{ marginTop: 4 }}>
              {[...SIGNAL_ORDER].reverse().map((c) => (
                <div key={c} className={`cs-rung${c === s.signalCode ? ' cs-rung--cur' : ''}`}>
                  <span className="cs-rung-n">{SIGNALS[c].level}</span>
                  <span className="cs-rung-l" style={c === s.signalCode ? { color: `var(${SIGNALS[c].token})`, fontWeight: 700 } : undefined}>
                    {SIGNALS[c].labelJa}
                  </span>
                  {c === s.signalCode && <span className="cs-rung-cur">{t('cmd.current')}</span>}
                </div>
              ))}
            </div>
          </div>

          {/* PARTIAL DATAの全理由+解消条件(該当時のみ) */}
          {partial && partialReasonsJa.length > 0 && (
            <div className="tstance__detail-block">
              <b>PARTIAL DATAの理由</b>
              {partialReasonsJa.slice(0, 4).map((r, idx) => (
                <span key={idx} style={{ display: 'block' }}>・{r}</span>
              ))}
              {partialRaiseJa && (
                <span style={{ display: 'block', color: 'var(--text-faint)', fontSize: 10.5 }}>
                  解消条件: {partialRaiseJa}
                </span>
              )}
            </div>
          )}
          {visibilityReasonJa && (
            <div className="tstance__detail-block">
              <b>VISIBILITY</b>
              <span style={{ display: 'block' }}>⚠ {visibilityReasonJa}</span>
            </div>
          )}

          {/* 詳細根拠(既存judgment.reasonsをそのまま) */}
          {judgment.reasons.length > 0 && (
            <div className="tstance__detail-block">
              <b>詳細(根拠)</b>
              {judgment.reasons.map((r, idx) => (
                <span key={idx} style={{ display: 'block' }}>{String(idx + 1).padStart(2, '0')} {r}</span>
              ))}
            </div>
          )}

          {/* Touch / Avoid(常時表示から詳細へ) */}
          {(judgment.assetsToTouch.length > 0 || judgment.assetsToAvoid.length > 0) && (
            <div className="tstance__detail-block">
              {judgment.assetsToTouch.length > 0 && (
                <span style={{ display: 'block' }}><b>Touch today:</b> {judgment.assetsToTouch.join(' / ')}</span>
              )}
              {judgment.assetsToAvoid.length > 0 && (
                <span style={{ display: 'block' }}><b>Avoid today:</b> {judgment.assetsToAvoid.join(' / ')}</span>
              )}
            </div>
          )}

          <p className="tstance__detail-block" style={{ fontSize: 10.5, color: 'var(--text-faint)' }}>
            {t('cmd.disclaimer')}
          </p>
        </div>
      )}
    </article>
  );
};

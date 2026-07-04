import React from 'react';
import type { AssetCardModel } from '../../domain/assetCard';
import type { SignalCode } from '../../domain/actionLevel';
import { SIGNALS } from '../../domain/actionLevel';
import { SignedValue } from '../common/SignedValue';
import { CauseStackCard } from './CauseStackCard';
import { InstitutionalView } from './InstitutionalView';
import { SignalGauge } from '../action/SignalGauge';
import './UnifiedAssetCard.css';

// One unified card per stock (v10.140). Collapsed = the 4 things you need (what's
// happening, what to do, is the cause known, last update). Expanded = ARGUS VIEW
// (the resolved view across rules + downside + flow + AI), timeline, cause, next.
// Header is "ARGUS VIEW", not "AI VIEW" — it's the synthesis, not just the LLM.

// Primary human command per signal (the punchy English keyword).
const PRIMARY_EN: Record<SignalCode, string> = {
  EXIT: 'EXIT POSITION', DEFEND: 'PROTECT CAPITAL', REVIEW: 'REASSESS NOW', PAUSE: 'NO NEW ENTRY',
  HOLD_ONLY: 'HOLD EXISTING ONLY', PREPARE: 'WAIT FOR SETUP', ENTER: 'ENTRY ALLOWED',
};
// LINKED EVENT tag — Japanese (was raw "BOJ · normal · HIGH" jargon). Event code +
// (proximity, omitted when far out) + impact, all読める日本語に.
const EVENT_CODE_JA: Record<string, string> = {
  BOJ: '日銀', FOMC: 'FOMC', PCE: '米PCE', CPI: '米CPI', PPI: '米PPI', NFP: '米雇用統計',
  JOLTS: 'JOLTS', GDP: 'GDP', AUCTION: '国債入札', EARNINGS: '決算', BOE: '英中銀', ECB: '欧中銀',
};
const ESC_JA: Record<string, string> = { 'D-7': '7日前', 'D-3': '3日前', 'D-1': '前日', D: '当日', 'D+1': '翌日' };
const IMPACT_JA: Record<string, string> = { CRITICAL: '影響:重大', HIGH: '影響:大', MEDIUM: '影響:中', LOW: '影響:小' };
const linkedTagJa = (le: { code: string; countdown: string; impact: string }) =>
  [EVENT_CODE_JA[le.code] ?? le.code, ESC_JA[le.countdown], IMPACT_JA[le.impact] ?? le.impact]
    .filter(Boolean).join(' · ');

const AI_BADGE: Record<string, { txt: string; tone: string }> = {
  fresh: { txt: 'AI FRESH', tone: 'var(--value-positive)' },
  stale: { txt: 'AI STALE', tone: 'var(--value-neutral)' },
  unavailable: { txt: 'AI UNAVAILABLE', tone: 'var(--text-muted)' },
  rule_only: { txt: 'RULE ONLY', tone: 'var(--text-muted)' },
};
const TONE: Record<string, string> = { up: 'var(--value-positive)', down: 'var(--value-negative)', flow: 'var(--event-medium)', news: 'var(--text-sub)', flat: 'var(--text-sub)' };

import type { PositionNote } from '../../domain/positionExposure';
import type { SupplyDemandSignal } from '../../hooks/useSupplyDemand';
import { RANK_TONE } from '../../hooks/useSupplyDemand';
import { decisionHistoryFor } from '../../lib/decisionQuality';
import { pastPatternLineJa } from '../../lib/learningReview';
import type { APItem } from '../../domain/actionPriority';
import { RANK_TONE as AP_TONE } from '../../domain/actionPriority';
import { READINESS_TONE } from '../../domain/positionExposure';

interface Props { card: AssetCardModel; open: boolean; onToggle: () => void;
  /** v11.8.0: device-local position/exposure note (never uploaded). */
  positionNote?: PositionNote;
  /** v11.10.0: 需給ランク(JP). */
  supplyDemand?: SupplyDemandSignal;
  /** v11.12.0: 優先度(端末内). */
  actionPriority?: APItem; }

export const UnifiedAssetCard: React.FC<Props> = ({ card: c, open, onToggle, positionNote: pn, supplyDemand: sdg, actionPriority: apx }) => {
  const sigColor = `var(${SIGNALS[c.signalCode].token})`;
  const ai = AI_BADGE[c.aiFreshness] ?? AI_BADGE.rule_only;

  return (
    <div className={`uac uac--${open ? 'open' : 'compact'}${c.held ? ' uac--held' : ''}`} style={{ ['--uac-sig' as string]: sigColor }}>
      <button className="uac-head" onClick={onToggle} aria-expanded={open}
        aria-label={`${c.symbol} ${c.name}, ${PRIMARY_EN[c.signalCode]}`}>
        <span className="uac-l1">
          {c.held && <span className="uac-held">保有</span>}
          <span className="uac-sym">{c.symbol}</span>
          <span className="uac-name">{c.name}</span>
          {c.price != null && <span className="uac-price">{c.price.toLocaleString()}</span>}
          <span className="uac-chg">{c.changePct == null ? '—' : <SignedValue value={c.changePct} suffix="%" arrow={false} />}</span>
        </span>
        <span className="uac-l2">
          <span className="uac-cmd" style={{ color: sigColor }}>{PRIMARY_EN[c.signalCode]}</span>
          <SignalGauge code={c.signalCode} />
          <span className={`uac-jsrc uac-jsrc--${c.judgmentSource}`}
                title={c.judgmentSource === 'ai' ? 'GPT+Geminiの判断(自己採点・C.A.O.S.参照)' : 'AI未更新のためルール暫定(ガードレール)'}>
            {c.judgmentSource === 'ai' ? 'AI' : 'ルール暫定'}
          </span>
        </span>
        <span className="uac-l3">{`新規${c.permNewEntry === 'BLOCKED' ? '禁止' : '可'} · 追加${c.permAdd === 'BLOCKED' ? '禁止' : '可'} · 既存は${c.permExistingJa}`}</span>
        {c.causeOneLineJa && <span className="uac-cause">{c.causeOneLineJa}</span>}
        <span className="uac-foot">
          {c.linkedEvents.map((le) => (
            <span key={le.code} className="uac-linked" title="関連イベント">{linkedTagJa(le)}</span>
          ))}
          {c.lastUpdate && <span className="uac-upd">最終更新 {c.lastUpdate}</span>}
        </span>
      </button>

      {open && (
        <div className="uac-body">
          <div className="uac-av">
            <div className="uac-av-h"><b>ARGUS VIEW</b>{c.lastUpdate && <span> · {c.lastUpdate}</span>}</div>
            <p className="uac-av-t">{c.argusViewJa}</p>
            {/* The full overall sentence, right under the stock — same depth as the
                old Downside row; nothing stripped (v10.141). */}
            {c.overallJa && c.overallJa !== c.argusViewJa && <p className="uac-overall">{c.overallJa}</p>}
            <div className="uac-av-src">
              <span>RULE + GPT-5.5 + GEMINI</span>
              <span className="uac-ai" style={{ color: ai.tone }}>· {ai.txt}</span>
            </div>
          </div>

          {c.timeline.length > 0 && (
            <div className="uac-sec">
              <div className="uac-sec-t">TIMELINE</div>
              <ul className="uac-tl">
                {c.timeline.map((t, i) => (
                  <li key={i}><span className="uac-tl-time">{t.time}</span><span style={{ color: TONE[t.tone] }}>{t.textJa}</span></li>
                ))}
              </ul>
            </div>
          )}

          {c.causeSlices.length > 0 && (
            <div className="uac-sec">
              <div className="uac-sec-t">CAUSE</div>
              <div className="uac-cz">
                {c.causeSlices.map((s) => (
                  <div className="uac-cz-row" key={s.labelJa}>
                    <span className="uac-cz-l">{s.labelJa}</span>
                    <span className="uac-cz-bar"><i style={{ width: `${s.pct}%` }} /></span>
                    <span className="uac-cz-p">{s.pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* SUPPLY / DEMAND (v11.10.0) — ランク+状態が主役。生数値は折りたたみ */}
          {sdg && (
            <div className="uac-sec">
              <div className="uac-sec-t">SUPPLY / DEMAND</div>
              <p className="uac-next" style={{ marginBottom: 2 }}>
                <b style={{ color: RANK_TONE[sdg.supplyDemandRank] }}>需給ランク {sdg.supplyDemandRank}</b>
                <span style={{ marginLeft: 6 }}>{sdg.conditionJa}</span>
                <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
                  {sdg.directnessJa} · 確度{Math.round(sdg.confidence * 100)}%
                </span>
              </p>
              <p className="uac-next" style={{ marginBottom: 2, color: 'var(--text-sub)' }}>{sdg.ownerReadableWhyJa}</p>
              <details>
                <summary style={{ cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)' }}>詳細データを見る</summary>
                <p style={{ margin: '2px 0 0', fontSize: 10.5, color: 'var(--text-faint)' }}>
                  信用買い残 {sdg.evidence.marginBuyingBalance != null ? Number(sdg.evidence.marginBuyingBalance).toLocaleString() : '—'} /
                  売り残 {sdg.evidence.marginSellingBalance != null ? Number(sdg.evidence.marginSellingBalance).toLocaleString() : '—'}
                  {sdg.evidence.lendingBorrowingRatio != null && <> / 貸借倍率 {String(sdg.evidence.lendingBorrowingRatio)}</>}
                  {sdg.evidence.daysToCover != null && <> / 買い戻し{String(sdg.evidence.daysToCover)}日分</>}
                  {' / 逆日歩 未取得'}
                </p>
              </details>
            </div>
          )}

          {/* ACTION PRIORITY (v11.12.0) — 今日の優先度(注意配分・売買指示なし) */}
          {apx && apx.priorityRank !== 'Ignore' && (
            <div className="uac-sec">
              <div className="uac-sec-t">ACTION PRIORITY</div>
              <p className="uac-next" style={{ marginBottom: 2 }}>
                <b style={{ color: AP_TONE[apx.priorityRank] }}>{apx.priorityRank} {apx.actionLabelJa}</b>
                <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>{apx.whyJa}</span>
              </p>
              <p className="uac-next" style={{ marginBottom: 0, fontSize: 10.5, color: 'var(--text-faint)' }}>
                変化条件: {apx.whatWouldChangeJa}
              </p>
            </div>
          )}

          {/* DECISION HISTORY (v11.11.0) — この銘柄への過去ラベルとその後(端末内記録) */}
          {(() => {
            const hist = decisionHistoryFor(c.symbol, 2);
            if (!hist.length) return null;
            return (
              <div className="uac-sec">
                <div className="uac-sec-t">DECISION HISTORY</div>
                {(() => { const pl = pastPatternLineJa(c.symbol);
                  return pl ? <p className="uac-next" style={{ marginBottom: 2, color: 'var(--text-faint)' }}>{pl}</p> : null; })()}
                {hist.map((h) => (
                  <p key={h.id} className="uac-next" style={{ marginBottom: 2 }}>
                    <span style={{ color: 'var(--text-faint)' }}>{h.asOf.slice(0, 10)}</span>
                    <span style={{ marginLeft: 5 }}>[{h.decisionContext}]</span>
                    {h.outcome?.outcomeReturn5d != null && (
                      <span style={{ marginLeft: 5, color: h.outcome.outcomeReturn5d >= 0 ? 'var(--value-positive)' : 'var(--value-negative)' }}>
                        5d {h.outcome.outcomeReturn5d >= 0 ? '+' : ''}{h.outcome.outcomeReturn5d.toFixed(1)}%
                      </span>
                    )}
                    {h.outcome?.outcomeReadableJa && (
                      <span style={{ marginLeft: 5, color: 'var(--text-faint)' }}>{h.outcome.outcomeReadableJa}</span>
                    )}
                    {!h.outcome?.outcomeReadableJa && <span style={{ marginLeft: 5, color: 'var(--text-faint)' }}>結果待ち</span>}
                  </p>
                ))}
              </div>
            );
          })()}

          {/* POSITION / EXPOSURE (v11.8.0) — device-local: 保有/監視・含み損益・
              比率・買い増し余地。数量未入力は未入力と正直に言う。売買指示なし。 */}
          {pn && (
            <div className="uac-sec">
              <div className="uac-sec-t">POSITION / EXPOSURE</div>
              <p className="uac-next" style={{ marginBottom: 2 }}>
                {pn.held ? (
                  <>
                    保有中{pn.quantity != null ? ` ${pn.quantity.toLocaleString()}株/口` : ''}
                    {pn.avgCost != null ? ` · 取得 ${pn.avgCost.toLocaleString()}` : ''}
                    {pn.pnlPct != null && (
                      <b style={{ marginLeft: 4, color: pn.pnlPct >= 0 ? 'var(--value-positive)' : 'var(--value-negative)' }}>
                        {pn.pnlPct >= 0 ? '+' : ''}{pn.pnlPct.toFixed(1)}%
                      </b>
                    )}
                    {pn.weightPct != null && ` · 全体の${pn.weightPct.toFixed(0)}%`}
                    {` · ${pn.themeJa}`}
                  </>
                ) : (
                  <>監視のみ(保有なし) · {pn.themeJa}</>
                )}
              </p>
              <p className="uac-next" style={{ marginBottom: 0 }}>
                <b style={{ color: READINESS_TONE[pn.readiness] }}>{pn.readinessJa}</b>
                <span style={{ marginLeft: 6, color: 'var(--text-faint)' }}>{pn.whyJa}</span>
              </p>
            </div>
          )}

          {c.nextJa && (
            <div className="uac-sec">
              <div className="uac-sec-t">NEXT</div>
              <p className="uac-next">{c.nextJa}</p>
            </div>
          )}

          {/* Named institutional views attached to THIS asset (public metadata).
              A reported view, never a trading position; renders nothing when none. */}
          <InstitutionalView symbol={c.symbol} />

          {/* Cause attribution + the "なぜ動いた? ライブで調べる" button. v10.190:
              rendered on EVERY expanded stock (owner: 全銘柄で押せるように), not just
              incident stocks. The button is always available; the full 原因スタック
              (immediate trigger / distribution / contagion / positioning / what-would-
              change) renders inside only when attribution data exists. */}
          <div className="uac-sec uac-deep">
            <CauseStackCard symbol={c.symbol} market={c.market} />
          </div>
        </div>
      )}
    </div>
  );
};

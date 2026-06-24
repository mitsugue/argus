import React from 'react';
import type { AssetCardModel } from '../../domain/assetCard';
import type { SignalCode } from '../../domain/actionLevel';
import { SIGNALS } from '../../domain/actionLevel';
import { SignedValue } from '../common/SignedValue';
import { CauseStackCard } from './CauseStackCard';
import { InstitutionalView } from './InstitutionalView';
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
const AI_BADGE: Record<string, { txt: string; tone: string }> = {
  fresh: { txt: 'AI FRESH', tone: 'var(--value-positive)' },
  stale: { txt: 'AI STALE', tone: 'var(--value-neutral)' },
  unavailable: { txt: 'AI UNAVAILABLE', tone: 'var(--text-muted)' },
  rule_only: { txt: 'RULE ONLY', tone: 'var(--text-muted)' },
};
const TONE: Record<string, string> = { up: 'var(--value-positive)', down: 'var(--value-negative)', flow: 'var(--event-medium)', news: 'var(--text-sub)', flat: 'var(--text-sub)' };

interface Props { card: AssetCardModel; open: boolean; onToggle: () => void; }

export const UnifiedAssetCard: React.FC<Props> = ({ card: c, open, onToggle }) => {
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
          <span className="uac-chg">{c.changePct == null ? '—' : <SignedValue value={c.changePct} suffix="%" arrow={false} />}</span>
        </span>
        <span className="uac-l2">
          <span className="uac-cmd" style={{ color: sigColor }}>{PRIMARY_EN[c.signalCode]}</span>
          <span className="uac-sig">· ACTION {c.signalLevel}/7</span>
        </span>
        <span className="uac-l3">{`新規${c.permNewEntry === 'BLOCKED' ? '禁止' : '可'} · 追加${c.permAdd === 'BLOCKED' ? '禁止' : '可'} · 既存は${c.permExistingJa}`}</span>
        {c.causeOneLineJa && <span className="uac-cause">{c.causeOneLineJa}</span>}
        <span className="uac-foot">
          {c.linkedEvents.map((le) => (
            <span key={le.code} className="uac-linked" title="LINKED EVENT">{le.code} · {le.countdown} · {le.impact}</span>
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

          {c.nextJa && (
            <div className="uac-sec">
              <div className="uac-sec-t">NEXT</div>
              <p className="uac-next">{c.nextJa}</p>
            </div>
          )}

          {/* Named institutional views attached to THIS asset (public metadata).
              A reported view, never a trading position; renders nothing when none. */}
          <InstitutionalView symbol={c.symbol} />

          {/* Deep cause attribution — the full 原因スタック (immediate trigger /
              distribution / contagion / positioning / what-would-change / data
              limits). Same depth as the old standalone card; nothing stripped. */}
          {c.hasIncident && (
            <div className="uac-sec uac-deep">
              <CauseStackCard symbol={c.symbol} market={c.market} />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

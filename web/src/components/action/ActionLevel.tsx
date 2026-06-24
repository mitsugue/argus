import React from 'react';
import { resolveSignal, positionInstruction, SIGNAL_ORDER, SIGNALS,
  type ResolveCtx, type SignalCode, type DataQuality, type OwnerState } from '../../domain/actionLevel';
import './ActionLevel.css';

// Action Level display (action-level-v1, v10.119). A signal word is NEVER shown
// alone — the permission matrix is mandatory. Action Level ≠ confidence ≠ regime.

const EXISTING_LABEL: Record<string, string> = {
  MAINTAIN: 'MAINTAIN', MONITOR: 'MONITOR', REASSESS: 'REASSESS', REDUCE_RISK: 'REDUCE RISK', EXIT: 'EXIT',
};

export function ActionLevelBar({ code }: { code: SignalCode }) {
  return (
    <div className="al-bar" role="img" aria-label={`Action level ${SIGNALS[code].level} of 7`}>
      {SIGNAL_ORDER.map((c) => (
        <span key={c} className={`al-seg${c === code ? ' al-seg--on' : ''}`}
          style={c === code ? { background: `var(${SIGNALS[c].token})` } : undefined}
          title={SIGNALS[c].labelEn} />
      ))}
    </div>
  );
}

interface Props {
  legacyAction: string;
  ctx?: ResolveCtx;
  risk?: string;
  dataQuality?: DataQuality;
  ownerState?: OwnerState;
  confidence?: number | null;
  reason?: string;
  next?: string;
  compact?: boolean;
}

export const ActionLevelCard: React.FC<Props> = ({
  legacyAction, ctx = {}, risk, dataQuality, ownerState = 'none', confidence, reason, next, compact,
}) => {
  const sig = resolveSignal(legacyAction, { ...ctx, dataQuality, ownerState });
  const color = `var(${sig.token})`;
  const dq = (dataQuality ?? sig.dataQuality);
  const partial = ['PARTIAL', 'DELAYED', 'STALE', 'UNKNOWN', 'UNAVAILABLE'].includes(dq);
  const blocked = sig.permissions.newEntry === 'BLOCKED';

  if (compact) {
    return (
      <span className="al-compact" style={{ color }}>
        <span className="al-compact-lvl">{sig.level}/7</span> {sig.labelEn}
        {blocked && <span className="al-compact-blk"> · ENTRY BLOCKED</span>}
      </span>
    );
  }

  return (
    <div className={`al-card${partial ? ' al-card--partial' : ''}`}>
      <div className="al-top">
        <span className="al-signal" style={{ color }}>{sig.labelEn}</span>
        <span className="al-lvl">ACTION {sig.level}/7</span>
      </div>
      {/* High-visibility permission line — the 10-second answer. */}
      <div className="al-permline">
        <span className={`al-perm al-perm--${blocked ? 'blk' : 'ok'}`}>NEW ENTRY {sig.permissions.newEntry}</span>
        <span className="al-perm-sep">·</span>
        <span className={`al-perm al-perm--${sig.permissions.add === 'ALLOWED' ? 'ok' : 'blk'}`}>ADD {sig.permissions.add}</span>
      </div>
      <ActionLevelBar code={sig.code} />
      <div className="al-grid">
        <div className="al-cell"><span className="al-k">EXISTING</span><span className="al-v">{EXISTING_LABEL[sig.permissions.existingPosition]}</span></div>
        {risk && <div className="al-cell"><span className="al-k">RISK</span><span className="al-v">{String(risk).toUpperCase()}</span></div>}
        <div className="al-cell"><span className="al-k">DATA</span><span className={`al-v${['STALE','MOCK','UNKNOWN','UNAVAILABLE'].includes(dq) ? ' al-v--blk' : ['PARTIAL','DELAYED'].includes(dq) ? ' al-v--warn' : ''}`}>{dq}</span></div>
      </div>
      {partial && (
        <p className="al-partial">
          {dq} DATA — information is incomplete; decision confidence is capped
          {typeof confidence === 'number' ? ` at ${Math.round(confidence * 100)}%` : ''}. New entries remain blocked.
        </p>
      )}
      <p className="al-pos">{positionInstruction(sig, ownerState)}</p>
      {reason && <p className="al-reason"><b>Why:</b> {reason}</p>}
      {next && <p className="al-next"><b>Next:</b> {next}</p>}
      <details className="al-details"><summary>What does Action Level mean?</summary>
        <p className="al-foot">Action Level = capital-deployment permission, not model confidence and not market regime. Decision-support only — ARGUS never places an order.</p>
      </details>
    </div>
  );
};

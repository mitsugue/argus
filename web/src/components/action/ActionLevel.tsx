import React from 'react';
import { resolveSignal, positionInstruction, SIGNAL_ORDER, SIGNALS,
  type ResolveCtx, type SignalCode, type DataQuality, type OwnerState } from '../../domain/actionLevel';
import './ActionLevel.css';

// Action Level display (action-level-v1, v10.119). A signal word is NEVER shown
// alone — the permission matrix is mandatory. Action Level ≠ confidence ≠ regime.

const PERM_LABEL: Record<string, string> = { ALLOWED: 'ALLOWED', BLOCKED: 'BLOCKED' };
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
  reason?: string;
  next?: string;
  compact?: boolean;
}

export const ActionLevelCard: React.FC<Props> = ({
  legacyAction, ctx = {}, risk, dataQuality, ownerState = 'none', reason, next, compact,
}) => {
  const sig = resolveSignal(legacyAction, { ...ctx, dataQuality, ownerState });
  const color = `var(${sig.token})`;
  const dq = (dataQuality ?? sig.dataQuality);

  if (compact) {
    return (
      <span className="al-compact" style={{ color }}>
        <span className="al-compact-lvl">{sig.level}/7</span> {sig.labelEn}
        {sig.permissions.newEntry === 'BLOCKED' && <span className="al-compact-blk"> · ENTRY BLOCKED</span>}
      </span>
    );
  }

  return (
    <div className="al-card">
      <div className="al-top">
        <span className="al-lvl">ACTION LEVEL {sig.level}/7</span>
        <span className="al-signal" style={{ color }}>{sig.labelEn}</span>
        <span className="al-signal-ja">{sig.labelJa}</span>
      </div>
      <ActionLevelBar code={sig.code} />
      <div className="al-grid">
        <div className="al-cell"><span className="al-k">NEW ENTRY</span><span className={`al-v al-v--${sig.permissions.newEntry === 'ALLOWED' ? 'ok' : 'blk'}`}>{PERM_LABEL[sig.permissions.newEntry]}</span></div>
        <div className="al-cell"><span className="al-k">ADD</span><span className={`al-v al-v--${sig.permissions.add === 'ALLOWED' ? 'ok' : 'blk'}`}>{PERM_LABEL[sig.permissions.add]}</span></div>
        <div className="al-cell"><span className="al-k">EXISTING</span><span className="al-v">{EXISTING_LABEL[sig.permissions.existingPosition]}</span></div>
        {risk && <div className="al-cell"><span className="al-k">RISK</span><span className="al-v">{String(risk).toUpperCase()}</span></div>}
        <div className="al-cell"><span className="al-k">DATA</span><span className={`al-v${['STALE','MOCK','UNKNOWN','UNAVAILABLE'].includes(dq) ? ' al-v--blk' : ['PARTIAL','DELAYED'].includes(dq) ? ' al-v--warn' : ''}`}>{dq}</span></div>
      </div>
      <p className="al-pos">{positionInstruction(sig, ownerState)}</p>
      {reason && <p className="al-reason"><b>Reason:</b> {reason}</p>}
      {next && <p className="al-next"><b>Next:</b> {next}</p>}
      <p className="al-foot">Action Level = capital-deployment permission, not confidence or market regime. Decision-support only — no orders.</p>
    </div>
  );
};

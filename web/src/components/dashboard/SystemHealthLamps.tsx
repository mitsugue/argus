import { useState } from 'react';
import { useSystemHealth, type LampStatus } from '../../hooks/useSystemHealth';
import './SystemHealthLamps.css';

// Compact green/amber/red lamp row for the metered/important systems. Small by
// design — a quiet status strip that turns RED when something overheats (e.g. the
// AI budget hard-stop fires). Dollar amounts stay in the admin Operations view.
const DOT: Record<LampStatus, string> = {
  ok: 'shl-dot--ok', warning: 'shl-dot--warn', stopped: 'shl-dot--stop', off: 'shl-dot--off',
};
const OVERALL_JA: Record<LampStatus, string> = {
  ok: '全システム正常', warning: '注意あり', stopped: '停止中の項目あり', off: '—',
};

export default function SystemHealthLamps() {
  const health = useSystemHealth();
  const [open, setOpen] = useState(false);
  if (!health) return null;

  const alerts = health.lamps.filter((l) => l.status === 'stopped' || l.status === 'warning');
  const headDot = DOT[health.overall] || DOT.off;

  return (
    <div className={`shl ${health.overall === 'stopped' ? 'shl--stop' : ''}`}>
      <button className="shl-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className={`shl-dot ${headDot}`} />
        <span className="shl-title">システム状態</span>
        <span className="shl-overall">{OVERALL_JA[health.overall]}</span>
        {alerts.length > 0 && <span className="shl-badge">{alerts.length}</span>}
        <span className="shl-caret">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="shl-grid">
          {health.lamps.map((l) => (
            <div className="shl-row" key={l.key} title={l.detailJa}>
              <span className={`shl-dot ${DOT[l.status] || DOT.off}`} />
              <span className="shl-label">{l.labelJa}</span>
              <span className="shl-detail">{l.detailJa}</span>
            </div>
          ))}
          {health.noteJa && <div className="shl-note">{health.noteJa}</div>}
        </div>
      )}
    </div>
  );
}

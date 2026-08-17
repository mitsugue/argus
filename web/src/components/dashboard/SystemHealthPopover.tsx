import { useEffect } from 'react';
import type { SystemHealth, LampStatus } from '../../hooks/useSystemHealth';
import './SystemHealthLamps.css';

// Health popover opened by tapping the A.R.G.U.S. brand. Tap the dimmed overlay
// (or Esc) to close. Presentational — the parent owns the useSystemHealth hook so
// the always-visible brand beacon and this list share one poll.
const DOT: Record<LampStatus, string> = {
  ok: 'shl-dot--ok', warning: 'shl-dot--warn', stopped: 'shl-dot--stop', off: 'shl-dot--off',
};
const OVERALL_JA: Record<LampStatus, string> = {
  ok: '全システム正常', warning: '注意あり', stopped: '停止中の項目あり', off: '—',
};

export function SystemHealthPopover({ health, onClose }: { health: SystemHealth | null; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      <div className="shl-overlay" onClick={onClose} />
      <div className="shl-popover" role="dialog" aria-label="システム状態" onClick={(e) => e.stopPropagation()}>
        <div className="shl-pop-head">
          <span className={`shl-dot ${health ? DOT[health.overall] : DOT.off}`} />
          <span className="shl-pop-title">システム状態</span>
          <span className="shl-pop-overall">{health ? OVERALL_JA[health.overall] : '取得中…'}</span>
        </div>
        {health ? (
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
        ) : (
          <div className="shl-note">取得中…</div>
        )}
      </div>
    </>
  );
}

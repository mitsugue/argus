import { TriangleStepLoader } from '../common/TriangleStepLoader';
import { usePublicDiagnostics } from '../../hooks/useSystemHealth';
import { useEffect } from 'react';
import type { SystemHealth, LampStatus } from '../../hooks/useSystemHealth';
import './SystemHealthLamps.css';

// Health popover opened by tapping the A.R.G.U.S. brand. Tap the dimmed overlay
// (or Esc) to close. Presentational — the parent owns the canonical public
// diagnostics snapshot shared by the always-visible beacon and this list.
const DOT: Record<LampStatus, string> = {
  ok: 'shl-dot--ok', warning: 'shl-dot--warn', stopped: 'shl-dot--stop', off: 'shl-dot--off',
};
const OVERALL_JA: Record<LampStatus, string> = {
  ok: '全システム正常', warning: '注意あり', stopped: '停止中の項目あり', off: '—',
};

export function SystemHealthPopover({ health, onClose }: { health: SystemHealth | null; onClose: () => void }) {
  const { loading, failed } = usePublicDiagnostics();
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
          <span className="shl-pop-overall">{health ? OVERALL_JA[health.overall] : '未取得'}</span>
        </div>
        {loading && <p className="shl-note"><TriangleStepLoader label={health ? "前回の状態を表示しながら更新しています" : "接続状況を読み込んでいます"} /></p>}
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
          !loading && <div className="shl-note">{failed ? "接続状況を取得できませんでした。Settingsから再取得できます。" : "接続状況は未取得です。"}</div>
        )}
      </div>
    </>
  );
}

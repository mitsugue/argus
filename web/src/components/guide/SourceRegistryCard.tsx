import React from 'react';
import './SourceRegistryCard.css';

interface Source {
  capability: string; provider: string; market: string; status: string;
  entitlement: string; paid: string; licence: string; notesJa: string;
}
interface Registry { confirmedLive: number; total: number; sources: Source[]; noteJa?: string }

const STATUS_JA: Record<string, string> = {
  confirmed_live: 'ライブ確認', confirmed_delayed: '遅延(確認)', partial: '一部',
  requires_test: '要検証', paid_not_enabled: '有料未契約', licence_unclear: 'ライセンス不明',
  unavailable: '未対応', missing: '未設定',
};
const STATUS_COLOR: Record<string, string> = {
  confirmed_live: 'var(--green, #34d399)', confirmed_delayed: 'var(--blue, #60a5fa)',
  partial: 'var(--amber, #fbbf24)', requires_test: 'var(--amber, #fbbf24)',
  paid_not_enabled: 'var(--text-muted, #5f6b78)', licence_unclear: 'var(--text-muted, #5f6b78)',
  unavailable: 'var(--text-faint, #5f6b78)', missing: 'var(--text-faint, #5f6b78)',
};

export const SourceRegistryCard: React.FC = () => {
  const [reg, setReg] = React.useState<Registry | null>(null);
  const [err, setErr] = React.useState(false);
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
  React.useEffect(() => {
    let alive = true;
    fetch(`${backend?.replace(/\/$/, '')}/api/argus/source-registry`)
      .then((r) => r.json()).then((d) => { if (alive) setReg(d); })
      .catch(() => { if (alive) setErr(true); });
    return () => { alive = false; };
  }, [backend]);
  if (err && !reg) return <div className="card sr-card"><div className="sr-note">取得できませんでした。</div></div>;
  if (!reg) return <div className="card sr-card"><div className="sr-note">読み込み中…</div></div>;
  return (
    <div className="card sr-card">
      <div className="sr-head">情報源 {reg.confirmedLive}/{reg.total} がライブ確認 — 「設定済み」≠「ライブ」</div>
      <div className="sr-rows">
        {reg.sources.map((s) => (
          <div className="sr-row" key={s.capability}>
            <span className="sr-dot" style={{ background: STATUS_COLOR[s.status] ?? 'var(--text-faint)' }} />
            <span className="sr-cap">{s.capability}</span>
            <span className="sr-status" style={{ color: STATUS_COLOR[s.status] ?? 'var(--text-faint)' }}>
              {STATUS_JA[s.status] ?? s.status}
            </span>
            <span className="sr-prov">{s.provider}</span>
            <span className="sr-note2">{s.notesJa}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

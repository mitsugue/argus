import '../dashboard/Dashboard.css';
import React from 'react';
import { useArgusProStatus } from '../../hooks/useArgusProStatus';

// ARGUS Pro — Free-First Research Desk Build (v11). ONE honest panel: what the Pro
// foundation actually has active vs inactive. Every line is backed by a status
// endpoint; it never claims "proven", "live", or "recording" unless the backend does.

const OK = 'var(--value-positive, #34d399)';
const WARN = 'var(--amber, #fbbf24)';
const MUTED = 'var(--text-muted)';

const CAL_STAGE_JA: Record<string, string> = {
  burn_in: 'burn-in（精度未実証）', early_signal: '初期シグナル', provisional: '暫定', regime_level: '実運用水準',
};
const DV_PHASE_JA: Record<string, { ja: string; tone: string }> = {
  not_configured: { ja: '未設定（private store無し）', tone: MUTED },
  engine_ready_no_records_yet: { ja: 'エンジン準備済・記録待ち', tone: WARN },
  shadow_recording_active: { ja: 'シャドー記録中（仮想・発注なし）', tone: OK },
  scoring_active: { ja: '採点中（仮想・発注なし）', tone: OK },
};

const Row: React.FC<{ label: string; value: React.ReactNode; tone?: string; note?: string }> =
  ({ label, value, tone, note }) => (
    <div className="mdepth__row" title={note || ''}>
      <span className="mdepth__label">{label}</span>
      <span className="mdepth__status" style={{ color: tone || 'var(--text-main)' }}>{value}</span>
    </div>
  );

export const ArgusProStatusCard: React.FC = () => {
  const { calibration, decisionValue, depthProof, sourceCoverage } = useArgusProStatus();
  const dv = decisionValue?.phase ? DV_PHASE_JA[decisionValue.phase] : undefined;
  const dp = depthProof?.summary;
  const sc = sourceCoverage?.summary;

  return (
    <section className="mdepth">
      <div className="section-head">
        <span className="section-head__title">ARGUS Pro — Free-First Research Desk Build</span>
        <span className="section-head__count">v11 foundation</span>
      </div>
      <div className="card mdepth__card">
        <p className="mdepth__lead">
          プロの調査デスク化の土台。<b>誇張しない・記録があるものだけ「稼働」と表示</b>します
          （分類であって予測・利益保証ではありません。自動売買は一切なし）。
        </p>
        <div className="mdepth__grid">
          <Row label="自己採点 Calibration v4"
               value={calibration?.isActive
                 ? `記録中 · ${CAL_STAGE_JA[calibration?.reliabilityStage || 'burn_in'] || '—'}`
                 : 'inactive（記録待ち）'}
               tone={calibration?.isActive ? WARN : MUTED}
               note={calibration?.reasonJa} />
          <Row label="意思決定価値 Decision Value"
               value={dv?.ja || '—'} tone={dv?.tone}
               note={decisionValue?.reasonJa || decisionValue?.disclaimer} />
          <Row label="市場の深さ（実証済みLIVE）"
               value={`真の深さ ${dp?.trueDepthLiveCount ?? 0} · 算出指標 ${dp?.computedIndicatorsLiveCount ?? 0}`}
               tone={(dp?.trueDepthLiveCount || 0) > 0 ? OK : MUTED}
               note={depthProof?.proofNoteJa} />
          <Row label="要契約/未接続の深さ"
               value={`要契約 ${dp?.requiresContractCount ?? 0} · 未接続 ${dp?.unavailableCount ?? 0}`}
               tone={MUTED}
               note="板/歩み値/オプションIV/貸株料は実データが無い限りunavailable/要契約。" />
          <Row label="情報源カバレッジ（品質ティア別）"
               value={`根拠可 ${sc?.canGroundJudgmentItems ?? 0} · 弱 ${sc?.weakSignalItems ?? 0}（計${sc?.totalItems ?? 0}）`}
               tone={OK}
               note="アグリゲータ/不明/SNSは単独で判断根拠にも原因確定にもできません。" />
        </div>
        <p className="mdepth__note">
          可視性ガードは警告だけでなく<b>実際に確信度を上限化し、劣化時は新規ENTERを抑制</b>します。
          Event Intelligence は EventCard v2（単一ソースを原因確定にしない・不足を必ず明示）で構成。
        </p>
      </div>
    </section>
  );
};

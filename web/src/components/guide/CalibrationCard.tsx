import React from 'react';
import { useCalibration } from '../../hooks/useCalibration';

// Owner Calibration view (Calibration Ledger v4) — read-only. Shows the versioned
// cohort universe, epoch status, multidimensional posture, and Layer 2B sync
// state. Calm + honest: this measures calibration, not guaranteed profit.
const DIM_JA: Record<string, string> = {
  equityRisk: '株式リスク', growthRisk: 'グロース', smallCapRisk: '小型株',
  creditRisk: 'クレジット', duration: 'デュレーション', volatility: 'ボラ(逆)',
  safeHaven: '安全資産', japanRisk: '日本株', fx: 'FX', liquidity: '流動性',
};

export const CalibrationCard: React.FC = () => {
  const { cohorts, epochs, posture, sync } = useCalibration();
  const sensors = cohorts?.cohorts?.regime_sensor_fixed;
  const tac = cohorts?.cohorts?.tactical_benchmark_fixed;
  const ctx = cohorts?.contextVariables?.variables;
  const fgd = cohorts?.layer1FactorGroupDemo;

  return (
    <div className="card guide-card">
      {!cohorts && <div className="guide-note">読み込み中…</div>}
      {cohorts && (
        <div className="guide-glossary">
          <div className="guide-term">
            <span className="guide-term__en">ユニバース版</span>
            <span className="guide-term__ja">
              センサー <b>{cohorts.regimeSensorUniverseVersion}</b> / タクティカル <b>{cohorts.tacticalBenchmarkVersion}</b> / ファクター <b>{cohorts.factorGroupVersion}</b>
            </span>
          </div>

          <div className="guide-term">
            <span className="guide-term__en">Layer 1 固定センサー({sensors?.count ?? 0})</span>
            <span className="guide-term__ja">{(sensors?.members ?? []).map((m: any) => m.symbol).join(' / ')}</span>
          </div>

          <div className="guide-term">
            <span className="guide-term__en">Layer 2A 固定ベンチ({tac?.count ?? 0})</span>
            <span className="guide-term__ja">
              JP: {(tac?.jp ?? []).map((m: any) => (m.symbol === '5803' ? `★${m.symbol}(${m.name})` : m.symbol)).join(' / ')}<br />
              US: {(tac?.us ?? []).map((m: any) => m.symbol).join(' / ')}
              <br /><span style={{ opacity: 0.7 }}>★5803 フジクラは固定ベンチに意図的に保持。5801/METAは所有者ウォッチリストで利用可。</span>
            </span>
          </div>

          {ctx && (
            <div className="guide-term">
              <span className="guide-term__en">文脈変数(非採点)</span>
              <span className="guide-term__ja">{Object.values(ctx).join(' / ')} — 等加重リターン採点に混ぜない。</span>
            </div>
          )}

          {fgd && fgd.flatEqualSymbolWeighted != null && (
            <div className="guide-term">
              <span className="guide-term__en">ファクター加重(実データ)</span>
              <span className="guide-term__ja">フラット平均 {fgd.flatEqualSymbolWeighted} → グループ等加重 <b>{fgd.equalGroupWeighted}</b>(相関銘柄の過大評価を回避)</span>
            </div>
          )}

          {posture?.outcome && (
            <div className="guide-term">
              <span className="guide-term__en">多次元ポスチャー</span>
              <span className="guide-term__ja">
                状態 <b>{posture.outcome.status}</b>
                {posture.outcome.status === 'partial' && '(次元不足 — SPY単独に落とさない)'}
                {posture.outcome.aggregateRiskAppetite != null && <> · リスク選好 <b>{posture.outcome.aggregateRiskAppetite}</b></>}
                {' '}<span style={{ opacity: 0.7 }}>
                  ({Object.entries(posture.outcome.dimensions || {})
                    .filter(([, v]: any) => v.score != null)
                    .map(([k, v]: any) => `${DIM_JA[k] ?? k}:${v.score}`).join(' / ') || '—'})
                </span>
              </span>
            </div>
          )}

          {epochs?.epochs && (
            <div className="guide-term">
              <span className="guide-term__en">エポック</span>
              <span className="guide-term__ja">
                {epochs.epochs.map((e) => (
                  <span key={e.epochId} style={{ display: 'block' }}>
                    {e.epochId}: {e.status}
                    {e.recordCount != null ? ` (n=${e.recordCount})` : ''}
                    {e.includeInHeadlineMetrics ? ' · headline' : ' · 除外'}
                  </span>
                ))}
              </span>
            </div>
          )}

          <div className="guide-term">
            <span className="guide-term__en">Layer 2B(あなたのwatchlist採点)</span>
            <span className="guide-term__ja">
              状態 <b>{sync?.lastStatus ?? '—'}</b> · privateストア {sync?.privateStoreConfigured ? '設定済' : '未設定'}
              <br /><span style={{ opacity: 0.7 }}>
                公開リポ対策でprivateストア設定前は採点無効(銘柄は保存しない)。保有情報は一切送受信しない。
              </span>
            </span>
          </div>

          <div className="guide-note">
            これは「校正(確率の当たり具合)」の測定であり、利益保証ではありません。固定ベンチは縦断比較用、
            所有者ウォッチリストは実用性の測定(選択バイアスあり)。現n≈133はburn-inでヘッドラインから除外。
          </div>
        </div>
      )}
    </div>
  );
};

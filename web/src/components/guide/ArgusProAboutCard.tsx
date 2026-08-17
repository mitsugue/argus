import '../dashboard/Dashboard.css';
import React from 'react';

// "ARGUS Proとは何か" (v11.0.4) — the philosophy up top of the Guide so the product is
// understood correctly: not an auto-trader; a research desk that separates evidence,
// gaps, association-vs-cause, unseen data, and its own past scoring.

const FLOW = [
  'C.A.O.S.', 'Source Tier / Rights', 'EventCard v2', 'Visibility Guard / Depth Proof',
  'GPT Judgment', 'Gemini Challenge', 'ARGUS View / TodayCall', 'Ledger / Decision Value',
  'Outcome Scoring', '次回判断の教科書',
];

const NOT = [
  '自動売買ではない',
  '利益保証ではない',
  'すべての情報が見えているわけではない',
  '単一ソースやテーマ連想を原因確定にしない',
  'Market Depthが未接続なら未接続と表示する',
  'Calibration/DVは記録がなければactiveと言わない',
];

export const ArgusProAboutCard: React.FC = () => (
  <section className="mdepth">
    <div className="section-head">
      <span className="section-head__title">ARGUS Proとは何か</span>
      <span className="section-head__count">思想</span>
    </div>
    <div className="card mdepth__card">
      <p className="mdepth__lead" style={{ lineHeight: 1.75 }}>
        ARGUS Proは、<b>自動売買アプリではありません</b>。C.A.O.S.が英語・日本語ニュース、公式開示、銘柄データ、
        価格、チャート、日証金/信用、イベント、スケジュールを収集し、それらを<b>EventCard</b>として正規化します。
        GPTが主判断を行い、Geminiが反証・確かめ算を行い、<b>ARGUS View / TodayCall / Action Label</b>として表示します。
        判断はPrediction LedgerとDecision Value Shadowに記録され、後でCalibrationとDecision Valueで採点されます。
        その結果は次回判断の教科書として使われます。ARGUS Proの価値は、<b>予言ではなく、根拠・欠落・連想と原因の区別・
        見えていない情報・過去の採点を一体化すること</b>です。
      </p>

      <div style={{ margin: '4px 0 10px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
        {FLOW.map((step, i) => (
          <React.Fragment key={step}>
            <span style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 999,
              border: '1px solid var(--line)', color: 'var(--text-sub)', whiteSpace: 'nowrap',
            }}>{step}</span>
            {i < FLOW.length - 1 && <span style={{ color: 'var(--text-faint)', fontSize: 11 }}>→</span>}
          </React.Fragment>
        ))}
      </div>

      <div>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>ARGUS Proが「やらないこと」</span>
        <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.7 }}>
          {NOT.map((n) => <li key={n}>{n}</li>)}
        </ul>
      </div>

      {/* 「判断は何を読んでいるのか」は専用カード DecisionSpineCard へ移設 (v11.2.1) */}
    </div>
  </section>
);

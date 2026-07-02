import '../dashboard/Dashboard.css';
import React from 'react';

// 判断は何を読んでいるのか (v11.2.1) — the dedicated Decision Spine explainer.
// Static + honest: describes what the judges actually read (the Evidence Pack) and the
// hard limitations. No overclaims; the flow mirrors the real pipeline.

const FLOW = [
  'C.A.O.S. / 公式ソース', 'EventCard v2', 'Evidence Pack',
  '可視性 / 深さ / 校正 / Decision Value', 'GPT判断', 'Geminiチャレンジ',
  'ARGUS View / TodayCall / Action Label', '台帳 / 採点', '次回判断の教科書',
];

const LIMITS = [
  'Evidence Packは証拠の束であり、利益保証ではない。',
  '単一ソースCAOSは原因確定ではない。',
  '公式開示は事実確認であり、価格原因確定ではない。',
  'Market Depthが欠ける場合、intraday判断の確信度は下げる。',
  'Public endpointはcached-onlyで、取得更新はscheduled/admin refreshが行う。',
];

export const DecisionSpineCard: React.FC = () => (
  <section className="mdepth">
    <div className="section-head">
      <span className="section-head__title">判断は何を読んでいるのか</span>
      <span className="section-head__count">Decision Spine</span>
    </div>
    <div className="card mdepth__card">
      <p className="mdepth__lead" style={{ lineHeight: 1.8 }}>
        ARGUS Proは、GPT/Geminiに<b>生ニュースを丸投げしません</b>。先に<b>Evidence Pack</b>を作ります。
        Evidence Packは、EventCard・公式開示・C.A.O.S.連想・source tier・market depth proof・
        Visibility Guard・Calibration status・Decision Value status・missing dataを
        <b>1銘柄ごとに束ねた判断用の証拠パック</b>です。GPTはこれを読んで主判断を出し、Geminiは反証し、
        ARGUS View / TodayCall / Action Labelに反映されます。判断には<b>evidencePackIdが残る</b>ため、
        後で「どの証拠を読んだ判断だったか」を監査できます
        （<code style={{ fontSize: 11 }}>/api/argus/evidence-pack?symbol=◯</code>）。
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
        <span className="mdepth__label" style={{ fontWeight: 600 }}>重要な制限</span>
        <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.7 }}>
          {LIMITS.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </div>
    </div>
  </section>
);

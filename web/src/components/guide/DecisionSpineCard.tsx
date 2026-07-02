import '../dashboard/Dashboard.css';
import React from 'react';

interface Durability {
  runtimeStore?: { count?: number; pathType?: string; restoreStatus?: string };
  durableStore?: { configured?: boolean; latestLedgerDate?: string | null;
                   latestCount?: number; restoreAvailable?: boolean };
  limitationsJa?: string[];
}

function useOfficialDurability(): Durability | null {
  const [d, setD] = React.useState<Durability | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    fetch(backend.replace(/\/$/, '') + '/api/argus/official-events/durability')
      .then((r) => r.json()).then((j) => { if (alive && j && j.schemaVersion) setD(j); })
      .catch(() => { /* keep null */ });
    return () => { alive = false; };
  }, []);
  return d;
}

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

export const DecisionSpineCard: React.FC = () => {
  const dur = useOfficialDurability();
  return (
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

      {/* 公式イベントはどう追跡されるのか (v11.3 official event lifecycle) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>公式イベントはどう追跡されるのか</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          TDnet/EDINET/SECなどの<b>公式開示は、一度表示して終わりではありません</b>。各開示はライフサイクルとして
          追跡されます: 開示 → EventCard → Evidence Pack → AI判断 → <b>翌日/3日/5日後の市場反応</b> →
          Decision Value採点。<b>公式開示は事実確認</b>ですが、<b>価格原因の確定には市場反応と時刻整合が必要</b>で、
          反応が観測されるまでは「引き金候補」に留まります（値動きより後の開示は引き金にしません）。
          追跡状況は <code style={{ fontSize: 11 }}>/api/argus/official-events</code> で監査できます。
        </p>
      </div>

      {/* C.A.O.S.イベント分析とは (v11.3.2 macro pre/post) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>C.A.O.S.イベント分析とは</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          NFP/CPI/FOMC/日銀などの予定イベントについて、<b>発表前にARGUSの事前シナリオを保存</b>し、
          <b>発表後に公式結果と市場反応を確認して答え合わせ</b>する機能です。これはコンセンサス予想の捏造では
          ありません — 公式コンセンサスが取れない場合は「AIシナリオ・市場の織り込み・サプライズ時の確認項目」として
          表示します。発表後は、事前に保存された見方と実際の結果を比較し、
          <b>当たり/部分的/外れ/採点不可</b>を表示します。
        </p>
        <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.7 }}>
          <li>公式結果が取れない場合は答え合わせしない（「公式結果待ち」）。</li>
          <li>事前予想が保存されていない場合は採点不可にする。</li>
          <li>AIシナリオは売買指示ではない。</li>
          <li>機関投資家の「見解」と「実際の売買」は区別する。</li>
        </ul>
      </div>

      {/* 急落・急騰の原因判定 (v11.3.3 mover cause ladder) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>急落・急騰の「原因」はどう判定しているのか</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          ARGUS Proは、急落・急騰を見つけた時に<b>原因確定と原因候補を分けて</b>表示します。
          公式開示・複数ソース・市場反応が揃えば<b>原因確認</b>、公式開示や直接ニュースは<b>有力材料</b>、
          単一ニュースや関連企業/テーマ連想は<b>候補</b>として扱います。確定できない場合でも、
          <b>何を確認済みで、何が不足し、次に何を見ればよいか</b>を表示します。
          単に「原因未確認」で終わらせないことがARGUS Proの方針です。急騰も同じ仕組みで判定し、
          材料候補があっても高値追いの推奨には変換しません。
        </p>
        <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.7 }}>
          <li>公式開示がない値動きは確定原因を出せないことがある。</li>
          <li>単一ニュースは候補止まり。連想ニュースは原因ではない。</li>
          <li>値動きより後の記事は引き金にしない。</li>
          <li>板/歩み値/borrow/options未取得時は需給原因の確度を下げる。</li>
          <li>AI解説はcached/admin-generated only(公開アクセスからのAI起動なし)。</li>
        </ul>
      </div>

      {/* 原因候補の鮮度 (v11.3.4 freshness + market confirmation v1.5) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>原因候補はどれくらい新しいのか</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          ARGUS Proでは、急落・急騰の原因を<b>一度推定して終わりにせず</b>、証拠の鮮度・次回自動確認・
          市場確認の有無を表示します。有力材料や候補は時間が経つと古くなり、再確認が必要になります
          (優先度別SLA: urgent 15分/high 30分/normal 2時間)。AI解説は公開ボタンで即時課金起動せず、
          <b>重要度の高い未解決moverだけを管理側の予算内で生成</b>し、キャッシュ表示します。
          市場確認v1.5は既存データのみ(出来高比・指数相対・同業バスケット・VWAP近似)で、
          <b>板・歩み値・貸株(borrow)ではありません</b> — 本物の板/テープ確認は将来の有料データ
          (Databento等は後日のPoC対象で、現在は未接続・未課金)。市場確認単独では原因を確定しません。
        </p>
      </div>

      {/* 公式イベント履歴は消えないのか (v11.3.1 durability) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>公式イベント履歴は消えないのか</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          公式イベントは一時キャッシュだけでなく<b>ledgerブランチへpublic-safeなメタデータとして毎営業日保存</b>され、
          再起動後も復元されます。保存するのは開示タイトル・分類・時刻・EventCard/Evidence Pack参照・市場反応・
          未確認項目のみで、<b>PDF本文・秘密情報・保有/損益は保存しません</b>。
        </p>
        {dur && (
          <p style={{ margin: '6px 0 0', color: 'var(--text-faint)', fontSize: 11, lineHeight: 1.7 }}>
            実測: 実行中ストア {dur.runtimeStore?.count ?? 0}件（{dur.runtimeStore?.pathType ?? '—'}）
            ・恒久保存 {dur.durableStore?.restoreAvailable
              ? `あり（最新 ${dur.durableStore?.latestLedgerDate ?? '—'} / ${dur.durableStore?.latestCount ?? 0}件）`
              : 'まだ（初回は16:05のワークフロー後に生成）'}
            {(dur.limitationsJa || []).length > 0 ? ` ・注: ${(dur.limitationsJa || [])[0]}` : ''}
          </p>
        )}
      </div>
    </div>
  </section>
  );
};

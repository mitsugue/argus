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

interface LearningStatus {
  status?: string; sampleStage?: string; lastBuildAt?: string | null;
  counts?: { lessons?: number; usableLessons?: number; burnInLessons?: number };
  ledger?: { restoreAvailable?: boolean; latestDate?: string | null; latestCount?: number };
  limitationsJa?: string[];
}

// v11.4.0 — live Learning Memory status (public cache-only; none/burn_in/ready).
function useLearningStatus(): LearningStatus | null {
  const [d, setD] = React.useState<LearningStatus | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend) return;
    let alive = true;
    fetch(backend.replace(/\/$/, '') + '/api/argus/learning-memory/status')
      .then((r) => r.json()).then((j) => { if (alive && j && j.schemaVersion) setD(j); })
      .catch(() => { /* keep null */ });
    return () => { alive = false; };
  }, []);
  return d;
}

const STAGE_JA: Record<string, string> = {
  none: 'まだ空(none)', burn_in: 'burn-in(サンプル不足)', early_signal: '初期シグナル',
  usable: '利用可能', mature: '成熟',
};

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
  const learn = useLearningStatus();
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

      {/* ニュース日本語化・AI解説 (v11.5.1 / v11.5.2) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>ニュースはなぜ日本語で表示されるのか</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          ARGUS Proでは、英語ニュースも主表示では日本語で読めるようにします。翻訳は公開画面の表示時にAIを
          起動するのではなく、<b>管理側の定期実行でキャッシュ</b>します。翻訳待ちのニュースが画面に出た場合、
          ARGUSはその見出しを<b>翻訳キューへ登録</b>します。公開画面ではAI翻訳を直接起動しないため、数分
          遅れることがあります。翻訳前は英語原文を主表示せず<b>「翻訳取得中」</b>と表示し、原文は「原文を見る」の
          詳細内で確認できます。次回の翻訳処理で<b>実際の日本語タイトルに置き換わります</b>。
        </p>
        <span className="mdepth__label" style={{ fontWeight: 600, display: 'block', marginTop: 10 }}>AI解説はなぜすぐ出ないことがあるのか</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          公開画面のクリックでAI検索やAI生成を<b>直接起動しません</b>。<b>「理由を詳しく調べる」</b>を押すと、
          AI検索をその場で起動するのではなく、<b>調査キューに追加</b>します。重要度・予算・重複を管理したうえで、
          管理側の定期実行が解説を生成します。生成後は同じ場所で<b>「AI解説を開く」</b>として表示されます。解説が
          まだない場合でも、<b>原因候補・確認済み範囲・次に確認すること</b>は表示されます（押しても何も起きない
          ボタンは出しません）。
        </p>
      </div>

      {/* 発表後の市場反応はどう測るのか (v11.5) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>発表後の市場反応はどう測るのか</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          ARGUS Proでは、公式結果を表示するだけでなく、発表後の<b>金利・為替・株式指数・VIX</b>などの反応を
          可能な範囲で測定します。市場反応が取得できない場合は、空欄や推測ではなく
          <b>「市場反応データ未取得」</b>と表示します。市場反応は原因確認や影響コメントの補助であり、
          それ単独で売買判断を作るものではありません。CPI/FOMC/日銀などの公式結果アダプタは段階的に拡張され、
          未実装のものは<b>not_implemented/partial</b>として正直に表示します。コンセンサス（市場予想）は捏造しません。
        </p>
        <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.7 }}>
          <li>公式結果: NFP/CPI/PPI/JOLTS(BLS)・PCE/GDP/FOMC(FRED)。日銀は公式声明URLのみ(数値未実装)。</li>
          <li>市場反応: 発表後の初回観測を基準に金利/為替/指数の変化を算出(板/歩み値ではない)。</li>
          <li>英語ニュースは管理側で日本語に翻訳してキャッシュ表示(公開GETは翻訳を起動しない)。</li>
        </ul>
      </div>

      {/* イベント表示はトップカードに統合 (v11.4.1) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>イベント表示はトップカードに統合</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          ARGUS Proでは、NFP/CPI/FOMC/日銀などの予定イベントは<b>トップのイベントカードに集約</b>されます。
          C.A.O.S.は別カードで同じ文章を繰り返すのではなく、トップカードへ<b>事前シナリオ・公式結果・答え合わせ・
          影響コメント</b>を供給する分析レイヤーとして扱います。発表後は<b>公式結果と影響を先に表示</b>し、
          事前シナリオは「当時の見方」として下段に保存します。これにより、
          <b>発表前・発表済み・結果取得中・答え合わせ済み</b>の状態を一目で区別できます。
        </p>
        <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.7 }}>
          <li>公式結果が取れない場合は「公式結果取得中」と表示（捏造しない）。</li>
          <li>事前シナリオはコンセンサスではない（ARGUS自身の読み）。</li>
          <li>C.A.O.S.の下部欄は重複表示を避け、未統合シグナルや詳細ログに限定。</li>
        </ul>
      </div>

      {/* ARGUSはどう成長するのか (v11.4.0 Learning Memory) */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <span className="mdepth__label" style={{ fontWeight: 600 }}>ARGUSはどう成長するのか</span>
        <p style={{ margin: '6px 0 0', color: 'var(--text-sub)', fontSize: 12, lineHeight: 1.8 }}>
          ARGUS Proの「成長」は、GPT/Geminiの重みを勝手に変えることでは<b>ありません</b>。公式イベント、
          C.A.O.S.イベント、急落・急騰の原因候補、Visibility Guard、Calibration、Decision Valueの結果を
          <b>public-safeなLearning Memory</b>として集計し、次回判断の証拠パックに<b>参考情報</b>として戻します。
          サンプルが少ない間はburn-inとして表示し、<b>判断を強制しません</b>。十分な件数が集まった場合だけ、
          確信度の上限・注意喚起・AIプロンプトの補助情報として使います。<b>現在の公式証拠・市場確認は
          履歴パターンより常に優先</b>し、Learning Memory単独でBUY/SELLを作ることはありません。
        </p>
        {learn && (
          <p style={{ margin: '6px 0 0', color: 'var(--text-faint)', fontSize: 11, lineHeight: 1.7 }}>
            実測: 状態 {learn.status ?? '—'} ・段階 {STAGE_JA[learn.sampleStage ?? 'none'] ?? learn.sampleStage}
            ・教訓 {learn.counts?.lessons ?? 0}件（利用可能 {learn.counts?.usableLessons ?? 0}
            {learn.counts?.burnInLessons ? ` / burn-in ${learn.counts.burnInLessons}` : ''}）
            ・最終ビルド {learn.lastBuildAt ? String(learn.lastBuildAt).slice(0, 16).replace('T', ' ') : 'まだ（初回は21:30 JSTのワークフロー後）'}
            {learn.ledger?.restoreAvailable ? ` ・恒久保存あり（最新 ${learn.ledger.latestDate ?? '—'}）` : ''}
          </p>
        )}
      </div>
    </div>
  </section>
  );
};

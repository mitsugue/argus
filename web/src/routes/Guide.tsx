import React from 'react';
import { PageShell } from './PageShell';
import { IntegrationsPanel } from '../components/guide/IntegrationsPanel';
import { BackupCard } from '../components/guide/BackupCard';
import '../components/dashboard/Dashboard.css';

// ── できること / 最近のアップデート ──────────────────────────────
// RULE (v9.10.1+): バージョンアップのたびに、この2つのリストも必ず更新する。
// アプリ内の説明書は常に「現在の実力」を正確に語ること（HANDOFF.md にも明記）。
const CAPABILITIES: { area: string; descJa: string }[] = [
  { area: '今日の判断 (Today)',
    descJa: '市場全体の姿勢(WAIT/HOLD等)・リスク・理由・触るもの/避けるもの・次に待つ条件を、金利/レジーム/イベント/価格からライブ合成。開いて10秒で今日の構えが分かる。' },
  { area: 'Watchlist',
    descJa: '銘柄を検索して追加(日本株/米国株/投信/暗号資産)・ドラッグ並べ替え。追加した銘柄には自動でライブ価格+ルールベースの行動ラベル+戦略カード(理由/次の条件/シナリオ確率)が付く。' },
  { area: '大口フロー (Big-money)',
    descJa: 'moomooブリッジ経由で大口注文の純流入率(本日累計)を取得し、戦略カードに表示。ルールエンジンの「確証シグナル」として機能 — 緩やかな下落+大口流入ならBUY DIP候補、大口流出が続けばHOLD→WAITに引き締め。' },
  { area: '価格データ',
    descJa: '日本株=J-Quants(前日終値)、米国株=Twelve Data、暗号資産=CoinGecko。moomooブリッジ稼働中は日米株がリアルタイムに自動アップグレード(途絶時は自動フォールバック)。画面を開いている間は60秒毎に自動更新。古いデータは「delayed」表示+確信度を自動で下げる。' },
  { area: 'Action Alerts (資産クラス)',
    descJa: '金(GLD)・債券(TLT)・REIT(XLRE)・仮想通貨・USD/JPY・現金・日米株の8クラスに「1クラス1判断」をライブ生成。ETFモメンタム+姿勢+金利地合いのルール合成で、追加・利確・比率調整の整理に使う。' },
  { area: 'Market Regime',
    descJa: '資金がどこへ回転しているか(ETF proxy)とレジーム(RISK_ON〜EVENT_WAIT)をルールベースで判定。行動ラベルにも反映。' },
  { area: 'Event Radar',
    descJa: 'FOMC/CPI/雇用/日銀/国債入札などの公式カレンダーをD-7→D+1でエスカレーション表示。' },
  { area: 'News Radar (原因検知)',
    descJa: '戦争・為替介入・金融破綻・緊急会見・非常事態などの危機級ヘッドライン件数を6時間窓で監視(GDELT)。テーマが増加に転じたらスマホへ通知し、朝ダイジェストにも掲載。件数ベースの参考指標と明示(事実検証はしない)。' },
  { area: 'Corporate Catalysts',
    descJa: '決算日・開示・ニュースのメタデータ(SEC EDGAR/Finnhub/J-Quants)。' },
  { area: 'What-if シミュレーション',
    descJa: '「¥Xを銘柄Yに追加したら?」— 追加後の配分変化・集中リスク警告・シナリオ別損益帯(仮定幅×ルールエンジンの確率)をWatchlist上で試算。予測ではなくシナリオ整理。端末内計算のみ。' },
  { area: '保有と評価 (Portfolio)',
    descJa: '銘柄ごとに保有数量・平均取得単価を入力すると、評価額・含み損益(¥/$別+円換算合計)・ジャンル配分をWatchlist上部に表示。保有データはこの端末のlocalStorageのみで、どこにも送信されない。' },
  { area: 'バックアップと同期',
    descJa: 'パスフレーズを1度設定すれば、毎日自動で暗号化バックアップがクラウド(GitHub)に保存される(端末上で暗号化・暗号文しか外に出ない・直近8世代を自動保持)。新端末はパスフレーズだけで復元。同じパスフレーズの端末同士はウォッチリスト・保有が自動同期(v10.10+、編集の約1分後に反映)。週1回のローカルファイル保存と手動エクスポート/復元も併用可。' },
  { area: '判断ログ (記憶)',
    descJa: '毎日の判断を端末内に記録し「昨日からの変化」と直近7日の判断を表示(この端末のみ)。' },
  { area: '予測台帳と自己採点',
    descJa: '毎営業日16:05に予測を記録し、1/3/5営業日後に実値と照合して自動採点。学習対象は3層構造(v10.9+): Layer1=固定16センサー(日本株6+米ETF7+BTC+USDJPY+VIX、局面校正の背骨)、Layer2=実戦銘柄(入替自由)、Layer3=高ノイズ実験枠(別集計)。姿勢の判断そのものもSPYの実際の動きで採点。蓄積した的中率は戦略ラベルの確信度に自動反映される(校正ループ、v10.8+)。' },
  { area: 'AI予想',
    descJa: '毎日のGPT-5.5+Gemini Proの二重チェックが各銘柄の戦略カードに「AI予想」として表示(ルール判定への同意/注意/不同意+AI提案アクション+理由)。朝ダイジェストにもAI見解1行。' },
  { area: '通知 (エージェント)',
    descJa: '日本株の寄り前8:30と米国株の寄り前22:00にダイジェスト、市場時間中(7〜24時)は「姿勢の変化・イベント接近・ボラティリティの圏域上昇/VIX急騰(固定の閾値ではなく、速度と自身の60日分布で文脈判定)・信用ストレス」の時だけアラートをスマホへpush(ntfy設定時)。通知タップでアプリが開く。' },
  { area: 'AI',
    descJa: 'GPT-5.5 Pro Handoff=手動コピペで無料の深掘り相談。自動AI判断(GPT-5.5+Gemini二重チェック)=管理者実行・キャッシュ閲覧のみ公開。実行結果は台帳に永続化され、サーバー再起動後も直近の見解を自動復元(実行時刻スタンプ付き)。下のAPI statusに現在の状態が常に出る。' },
  { area: '正直さの原則',
    descJa: '全データに live/partial/mock/delayed を明示。ARGUSは予測ではなく「現在の分類」。シナリオ確率は予言ではなく状況整理。' },
];

const RECENT_UPDATES: [string, string][] = [
  ['v10.10.0', '端末間の自動同期(sync-v1) — 同じパスフレーズでクラウドバックアップを有効にした端末同士で、ウォッチリスト・保有・判断ログが自動同期(編集の約1分後に他端末へ反映・暗号文のみ送受信)。同時編集は新しい方が勝つ方式'],
  ['v10.9.0', '学習対象を3層構造に再編(ledger-v3) — Layer1=固定16センサー(TOPIX/日経/三菱UFJ/トヨタ/三菱商事/NTT/SPY/QQQ/SMH/IWM/TLT/HYG/GLD/BTC/USDJPY/VIX)、Layer2=実戦銘柄、Layer3=高ノイズ実験枠(別集計)。採点は1/3/5営業日の3ホライズン・資産種別ごとのσ単位バンドに'],
  ['v10.8.1', '行動ラベルの自動復帰 — サーバーがスリープ明けで初回読込に失敗しても、60秒毎の静かな再取得で温まり次第ライブ判定へ自動復帰(タブに戻った瞬間も即更新)。リロード不要に'],
  ['v10.8.0', '校正ループ始動(calibration-v1) — 予測台帳の採点成績(姿勢別の的中率)が戦略ラベルの確信度に自動反映。証拠が3日分(33件)貯まるまでは中立、的中率60%超で僅かに強気・40%未満で弱気に。根拠は資産戦略ページに常時表示'],
  ['v10.7.0', 'AI見解が消えない化+通知の定時配信 — AI判断を台帳に永続化しサーバー再起動後も自動復元(「not run yet」解消)。朝/夜ダイジェストはGitHubの遅延に関係なく08:30/22:00ちょうどに配信。通知タップでアプリに飛ばずに全文が読めるように'],
  ['v10.6.1', '株価の自動更新 — 日米ウォッチリストが画面を開いたまま60秒毎に静かに最新化(moomooブリッジの更新周期と同期)。タブに戻った瞬間も即更新。リロード不要に'],
  ['v10.6.0', 'News Radar — ブラックスワンの「原因」検知(戦争/介入/金融破綻/緊急会見/非常事態のヘッドライン監視)。Event Radarに表示・テーマ急増でスマホ通知・朝ダイジェストにも掲載'],
  ['v10.5.0', '台帳の学習対象を拡張(ledger-v2) — 9資産クラス+BTC/ETHのシナリオ採点と「姿勢の判断そのもの」の採点(RISK_OFFと言った日に市場は本当に下げたか)を毎日記録。局面×クラスの校正データが蓄積開始'],
];

// 用語一覧 — English chrome term → Japanese meaning.
const GLOSSARY: [string, string][] = [
  ['Today', '今日の判断'],
  ['Action Alerts', '行動アラート'],
  ['Market Regime', '市場レジーム'],
  ['Event Radar', 'イベント監視'],
  ['Watchlist', '監視リスト'],
  ['Core Portfolio', '長期コア資産'],
  ['Capital Rotation', '資金回転'],
  ['Regime Matrix', 'レジーム行列'],
  ['Top Rotations', '注目資金移動'],
  ['Action Label', '行動ラベル'],
  ['Risk', 'リスク'],
  ['Confidence', '確信度'],
  ['Catalyst', '材料・きっかけ'],
  ['Scenario Probabilities', 'シナリオ確率'],
  ['Rescan', '再スキャン'],
  ['Pro Handoff', 'Pro確認用コピー'],
  ['AI Review', 'AIレビュー'],
  ['WAIT', '待機'],
  ['HOLD', '保有継続'],
  ['WAIT FOR PULLBACK', '押し目待ち'],
  ['BUY DIP', '下落時の買い候補'],
  ['ADD', '追加'],
  ['TRIM', '一部利確 / 縮小'],
  ['EXIT', '撤退'],
  ['CONTINUE', '継続'],
  ['GRADUAL ADD', '段階的追加'],
  ['DEFER LUMP SUM', '一括投入見送り'],
  ['NO SELL ACTION', '売却不要'],
  ['Prediction Ledger', '予測台帳 — 毎日の予測をGitHubに記録し翌日採点する仕組み'],
  ['的中率 (Hit rate)', 'シナリオ分布で最有力とした結果が実際に起きた割合'],
  ['Brier score', '確率予測の校正度(0〜2、低いほど良い。0.6前後=あてずっぽう同等、それ未満なら情報がある)'],
];

const HOWTO: string[] = [
  'まず Today で今日の姿勢(市場全体のスタンス)を確認します。',
  'Watchlist で個別銘柄の行動ラベルを見ます。行をタップすると戦略・理由・次に待つ条件が開きます。',
  'Event Radar で重要イベント(FOMC・CPI・決算・国債入札など)の接近を確認します。',
  'Action label は売買の指示ではなく、判断の整理です。迷うときは WAIT / HOLD 寄りに考えます。',
  'Pro Handoff は GPT-5.5 Pro に手動で深く相談したいときにプロンプトをコピーします(自動課金なし)。',
  'Scenario probabilities は予言ではなく、現在のデータに基づく短期のリスク配分です。',
  'データが partial / mock のときは、その銘柄の判断は弱めに受け取ってください。',
  '自己採点(的中率・Brier)は最低30営業日貯まるまで参考程度に。AI見解は毎日16:05の実行スナップショットで、常時最新ではありません(カードに実行時刻を表示)。',
  '長期コア資産(Core)は短期の値動きで売買せず、積立方針の維持が基本です。',
];

export const Guide: React.FC = () => {
  return (
    <PageShell title="Glossary / Guide" subtitle="ARGUS でできること・用語一覧・使い方(日本語ガイド)。">
      <section>
        <div className="section-head">
          <span className="section-head__title">ARGUS でできること</span>
          <span className="section-head__count">v{__APP_VERSION__} 時点</span>
        </div>
        <div className="card guide-card">
          <div className="guide-caps">
            {CAPABILITIES.map((c) => (
              <div className="guide-cap" key={c.area}>
                <span className="guide-cap__area">{c.area}</span>
                <span className="guide-cap__desc">{c.descJa}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">最近のアップデート</span>
          <span className="section-head__count">{RECENT_UPDATES.length} releases</span>
        </div>
        <div className="card guide-card">
          <div className="guide-caps">
            {RECENT_UPDATES.map(([v, d]) => (
              <div className="guide-cap" key={v}>
                <span className="guide-cap__area guide-cap__area--mono">{v}</span>
                <span className="guide-cap__desc">{d}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="section-head"><span className="section-head__title">用語一覧</span></div>
        <div className="card guide-card">
          <div className="guide-glossary">
            {GLOSSARY.map(([en, ja]) => (
              <div className="guide-term" key={en}>
                <span className="guide-term__en">{en}</span>
                <span className="guide-term__ja">{ja}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">バックアップ (端末データ)</span>
          <span className="section-head__count">エクスポート / 復元</span>
        </div>
        <BackupCard />
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">API / Integration status</span>
          <span className="section-head__count">設定・稼働状況</span>
        </div>
        <IntegrationsPanel />
      </section>

      <section>
        <div className="section-head"><span className="section-head__title">ARGUS の使い方</span></div>
        <div className="card guide-card">
          <ol className="guide-howto">
            {HOWTO.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
          <p className="guide-note">
            ARGUS は予測エンジンではありません。現在の市場・銘柄の状況を「行動カテゴリ」に整理して、
            今日の判断・リスク・理由・触るもの・避けるもの・待つものを示す投資コマンドセンターです。
          </p>
        </div>
      </section>
    </PageShell>
  );
};

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
    descJa: '銘柄を検索して追加(日本株/米国株/投信/暗号資産)・ドラッグ並べ替え。追加した銘柄には自動でライブ価格+ルールベースの行動ラベル+戦略カード(理由/次の条件/シナリオ確率)が付く。日米株はカード内の「⚡エントリー診断」で入りの瞬間判断(トレンド/過熱/大口フロー/イベント)を即取得(v10.15+)。' },
  { area: '大口フロー (Big-money)',
    descJa: 'moomooブリッジ経由で大口注文の純流入率(本日累計)を取得し、戦略カードに表示。ルールエンジンの「確証シグナル」として機能 — 緩やかな下落+大口流入ならBUY DIP候補、大口流出が続けばHOLD→WAITに引き締め。' },
  { area: '価格データ',
    descJa: '日本株=J-Quants(前日終値)、米国株=Twelve Data、暗号資産=CoinGecko。moomooブリッジ稼働中は日米株がリアルタイムに自動アップグレード(途絶時は自動フォールバック)。画面を開いている間は15秒毎に自動更新(v10.10.1+)。古いデータは「delayed」表示+確信度を自動で下げる。' },
  { area: '資産クラス司令室 (Core Portfolio)',
    descJa: '①あなたの実配分(円換算・含み損益・ジャンル別バー) ②金/債券/REIT/仮想通貨/USDJPY/現金/日米株の8クラスのライブ判断 ③姿勢連動の積立方針を1ページに統合(v10.13+)。比率調整の意思決定はここで。8クラス判断はAction Alertsページにも表示。' },
  { area: 'Market Regime',
    descJa: '資金がどこへ回転しているか(ETF proxy)とレジーム(RISK_ON〜EVENT_WAIT)をルールベースで判定。行動ラベルにも反映。' },
  { area: 'Event Radar',
    descJa: 'FOMC/CPI/雇用/日銀/国債入札などの公式カレンダーをD-7→D+1でエスカレーション表示。' },
  { area: 'News Radar (原因検知)',
    descJa: '戦争・為替介入・金融破綻・緊急会見・非常事態などの危機級ヘッドライン件数を6時間窓で監視(GDELT)。テーマが増加に転じたらスマホへ通知し、朝ダイジェストにも掲載。さらにTodayにはFinnhubの市場速報フィード(ECB/Fed/介入など⚡強調、v10.12+)。いずれも参考情報で事実検証はしない。' },
  { area: 'What-if シミュレーション',
    descJa: '「¥Xを銘柄Yに追加したら?」— 追加後の配分変化・集中リスク警告・シナリオ別損益帯(仮定幅×ルールエンジンの確率)をWatchlist上で試算。予測ではなくシナリオ整理。端末内計算のみ。' },
  { area: '保有と評価 (Portfolio)',
    descJa: '銘柄ごとに保有数量・平均取得単価を入力すると、評価額・含み損益(¥/$別+円換算合計)・ジャンル配分をWatchlist上部に表示。保有データはこの端末のlocalStorageのみで、どこにも送信されない。' },
  { area: 'バックアップと同期',
    descJa: 'パスフレーズを1度設定すれば、毎日自動で暗号化バックアップがクラウド(GitHub)に保存される(端末上で暗号化・暗号文しか外に出ない・直近8世代を自動保持)。新端末はパスフレーズだけで復元。同じパスフレーズの端末同士はウォッチリスト・保有が自動同期(v10.10+、編集の約1分後に反映)。週1回のローカルファイル保存と手動エクスポート/復元も併用可。' },
  { area: '判断ログ (記憶)',
    descJa: '毎日の判断を端末内に記録し「昨日からの変化」と直近7日の判断を表示(この端末のみ)。' },
  { area: '予測台帳と自己採点',
    descJa: '毎営業日16:05に予測を記録し、1/3/5営業日後に実値と照合して自動採点。学習対象は3層構造(v10.9+): Layer1=固定16センサー(日本株6+米ETF7+BTC+USDJPY+VIX、局面校正の背骨)、Layer2=実戦銘柄(入替自由)、Layer3=高ノイズ実験枠(別集計)。姿勢の判断そのものもSPYの実際の動きで採点。蓄積した的中率は戦略ラベルの確信度に自動反映される(校正ループ、v10.8+)。さらに14:30の「引けピン」が同日15:30終値で即日採点される第二の台帳も稼働(v10.11+)。' },
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
  ['v10.35.0', '運用の正直さ強化(GPT Proレビュー反映) — ①自己採点に「n件は相関銘柄を含み独立試行ではない/実効サンプルは小さめ」の注記を追加 ②説明書(AI Review)の古い記述を修正(「成績追跡なし」→台帳で稼働中、「AI判定はpending」の矛盾を解消) ③常時ゼロを返していた/calibrationエンドポイントを本物の台帳集計に接続。地合い安定化(v10.34)も反映'],
  ['v10.34.0', '地合い判定(Market Regime/Risk Level)が読み込むたびに揺れる問題を安定化 — 8本のETFの一部が取得失敗(Twelve Data無料枠の制限)すると残りだけで採点して評価が振れていました。直近の「全データ揃った評価」を保持し、不足時はそれを表示(最大24h・保持中は明記)。データが全部揃うと自動更新。コロコロ変わるのはノイズで、地合い自体が変わったわけではありません'],
  ['v10.33.0', 'バージョン表記が10.30で止まっていた不具合を修正 — package.jsonのバージョン更新が無言で失敗しており、v10.31〜v10.32.1の機能(スクロールのヌルヌル化・PWA自動更新・バックアップDLボタン・物語化診断など)は全て稼働していたのに表記だけ10.30のままでした。今後はバージョンが正しく上がります'],
  ['v10.32.0', 'ページ送りのガタつき解消(ドラッグをReact再描画ではなくDOM直接操作に=ヌルヌル)+ 新バージョンが自動で届くように(60秒ごとに更新確認、これまではアプリを完全終了するまで反映されなかった)。AI reviewに「評価用バックアップDL」ボタンを追加(初回読み込み時の自動DLは廃止)。AI連携ツール(アプリ仕様コピー/各銘柄🧠AI相談/全体相談/バックアップ)の違いを明記'],
  ['v10.31.0', 'ページ送りをさらに重く — トリガーまでの引っ張り距離を延長(誤操作ほぼ不可)。次ページは画面下/上から大きくスライドインする連続的な動きに(パッと出る→重くせり上がる/降りてくる)'],
  ['v10.30.0', 'エントリー診断を「物語化」+ AI相談ボタンを1本に統合 — ⚡診断が一言コール(買い場/様子見/見送り)とモート根拠の2〜3文(地合い・大口フロー・日証金/空売り・この局面でのARGUS的中率)を出すように。GPT相談とGemini OSINTの2ボタンは「🧠 AI相談」1本に統合し、中身をニュースではなくフロー・信用・校正実績を先頭に置いたモート起点プロンプトへ刷新'],
  ['v10.29.0', 'ページ送りを「Clear」アプリ風の重い操作感に — 指で引っ張るとページ本体が指に追従しつつ強く抵抗(指数ダンピング)。かなり引っ張らないと次に行かず、越えると次ページがぬるんと(オーバーシュート付きで)現れる。誤操作はほぼ不可能'],
  ['v10.19.0', '⚡診断に日証金(貸借残)を統合 — 無料の公開データ(taisyaku.jp)から日証金倍率(融資残÷貸株残)を毎日取得。売り長(倍率<1)=踏み上げの燃料、買い長(高倍率)=戻り売り圧力。本日の新規/返済の方向も判定。「日証金は?」の問いに正式対応(貸借銘柄のみ・非掲載銘柄は正直に未取得表示)'],
  ['v10.15.1', 'スクロールでページ送り — 画面の一番下からさらに強く下へ引っ張る(またはホイールを回す)と次のページへ移動。誤作動防止のしきい値+「↓さらに引っ張って◯◯へ」のインジケータ付き'],
  ['v10.16.0', '⚡エントリー診断をフル装備化(v2) — 市場レジーム・VIX急騰・指数(TOPIX)との相対力・決算接近・AI二重チェックの見解を診断に統合。ARGUSの全能力が⚡ボタン1つに集約。根拠は全件明示・隠れた重みなし。次は日証金/信用残と、台帳採点による確率の校正(Phase 2/3)'],
  ['v10.12.2', '銘柄ごとの「🤖 Pro相談」ボタン — 戦略カードを開くと、その銘柄の判断・理由・フロー・AI見解をまとめたGPT-5.5 Pro相談用プロンプトをワンタップでコピー。通知タイトルに配信時刻(JST)を明記(iPhoneで「昨日」としか出ない問題の解消)'],
  ['v10.8.0', '校正ループ始動(calibration-v1) — 予測台帳の採点成績(姿勢別の的中率)が戦略ラベルの確信度に自動反映。証拠が3日分(33件)貯まるまでは中立、的中率60%超で僅かに強気・40%未満で弱気に。根拠は資産戦略ページに常時表示'],
];

// 用語一覧 — English chrome term → Japanese meaning.
const GLOSSARY: [string, string][] = [
  ['Today', '今日の判断'],
  ['Action Alerts', '行動アラート'],
  ['Market Regime', '市場レジーム'],
  ['Event Radar', 'イベント監視'],
  ['Watchlist', '監視リスト'],
  ['Core Portfolio', '資産クラス司令室 — 配分の現在地とクラス別の構え'],
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

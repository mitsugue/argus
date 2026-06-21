import React from 'react';
import { PageShell } from './PageShell';
import { IntegrationsPanel } from '../components/guide/IntegrationsPanel';
import { BackupCard } from '../components/guide/BackupCard';
import { LedgerHealthCard } from '../components/guide/LedgerHealthCard';
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
  ['v10.45.0', 'Action Alertsページに24/7イベント+調査ドシエを統合表示 — Todayだけでなく専用ページでも、検知中のS高/急変/暗号資産ショックとその決定論ドシエ(原因/シナリオ/罠/反証)を展開して読めるように'],
  ['v10.44.0', 'ブリッジ→サーバーの通信にHMAC署名+リプレイ防止を追加(セキュリティ強化) — 価格push に時刻+nonce+HMAC-SHA256署名を要求でき、管理トークンが漏れても偽造・再送をブロック。後方互換(秘密鍵を設定するまで現状動作のまま壊れない)。EC2側に署名コードを足し、両側に共有鍵を設定すると有効化'],
  ['v10.43.0', '暗号資産の24時間ショック検知を追加 — 「24時間監視」を本物に。CoinGeckoの24h変動から±5%でショック・±10%で重大を検知し、深夜・週末も約30分間隔でスマホへ通知(株式は市場時間中のみだが暗号資産は常時)。決定論・LLMなし・新しい秘密設定不要。BTC/ETHの急変を寝ていても掴めます'],
  ['v10.42.0', '24/7イベントの耐久化(Lean) — 検知したイベント/改訂/ドシエをledgerブランチにスナップショット永続。Render再起動・デプロイでも復元(起動時にブランチから読み戻し)。DynamoDB等の新規AWSは使わず既存パターンを再利用・あなたの追加設定は不要。イベント履歴はブランチ上で監査可能。最良努力の粒度(スナップショット間で消えた分は次pushで再検知)'],
  ['v10.41.1', '調査ドシエの誠実性ハードニング(GPT Proレビュー反映) — ①事実/観測/報道/派生指標/推論/未確認を別バケットに分離(フロー推定やニュース見出しを「確認済み事実」に混ぜない)②原因の重みを情報源の格付けで判定(一般ニュースは公式材料にしない)③確信度バグ修正(UNCONFIRMEDを信号と誤カウントしていた)を「証拠カバレッジ(未較正)」に④全確率を検証・正規化(NaN/不正→unknown=1)⑤証拠に真の時刻/ハッシュを保持⑥イベント時点スナップショット+版/ハッシュでキャッシュ無効化⑦GETのHTTPコード正常化(失敗=500)⑧市場範囲の基準をMarket Regime SPYに⑨通知テストを管理者認証必須に(公開ボタン廃止)⑩説明書の誤り訂正(Action Alertsはmockでなくlive/partial・Geminiモデル名のハードコード除去)'],
  ['v10.41.0', 'Evidence-First 調査ドシエ(決定論・AIなし)を搭載 — 24/7監視がイベントを検知すると、既存システム(フロー推定・日証金/空売り・ニュース・地合い)だけで「何が起きた/推定原因/フロー/市場全体か個別か/罠リスク/次セッションのシナリオ/無効化条件/欠損データ/反証」を組み立て、Todayのイベントをタップで展開表示。全確率は合計100%・証拠ID付き・売買指示は一切出さない。AIによる深掘り(Gear2/3)は将来オプション'],
  ['v10.40.0', 'GPT Proレビューの正直性/安全修正を反映 — ①「特別気配」表記を廃止し「S高/S安 接近(値幅上限/下限)」に(取引所の特別気配フィールドは持っていないため正確な呼称に)②東京の後場判定を15:25まで(引け前は15:25-15:30)に修正③通知テストに1日上限(6回)を追加し悪用を遮断④市場時間外の文言を正直化(深夜/週末の常時監視は今後)。巨大なResearch Intelligence本体は段階導入を提案中'],
  ['v10.39.0', '24時間監視の心臓部(Phase 2)を搭載 — ブリッジの既存15秒pushをサーバー側で常時解析し、S高/S安(TSE制限値幅テーブルで正確に)・急騰/急落・大口フロー異常を検知。重要な変化(sev4+)だけスマホへ通知。セッション対応で薄商いの誤検知を防止。LLMなしの決定論Gear0/1のみ稼働(PTS/L2/VWAPは未対応・capability-gated)。Renderに NTFY_TOPIC を設定すれば通知が飛びます'],
  ['v10.38.0', '安全網: 本番スモークテストを自動化 — デプロイ毎に全主要エンドポイントを「200だけでなくフィールド単位」で自動検証し、壊れたら数分でスマホ通知。/healthzでビルドSHAを公開しデプロイ済みコミットを確認。今後のリファクタ(scanner分割の続き等)を安全に進めるための土台'],
  ['v10.37.0', 'AI判定の「遅延」表示を正直化(土日や祝日で前営業日のままなのは正常 — 予定された実行を取りこぼした時だけ「遅延」、それ以外は最新営業日として扱う)。内部整理: entry-scoutの純粋スコアリング層をargus_rules.pyへ分離(scanner.py 6757→6270行・挙動不変・92テスト緑)。Dynamic Workflows前の段階的リファクタ第1歩'],
  ['v10.36.0', 'Operational Truth 3点 — ①moomoo価格に鮮度/権限を明示(配信は約15秒毎だが元データがrealtimeか15分遅延か未確認の間は「未確認」と正直表示、realtimeと断定しない)②AI判定をfresh/保持中/古いで区別表示(モデル名・次回実行・「ルールが主・AIは第二意見」を明記。30分TTL失効=判定消滅ではない)③Guideに「Ledger Health」追加 — 予測台帳/Scout/引けピン/AIの稼働状況(稼働中/遅延/蓄積前・最終記録・次回実行・トリガー)を一画面で確認'],
  ['v10.35.0', '運用の正直さ強化(GPT Proレビュー反映) — ①自己採点に「n件は相関銘柄を含み独立試行ではない/実効サンプルは小さめ」の注記を追加 ②説明書(AI Review)の古い記述を修正(「成績追跡なし」→台帳で稼働中、「AI判定はpending」の矛盾を解消) ③常時ゼロを返していた/calibrationエンドポイントを本物の台帳集計に接続。地合い安定化(v10.34)も反映'],
  ['v10.33.0', 'バージョン表記が10.30で止まっていた不具合を修正 — package.jsonのバージョン更新が無言で失敗しており、v10.31〜v10.32.1の機能(スクロールのヌルヌル化・PWA自動更新・バックアップDLボタン・物語化診断など)は全て稼働していたのに表記だけ10.30のままでした。今後はバージョンが正しく上がります'],
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
          <span className="section-head__title">Ledger Health (自己採点ループ)</span>
          <span className="section-head__count">稼働状況</span>
        </div>
        <LedgerHealthCard />
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

import React from 'react';
import { PageShell } from './PageShell';
import { IntegrationsPanel } from '../components/guide/IntegrationsPanel';
import { BackupCard } from '../components/guide/BackupCard';
import { LedgerHealthCard } from '../components/guide/LedgerHealthCard';
import { SourceRegistryCard } from '../components/guide/SourceRegistryCard';
import '../components/dashboard/Dashboard.css';

// ── できること / 最近のアップデート ──────────────────────────────
// RULE (v9.10.1+): バージョンアップのたびに、この2つのリストも必ず更新する。
// アプリ内の説明書は常に「現在の実力」を正確に語ること（HANDOFF.md にも明記）。
// Page-by-page "how to use" — in the same order as the left nav, so the guide
// matches how you actually move through the app. Kept in sync with every update.
const PAGE_GUIDE: { page: string; descJa: string }[] = [
  { page: '共通ヘッダー / ナビ',
    descJa: '左上の「A.R.G.U.S.」をタップ → システム状態のポップアップ(AI予算・各データ源・通知などの健全性。緑=正常/橙=注意/赤=停止。外側タップで閉じる)。ロゴ横の小さなドットは常時の健康ランプ。左の縦ナビでページ移動(各ページは下端で強く引っ張ると次ページへも進める)。' },
  { page: '① Today(今日の判断)',
    descJa: 'まずここを開く。市場ランプで今どの市場が開いているか→総合判断(HOLD等/リスク/理由/触る・避ける・次の条件)で今日の構え→24/7イベントでS高/急変の有無(タップで「何が起きた/原因/シナリオ/罠」)→判断ログで自己採点の成績。10秒で全体把握。' },
  { page: '② Watchlist(個別銘柄)',
    descJa: '日本株/米国株/投信/暗号資産を検索して追加・ドラッグ並べ替え。各行に行動ラベル+戦略カード(理由/次の条件/シナリオ確率)、日米株は「⚡エントリー診断」で入りの瞬間判断。保有数量・取得単価を入れると評価額/含み損益(端末内のみ)。「¥XをYに追加したら?」のWhat-if試算もここ。' },
  { page: '③ Market Context(地合い+予定)',
    descJa: '今の地合いと、これから来る予定を1画面に。資金ローテーション+レジーム(RISK_ON〜EVENT_WAIT)+金利/VIX/HY OASの背景、さらに公式カレンダー(FOMC/CPI/日銀/入札のD-7→D+1)・エスカレーション方針・危機ヘッドライン監視(News Radar)。Todayの判断の「なぜ」と「今週の地雷」をまとめて裏取り(v10.57でMarket RegimeとEvent Radarを統合)。' },
  { page: '④ Core Portfolio(資産配分)',
    descJa: '①あなたの実配分(円換算・含み損益) ②8資産クラスのライブ判断(クラス判断) ③姿勢連動の積立方針。「比率をどう動かすか」の意思決定はこのページで完結。' },
  { page: '⑤ Guide(このページ)',
    descJa: '使い方・用語・自己採点の成績(Ledger Health)・情報源の真実性(レジストリ)・暗号化バックアップ設定。困ったらここ。アプリ更新のたびに自動で最新化されます。' },
];

const CAPABILITIES: { area: string; descJa: string }[] = [
  { area: '今日の判断 (Today)',
    descJa: '①市場セッションランプ(JP/US market・Crypto — 開場中は緑、引け後は消灯) ②総合判断(WAIT/HOLD等)・リスク・理由・触る/避ける/次に待つ条件を金利/レジーム/イベント/価格からライブ合成 ③24/7イベント(S高/急変・タップで調査ドシエ) ④判断ログ(自己採点)。開いて10秒で今日の構えが分かる。' },
  { area: 'Watchlist',
    descJa: '銘柄を検索して追加(日本株/米国株/投信/暗号資産)・ドラッグ並べ替え。追加した銘柄には自動でライブ価格+ルールベースの行動ラベル+戦略カード(理由/次の条件/シナリオ確率)が付く。日米株はカード内の「⚡エントリー診断」で入りの瞬間判断(トレンド/過熱/大口フロー/イベント)を即取得(v10.15+)。' },
  { area: '大口フロー (Big-money)',
    descJa: 'moomooブリッジ経由で大口注文の純流入率(本日累計)を取得し、戦略カードに表示。ルールエンジンの「確証シグナル」として機能 — 緩やかな下落+大口流入ならBUY DIP候補、大口流出が続けばHOLD→WAITに引き締め。' },
  { area: '価格データ',
    descJa: '日本株=J-Quants(前日終値)、米国株=Twelve Data(Basicはレギュラー時間の米国株/ETFがリアルタイム・時間外RTは上位プラン要)、暗号資産=CoinGecko。moomooブリッジ稼働中は日米株がリアルタイムに自動アップグレード(途絶時は自動フォールバック)。画面を開いている間は15秒毎に自動更新(v10.10.1+)。「15秒push」は配信頻度でデータ鮮度ではなく、ブリッジの真のリアルタイム性はexchangeTsで証明できるまでentitlement=unknown(過大主張しない)。古いデータは「delayed」表示+確信度を自動で下げる。' },
  { area: '資産クラス司令室 (Core Portfolio)',
    descJa: '①あなたの実配分(円換算・含み損益・ジャンル別バー) ②金/債券/REIT/仮想通貨/USDJPY/現金/日米株の8クラスのライブ判断(クラス判断) ③姿勢連動の積立方針を1ページに統合(v10.13+)。比率調整の意思決定はここで。' },
  { area: 'Market Context (地合い+予定)',
    descJa: '資金ローテーション(ETF proxy)+レジーム(RISK_ON〜EVENT_WAIT)+金利/VIX/HY OASの背景に加え、FOMC/CPI/雇用/日銀/国債入札の公式カレンダーをD-7→D+1でエスカレーション表示。1画面に統合(v10.57でMarket Regimeとイベント監視を合体)。行動ラベルにも反映。' },
  { area: 'News Radar (原因検知)',
    descJa: '戦争・為替介入・金融破綻・緊急会見・非常事態などの危機級ヘッドライン件数を6時間窓で監視(GDELT)。テーマが増加に転じたらスマホへ通知し、朝ダイジェストにも掲載(Event Radarページに表示)。参考情報で事実検証はしない。' },
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
  { area: '24/7イベント検知 (Event Intelligence)',
    descJa: 'moomooブリッジの15秒pushをサーバー側で常時解析し、S高/S安(TSE制限値幅テーブルで正確に)・急騰/急落・大口フロー異常を決定論で検知(LLMなし)。さらに直近1分の「変化率」を見る早期警戒層で、日中変化が本格閾値に達する前の急加速・大口フロー反転も検知(v10.49+)。重要な変化(sev4+)だけスマホへ通知し、各イベントは事実/推論/欠損を区別した調査ドシエ付き。暗号資産は深夜・週末も常時。PTS/板(L2)/VWAPは未対応(capability-gated)。' },
  { area: '通知 (エージェント)',
    descJa: '日本株の寄り前8:30と米国株の寄り前22:00にダイジェスト、市場時間中(7〜24時)は「姿勢の変化・イベント接近・ボラティリティの圏域上昇/VIX急騰(固定の閾値ではなく、速度と自身の60日分布で文脈判定)・信用ストレス」の時だけアラートをスマホへpush(ntfy設定時)。通知タップでアプリが開く。' },
  { area: 'AI',
    descJa: 'GPT-5.5 Pro Handoff=手動コピペで無料の深掘り相談。自動AI判断(GPT-5.5主+Gemini 2.5 Pro検証・Geminiは429時のみFlashへフォールバック)=管理者実行・キャッシュ閲覧のみ公開。実行結果は台帳に永続化され、サーバー再起動後も直近の見解を自動復元。コストはARGUS側のハード上限(日次$5/月次$80・既定)で制御し、上限到達で新規実行を拒否(OpenAIの前払い残高に依存しない)。トークン×単価の推定コスト・実際に動いたモデルを記録(v10.50+)。下のAPI statusに現在の状態が常に出る。' },
  { area: '正直さの原則',
    descJa: '全データに live/partial/mock/delayed を明示。ARGUSは予測ではなく「現在の分類」。シナリオ確率は予言ではなく状況整理。' },
];

const RECENT_UPDATES: [string, string][] = [
  ['v10.59.0', '台帳の復旧と正直化 — ①予測台帳(自己採点)の履歴(133件)が06-22のワークフロー不具合で消えていたのを復元し、ワークフローを修正(既存ブランチを誤って初期化しない安全策)。これで自己採点(的中率58.6%等)が再表示②投信の「積立継続」表記を正直に: これは"地合い連動の積立方針"であって基準価額のチャート判断ではない旨を明記(価格データを持たないのに判断しているように見える誤解を解消)'],
  ['v10.58.0', '不具合修正 — ①Market Contextの資金ローテーションが空になる問題を修正(ETFデータが不完全な時に5分毎に再取得し、Twelve Dataの無料枠 800/日を使い切って終日失敗していた。再取得を45分間隔にして枠内に収める)。取得待ち時は「データ取得待ち(無料枠上限)」と正直表示し「接続中」のまま固まらないように②「Add Asset」が画面のずっと下に出る問題を修正(オーバースクロール用のtransform内にあったためで、bodyへポータル化+画面上部に表示)③深夜の変な時刻に通知が来る問題を修正(GitHub cron遅延対策・前掲)'],
  ['v10.57.0', 'ページ統合でさらにシンプルに — ①「Market Regime」と「Event Radar」を1つの「Market Context」に統合(今の地合い+資金回転+金利、これから来る予定イベント+News Radarを1画面に。ナビ6→5ページ)②ページ内の重複も削除: 同じ金利を二度出していた「FRED Rates Snapshot」を撤去(「Rates backdrop」に一本化)、「Regime用語集」をGuideの用語一覧に集約。Todayの「Next ◯◯」ピルはMarket Contextへ遷移。使い方ガイド・用語集も自動で追従更新'],
  ['v10.56.0', '使い方ガイドをページ別に刷新 — Guideの先頭に「使い方 — ページ別ガイド」を追加(共通ヘッダー→Today→Watchlist→Market Regime→Event Radar→Core Portfolio→Guideの順で、各ページの目的と操作を説明)。削除済みのAction Alerts/旧Today要素への古い記述も訂正。以後アプリ更新のたびにこの使い方ページも自動で最新化します'],
  ['v10.55.0', '重複の整理(続き) — ①Topの「Priority watchlist」を削除(Watchlistページの上位抜粋で重複)。Todayは市場ランプ+総合判断+24/7イベント+判断ログに集約 ②「Action Alerts」ページをナビごと廃止(中身のSatellites=Core Portfolioの「クラス判断」、Index Funds=「積立方針」と完全重複。Core Portfolioは「あなたの配分」も持つ上位互換)。不要な価格取得もカット。ナビは Today/Watchlist/Market Regime/Event Radar/Core Portfolio/Guide に簡素化'],
  ['v10.54.0', 'Topの「partial」表記を「市場セッションのランプ」に置換 — 分かりにくい partial を廃止し、JP market / US market / Crypto の名前+緑ランプで「今どの市場が開いているか」を直接表示(開場中=緑・引け後=消灯)。金利/イベント等の"API/データ源が動いているか"はTopの鮮度ではなく左上ARGUSロゴのシステム状態ポップアップで判断する、と役割を明確に分離'],
  ['v10.53.0', 'システム状態を左上のA.R.G.U.S.ロゴに統合 — ロゴをタップするとポップアップで全システムの健全性(AI予算・各データ源・通知など9項目)を表示、外側をタップ(またはEsc)で閉じる。ロゴ横に常時表示の状態ドット(緑=正常/橙=注意/赤=停止)が付き、どのページからでも一目で異常に気づけます。Todayの帯は廃止し、グローバルなヘッダー表示に一本化'],
  ['v10.52.0', '日本株は必ず会社名を表示+Today画面の重複を整理 — ①イベントカード/スマホ通知/Pro相談/材料一覧で日本株がバレ4桁だった箇所を「会社名(コード)」表示に(会社名はJ-Quantsマスターから解決・推測しない)②Today(トップ)を統合ビューに専念させ、専用ページと重複していた4セクション(Event Radarカレンダー・Market News・Top Rotations・Core Portfolio抜粋)を削除。イベントカードもTodayに一本化(Action Alertsの重複を解消)。情報は各専用ページに残るので消えません。不要なニュース取得もカット'],
  ['v10.51.0', 'システム状態ランプ(緑→赤)をTodayに追加 — 課金/重要システム(AI予算・AI判断・moomooブリッジ・日米株/暗号資産/金利の各データ源・EDINET・通知)の健全性を小さなランプで一目表示。AI予算が上限到達で新規AI実行が止まると赤く点滅、80%超で橙。タップで各項目の状態を展開。公開画面なので色と短い日本語のみ(金額など詳細は管理者画面)。サイレントな予算停止やブリッジ途絶に気づけます'],
  ['v10.50.0', 'コスト管理・プロバイダ正直性・EDINET材料判定の強化パッチ — ①AIに「ARGUS側のハード予算上限」(日次$5/月次$80・既定、env調整可)を追加。上限到達で新規AI実行を拒否し、OpenAIの前払い残高に依存しない。トークン使用量×単価で推定コストを記録、月次合計は台帳ブランチに永続(再起動でもリセットされない)②Geminiは2.5 Proが通常検証役・Flashは429時のみのフォールバックと明記し、実際に動いたモデルを記録(校正でPro/Flashを混同しない)③Twelve Data表記を訂正(Basicはレギュラー時間の米国株RT・無料枠の鮮度は未計測なので「遅延」と断定しない・アップグレード不要)④EDINETは「公式事実」だが、当日の「公式材料(official_catalyst)」になるのは臨時報告/大量保有など材料性のある開示が当日提出された場合のみ(定期/訂正は原因扱いしない)。書類種別を分類しdocID/提出時刻/発行体/関係性を保存⑤moomooの能力検証レポートを追加(管理者)⑥TDnet購入判断の客観指標(週次・TDnetデータ不使用)を追加。自動売買は追加しない'],
  ['v10.49.0', '早期警戒層(ローリング短期特徴量)を追加 — 24/7監視に「動きの始まり」を掴む層を追加。日中の累積変化が本格閾値(急騰±5%等)に達する前に、直近1分の変化率で①急加速(MOMENTUM_ACCELERATION)②大口フロー反転(FLOW_REVERSAL)を検知。サーバー側で既存の15秒pushから計算するため、EC2もあなたの操作も追加不要。セッション対応で薄商いの誤検知を抑制し、本格イベントが既に出た銘柄では二重通知しない。決定論・LLMなし'],
  ['v10.48.0', 'EDINET(金融庁の公式開示)連携を追加 — 日本株のイベント時に直近のEDINET開示(有報・大量保有報告等)を照合し、あれば調査ドシエの「確認済み事実」に本物の一次情報として掲載。推定原因も「公式材料(official_catalyst)」が到達可能に。要・無料APIキー(EDINET登録→RenderにEDINET_API_KEY設定)。未設定時は情報源レジストリに「未設定」と正直表示'],
  ['v10.47.0', 'Source Capability Registry を追加 — 情報源の「真実性」をcapability単位で1画面に(Guide)。「設定済み≠ライブ」を明確化し、各機能をライブ確認/遅延/要検証/有料未契約/未対応で正直表示。PTS・板(L2)・テープ・VWAP・TDnet/EDINET・FX/先物/商品は未対応と明記(過大主張を防止)。moomooの板/VWAPの過大記載も修正'],
  ['v10.46.0', '「全体をAIに相談」(Pro Handoff)に検知中イベントの調査ドシエを自動添付 — S高/急変/暗号資産ショックがある時、その「何が起きた/推定原因/次シナリオ/罠/反証/無効化条件/欠損データ」をLLM相談プロンプトに同梱。事実と推論を区別・確率は未較正・売買指示なしを明記。AIに渡す現状情報が一段濃くなります'],
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
  ['Market Context', '市場コンテキスト — 地合い(レジーム/資金回転/金利)+予定イベント/危機ニュースを1画面に'],
  ['Watchlist', '監視リスト'],
  ['Core Portfolio', '資産クラス司令室 — 配分の現在地とクラス別の構え'],
  ['Capital Rotation', '資金回転'],
  ['Regime Matrix', 'レジーム行列'],
  ['Top Rotations', '注目資金移動'],
  ['Action Label', '行動ラベル'],
  // Regime tags (moved from the Market Regime page glossary, v10.57):
  ['Risk On', '株式・ハイベータが牽引、ディフェンシブは遅れる'],
  ['Risk Off', 'ディフェンシブが先導、株式・クレジットが弱含み'],
  ['Event Wait', 'ウィンドウ内に主要触媒。新規エントリーを抑制'],
  ['Cautious', '方向感は限定的、金利・VIX・イベントのリスクがくすぶる'],
  ['Mixed', '明確な主導役がなく、資金の方向感は限定的'],
  ['Rates Pressure', '金利上昇 — デュレーション資産とグロース倍率が圧縮'],
  ['Credit Stress', 'ハイイールド・スプレッド拡大、リスク回避の兆候'],
  ['Gold Hedge', 'マクロ不安または実質利回り反転で金が先行'],
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
    <PageShell title="Glossary / Guide" subtitle="使い方(ページ別)・できること・用語一覧(日本語ガイド)。">
      <section>
        <div className="section-head">
          <span className="section-head__title">使い方 — ページ別ガイド</span>
          <span className="section-head__count">ナビ順</span>
        </div>
        <div className="card guide-card">
          <div className="guide-caps">
            {PAGE_GUIDE.map((p) => (
              <div className="guide-cap" key={p.page}>
                <span className="guide-cap__area">{p.page}</span>
                <span className="guide-cap__desc">{p.descJa}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="section-head">
          <span className="section-head__title">ARGUS でできること(機能一覧)</span>
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
          <span className="section-head__title">情報源レジストリ (真実性)</span>
          <span className="section-head__count">capability別</span>
        </div>
        <SourceRegistryCard />
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

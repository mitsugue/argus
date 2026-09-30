# 日経比較の市場条件 16系列 — 出所と入手時刻の規則

日本株分析エンジン(`jp_market_engine`)の類似局面選択は、価格形状・市場状態・
条件の順序・材料反応の4要素の距離で候補を選ぶ。市場状態は
`jp_market_analogs.FEATURE_DEFINITIONS` の16系列で定義される。2026-09-30 時点で
現在側と過去側の両方に値があり比較に使えたのは6系列だった。本書はその原因と、
全系列を現在・過去ともに実現するための出所・入手時刻の規則・進捗を記録する。

## 入手時刻の規則 (2026-09-30 変更)

- 原観測(revision 0)は**公表スケジュール由来の保守的な入手時刻**
  (観測日の翌暦日 00:00Z = 09:00 JST。米国系列は翌々日)を `knownAt`/`availableFrom`
  に持つ。`receivedAt` に実際の受信時刻を残し、`availabilityBasis` は
  `SCHEDULED_PUBLICATION`。生データは書き換えず、読み側の規則として適用する。
- 訂正(revision ≥ 1)は受信時刻からのみ入手可能(`RECEIVED_CORRECTION`)。
  過去の基準日が見た値を後から書き換えない。
- 形成中セッション(当日行)の日中更新は `PROVISIONAL_SESSION_UPDATE`。入手時刻の
  境界は維持する。
- いずれも `historicalVintageVerified: False`。改訂前の値の再現は未検証であり、
  画面の限界表示にその旨を出す。
- 変更前は取込済みの公式履歴(財務省金利・Cboe VIX)が受信時刻を知得時刻としていた
  ため、過去の基準日からは見えず、10年分の履歴が類似局面の選択に寄与していなかった。

## 系列と出所

| 系列 | 出所 | 入手時刻 | 状態 |
|---|---|---|---|
| credit.ratio / credit.ratio_change | JPX 二市場信用(CSV+台帳) | 公表スケジュール | 稼働 |
| vix.level / vix.change5 / vix.macd_histogram | Yahoo ^VIX (Cboe公式履歴で補完) | 翌日 00:00Z | 稼働 |
| relative_jp_us.return20 | Yahoo ^N225 / ^GSPC | 翌日 | 稼働 |
| rate.jp10y_change5 | 財務省 国債金利 全履歴 | 翌日 00:00Z | B1 で過去側が有効化 |
| fx.usdjpy_change5 | Yahoo JPY=X 10年 | 翌日 00:00Z | B1 で追加 |
| rate.us10y_change5 | FRED DGS10 | 翌々日 00:00Z | B1 で追加 |
| nt.ratio_change5 | J-Quants `/indices/bars/daily/topix` 10年 | 翌日 00:00Z | B1 で追加(TOPIX水準は表示しない) |
| margin1570.ratio / long_change_pct / short_change_pct | J-Quants 信用残(1570) 10年(1日1回の取り寄せで店に追記) | 週末+6日 00:00Z(原観測)・訂正は受信時刻 | B2 で追加 |
| foreign_flow.net4w | J-Quants 投資部門別(台帳・10年の一回取込) | 公式PubDate 18:00 JST | B2 で過去側を追加 |
| event.sq_sessions | 現在=JPX公表日程(VERIFIED)・過去=第2金曜/前営業日の規則(RULE_DERIVED) | 計算日の 00:00 JST | B2 で追加。規則導出は VERIFIED と表示しない |
| credit.loss_pct | 公式値はライセンスなしで取得不可。ARGUS代理計算=二市場買い残の週次純増を各週末の指数終値で取得したとみなす26週加重コスト vs 最新終値 | 入力(信用残・終値)の入手時刻に従う | B3 で追加。特徴に `derivationBasis=ARGUS_PROXY_MARGIN_COST_BASIS_26W`、画面は「信用評価損失率（ARGUS代理計算）」。公式値がある場合は公式値のみ |

## 取得の頻度と経路

新しい履歴は収集 warm(`_jp_market_engine_pit_inputs(warm=True)`)でのみ取得し、
公開経路はキャッシュ限定。FRED と J-Quants は6時間に1回、Yahoo は既存の指数と同じ
TTL。`jp_market_acquisition.py` の変更は特徴履歴の手法識別子を変えるため、配信後の
最初の収集で全再計算(`METHOD_CHANGED`)が1回走る。

## 検証状態

実装・テスト済(2026-09-30)。本番での各系列の充足は配信後のプローブ
(`index-comparison.json` の `marketFeatureSnapshot.missingFeatures` と候補の
`comparedFeatures`)で確認する。予測の検証(バックテスト)は別ユニット(D)。

## 計算予測の過去検証 (2026-09-30 追加)

`jp_market_analog_backtest.walk_forward` が、比較が作る封印済みエピソードをそのまま使い、
過去の各日付(5営業日おき、直近最大600時点)でその時点までの情報だけから同じ方法で予測を作り、
実際の値動きと照合する。

- 候補はその後の経路が評価日までに閉じたものだけ(位置差 ≥ 21 営業日)。
- 物差しは暦年ごとに、その年の1月1日より前に入手可能だった特徴行から再計算する。
- 期間ごとに重ならないよう、h営業日先は ceil(h/5) 時点おきに集計する。
- 判定: 方向を示した独立評価が100件以上、方向一致率の95% Wilson 下限が「いつも多数派の方向」
  の率を上回り、帯(四分位)に実際の値が入った割合が35〜65%のとき `VALIDATED`。
  それ以外は `UNVALIDATED` と理由を表示する。
- 過去の一致率であり、将来の確率としては扱わない(`predictiveProbabilities: null`)。

検証は1日1回(履歴か方針が変わったとき)計算し、4つの期間で共有する。

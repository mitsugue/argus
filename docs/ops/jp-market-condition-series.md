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
| margin1570.ratio / long_change_pct / short_change_pct | J-Quants 信用残(1570) | 受信時刻(現状) | B2: 10年へ拡大、入手時刻規則の検討 |
| foreign_flow.net4w | J-Quants 投資部門別 | 未定 | B2 |
| event.sq_sessions | JPX 公表日程 | 過去分は規則導出をラベル | B2 |
| credit.loss_pct | 無料の公式10年源なし | — | B3: 代理計算をラベル付きで実装、公式値と区別 |

## 取得の頻度と経路

新しい履歴は収集 warm(`_jp_market_engine_pit_inputs(warm=True)`)でのみ取得し、
公開経路はキャッシュ限定。FRED と J-Quants は6時間に1回、Yahoo は既存の指数と同じ
TTL。`jp_market_acquisition.py` の変更は特徴履歴の手法識別子を変えるため、配信後の
最初の収集で全再計算(`METHOD_CHANGED`)が1回走る。

## 検証状態

実装・テスト済(2026-09-30)。本番での各系列の充足は配信後のプローブ
(`index-comparison.json` の `marketFeatureSnapshot.missingFeatures` と候補の
`comparedFeatures`)で確認する。予測の検証(バックテスト)は別ユニット(D)。

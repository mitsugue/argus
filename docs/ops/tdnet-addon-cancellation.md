# 公式TDnet Add-on の解約と、その後の運用（2026-09-29）

## 何を解約したか

J-Quants の **TDnet/Company Disclosure アドオン（月額 ¥11,000）** のみ。
**Standard プラン（月額 ¥3,300）は解約しない。** 信用残高・貸借・投資主体別売買などの
需給分析の土台がそこにあり、これを失うと ARGUS の需給ランクが成立しない。

## 適時開示は止まらない

`get_tdnet_recent()` は最初から二段構えで、公式アドオンが使えないときは無料の
yanoshin ミラー（`provider="yanoshin-tdnet"`, `official=false`）に自動で切り替わる。
2026-09-29 に実地確認済み（HTTP 200・当日の開示行を取得・パーサの参照フィールドは
`company_code` / `company_name` / `title` / `pubdate` / `document_url` で一致）。

## 失うもの（ごまかさない）

公式の裏付けが付かなくなるため、以下は**構造的に**起きなくなる。これは正しい劣化で、
解約後に元の水準を主張してはいけない。

- `has_official` が false 固定 → `corroboration_level` は official / official_and_market_confirmed に到達しない
- `resolve_trigger_role()` は `confirmed_cause` を返さない（原因は推定止まり）
- Evidence Pack の公式開示欄が空、`missingConfirmations` に `cache:tdnet:not_official` が入る
- 開示の抜け漏れ・遅延が起こり得る（ミラーは公式配信ではない）

## 設定（Render の環境変数）

```
ARGUS_TDNET_ADDON=off
```

これを入れると、システムは「解約済み（意図的）」を**宣言された状態**として扱う。

- 公式エンドポイントへのプローブを一切行わない（403 を 15 分ごとに叩き続けない・Standard のレート枠を消費しない）
- ソース登録簿の表示が `not_subscribed` ／「解約済み(意図的)」になり、
  **ダッシュボードでアドオンを買い直せという案内を出さない**
- 障害としては採点されない（`argus_tdnet_subscription.is_failure_status()` が false）

未設定なら従来どおり公式を試す（`auto`）。**既定を off にはしない** — 有効な有料
フィードを黙って無視する事故のほうが高くつく。

## タイミング

解約は請求期間の終わりまで使えるため、`ARGUS_TDNET_ADDON=off` は
**権限が切れる当日までに**入れればよい。先に入れても公式を使わなくなるだけで壊れない。

## 将来の代替

公式性を取り戻したいときは `release.tdnet.info` から直接取り込む経路を作る（有料契約なし）。
未着手。これが入るまで公式確認は付かない。

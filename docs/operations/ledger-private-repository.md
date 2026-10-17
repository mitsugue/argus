# データ用の枝（ledger）の置き場所（2026-10-17）

## 決まり
- `ledger` 枝は、オーナーの非公開リポジトリ `mitsugue/argus-l2b-private` に置く。公開リポジトリには置かない。
- 非公開側の `ledger` 枝は、公開側にあったときと**同じコミットの続き**になっている。遠隔からの復旧が保存しているコミット番号(受領記録の `remoteCommitSha`・封印した `ledgerBaseCommitSha`)が、そのまま通用する。

## 書く側
- 書き込みのワークフロー(event-ledger・macro-event-analysis・learning-memory・mover-causes・prediction-ledger・vault-sync・caos-scan・caos-watchtower)は、ledger を取得する直前に `scripts/ledger_use_private.sh` を呼ぶ。
- このスクリプトは、接続先(origin)と、actions/checkout が保存した鍵を、非公開リポジトリ用の鍵(秘密 `ARGUS_PRIVATE_LEDGER_TOKEN`)に置き換える。鍵は HTTP の見出しとしてだけ送り、ログでは伏せ字にする。鍵がなければ、その手順は失敗する。

## 読む側
- サーバーは `_LEDGER_RAW_BASE`(既定は非公開側)から読む。非公開リポジトリの URL に対してだけ、`ARGUS_RECOVERY_GITHUB_READ_TOKEN` または `ARGUS_LAYER2B_PRIVATE_TOKEN` を付ける(`_ledger_get`・`_ledger_auth_headers`)。
- ブラウザは ledger を直接読まない。バックアップの取り出しは、サーバーの中継(`/api/argus/vault-relay`)だけを使う。

## 切り替えの経緯
1. 2026-10-16: 非公開側へ写す仕組みを作った(段階1)。
2. 2026-10-17: 写し方を「公開側と同じコミットのまま早送り」に改め、公開側の全履歴を一度だけ非公開側へ送った。
3. 2026-10-17: 読む側と書く側を同時に非公開側へ切り替え、写しのワークフローを外した。公開側の `ledger` 枝は、その時点の内容のまま更新が止まる(段階3)。
4. 公開側の `ledger` 枝の削除(段階4・オーナー決定 B)は、非公開側の一致を確かめてから行う。

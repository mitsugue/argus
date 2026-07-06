# ARGUS moomoo ブリッジ (v9.11)

OpenD が動いているマシン(AWS)の**中**で動かす小さな常駐スクリプト。
ローカルの OpenD からリアルタイム価格を読み、ARGUS バックエンドの
`POST /api/argus/quote-push`(admin token 必須)へ60秒ごとに送ります。

- push が新鮮(10分以内)な間は、アプリの価格が**リアルタイム**になります
- ブリッジが止まると自動で J-Quants(T-1) / Twelve Data にフォールバック
- 口座の認証情報・OpenD は**この1台から外に出ません**

## ⚠️ 最重要セキュリティ

**AWS のセキュリティグループで、ポート 11111 をインターネットに公開しないこと。**
OpenD は気配だけでなく取引コンテキストも開けるゲートウェイです。このブリッジは
同じマシン内(`127.0.0.1:11111`)で OpenD に話すので、**インバウンド開放は一切不要**。
公開されていたら今すぐ閉じてください(SSH 22番だけ残せば運用できます)。

## セットアップ(AWS のマシンで)

```bash
# 1. 配置(例: /opt/argus)
sudo mkdir -p /opt/argus && sudo git clone https://github.com/mitsugue/argus.git /opt/argus
pip3 install moomoo-api requests

# 2. 環境ファイル(トークンを記入)
sudo cp /opt/argus/bridge/bridge.env.example /etc/argus-bridge.env
sudo nano /etc/argus-bridge.env       # ARGUS_ADMIN_TOKEN と PUSH_SYMBOLS を編集
sudo chmod 600 /etc/argus-bridge.env

# 3. まず手動で1回テスト
set -a; source /etc/argus-bridge.env; set +a
python3 /opt/argus/bridge/moomoo_push.py
#   "pushed http=200 accepted=11" のような行が出れば成功(Ctrl-Cで停止)

# 4. 常駐化(systemd)
sudo useradd -r -s /usr/sbin/nologin argus 2>/dev/null || true
sudo cp /opt/argus/bridge/argus-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now argus-bridge
journalctl -u argus-bridge -f         # ログ確認
```

## 動作確認(どこからでも)

```bash
curl -s https://argus-backend-3j2m.onrender.com/api/argus/integrations | python3 -m json.tool | grep -A3 moomoo
# → "runtimeStatus": "live" + "last push Xs ago" なら成功
```

アプリの Watchlist の価格がザラ場中に分単位で動けば完成です。

## 銘柄の追加

ARGUS の Watchlist に銘柄を足したら、`/etc/argus-bridge.env` の `PUSH_SYMBOLS` にも
`JP.7203` / `US.AMD` の形式で追記して `sudo systemctl restart argus-bridge`。
(将来のバージョンでこの手動同期は自動化予定)

---

## 運用ランブック (v11.5.7 — 2026-07-03 OpenD障害の教訓)

このブリッジは **US/JPを分離取得** します。片方の市場の権限エラーが
もう片方を止めることはありません。JPで「No permission to get quotes」が
出ると自動で30分バックオフし、USのpushは継続します。60秒毎に
heartbeat(閉場中も)をバックエンドへ送り、アプリの「システム状態」に
**ブリッジ/OpenD/US realtime/JP realtime が分割表示**されます。

### ⚠️ 秘密情報の取り扱い(最重要)
- **SMSコード・moomooパスワード・ARGUS_ADMIN_TOKEN・HMAC秘密鍵を
  ChatGPT/Claude等のチャットに絶対に貼らないこと。**
- 万一貼ってしまった場合: moomooパスワードを変更し、RenderのARGUS_ADMIN_TOKEN
  とARGUS_BRIDGE_HMAC_SECRETをローテーション → /etc/argus-bridge.envも更新。

### ディスク拡張チェックリスト(7/3: / が100%でOpenDが不調に)
1. `df -h` で使用率確認(90%超えたら対応)
2. AWSコンソール → EBSボリュームサイズ変更(例: 6.61GB→50GB)
3. インスタンス内で `sudo growpart /dev/xvda 1`(またはnvme0n1p1)
4. `sudo resize2fs /dev/root`(xfsなら `sudo xfs_growfs /`)
5. `df -h` で反映確認(現在: /dev/root 48G, 13% used)
6. 不要ログ掃除: `sudo journalctl --vacuum-size=200M`

### OpenD SMS認証チェックリスト(7/3: 認証待ちでpush不能に)
1. `ps aux | grep -i opend` — **重複プロセスがあれば全部kill**してから1つ起動
2. OpenDログに `Abnormal event timeout / RemoteClose / Context status bad`
   が出ていたらAPI不調 → OpenD再起動
3. SMS認証待ちの場合: telnet制御ポート(127.0.0.1:22222 — **localhostのみ**)
   から `input_phone_verify_code -code=XXXXXX` で入力(コードは端末で直接入力)
4. 接続成功後 `sudo systemctl restart argus-bridge`
5. ログで `pushed http=200 accepted=N mode=...` を確認

### US-onlyモードの有効化(JPクォート権限が無いとき)
```bash
sudo nano /etc/argus-bridge.env    # ARGUS_DISABLE_JP_QUOTES=1 を追加
# PUSH_SYMBOLSをUS銘柄だけにするのは任意(フラグだけでJP系は全停止する):
# PUSH_SYMBOLS=US.NVDA,US.AAPL,US.TSLA,US.META,US.SPY,US.QQQ,US.IWM,US.XLK,US.XLU,US.GLD,US.TLT,US.HYG
sudo systemctl restart argus-bridge
journalctl -u argus-bridge -n 20 --no-pager   # "[US-ONLY MODE]" 表示を確認
```
アプリ側は「JP realtime: 無効化中 — 日本株は代替データで判定」と表示されます。

### fullモードへの復帰(moomooでJP権限を取得できたら)
1. まず手動で権限テスト(EC2で):
```bash
python3 - <<'PY'
from moomoo import OpenQuoteContext
qc = OpenQuoteContext(host="127.0.0.1", port=11111)
ret, df = qc.get_market_snapshot(["JP.8058", "JP.9984"])
print("ret=", ret)   # 0 なら権限OK / -1 "No permission" なら未取得
print(df if ret != 0 else df[["code", "last_price"]])
qc.close()
PY
```
2. ret=0 を確認できたら `/etc/argus-bridge.env` から `ARGUS_DISABLE_JP_QUOTES=1`
   を削除し `sudo systemctl restart argus-bridge`
3. **ret=-1のままフラグだけ外さないこと**(自動バックオフで実害はないが
   30分毎に権限エラーを試み続ける)

### 日常の確認コマンド
```bash
systemctl status argus-bridge
journalctl -u argus-bridge -n 120 --no-pager
df -h
# どこからでも(公開・秘密なし):
curl -s https://argus-backend-3j2m.onrender.com/api/argus/bridge/status | python3 -m json.tool
```

### コード更新の反映(このリポジトリを更新したら)
```bash
cd /opt/argus && sudo git pull
sudo systemctl restart argus-bridge
```

---

## OpenD 10.8.6818 運用ランブック (v11.5.9 — 7/3-4障害からの復旧を運用化)

### 現在の本番構成(2026-07-04時点)
- EC2: `ubuntu@52.195.168.61` / ディスク 48GB(使用 ~16%)
- OpenD: **10.8.6818**(旧 10.7.6718 からアップグレード済み)
  - 実行ディレクトリ: `/home/ubuntu/moomoo_OpenD_new/moomoo_OpenD_10.8.6818_Ubuntu18.04/`
  - API: `127.0.0.1:11111` / telnet: `127.0.0.1:22222`(**どちらもlocalhostのみ**)
- 権限: **US Stocks LV3(Normal)/ JPN Stocks 権限なし** → **US-onlyモードは意図的**
  (`ARGUS_DISABLE_JP_QUOTES=1`)。日本株はJ-Quants/Yahoo代替で判定(アプリに明示)。
  moomoo側でJPN Stocksが Normal/LV1+ になるまでJPは無効のまま維持する。
- HMAC秘密はローテーション済み・`/etc/argus-bridge.env`(root:root, 600)のみ。
  `systemctl cat argus-bridge` に秘密は出ない。

### 安全な確認コマンド(このリポジトリの bridge/scripts/ を使う)
```bash
cd /opt/argus && sudo git pull        # スクリプト取得(初回)
bridge/scripts/check_opend_status.sh      # OpenDバージョン/ポート/プロセス(マスク済み)
bridge/scripts/check_bridge_status.sh     # argus-bridge状態+直近ログ(マスク済み)
bridge/scripts/safe_opend_process_view.sh # プロセス表示(資格情報を必ずマスク)
bridge/scripts/safe_public_bridge_status.sh  # 公開ステータス(どこからでも可)
```
**生の `ps aux | grep OpenD` をドキュメントやチャットに貼らないこと** —
OpenDは `-login_pwd` 引数を持つため、マスク無しの出力はパスワードを含み得る。

### 図形認証(graphic verification)の手順
1. `bridge/scripts/request_pic_verify_code.sh` — `req_pic_verify_code` を送信。
   画像はOpenDディレクトリ直下の `PicVerifyCode.png` に生成される
2. Mac側で取得して開く:
   `scp ubuntu@52.195.168.61:/home/ubuntu/moomoo_OpenD_new/moomoo_OpenD_10.8.6818_Ubuntu18.04/PicVerifyCode.png ~/Desktop/`
3. `bridge/scripts/submit_pic_verify_code.sh` — コードは**サイレント入力**
   (`input_pic_verify_code -code=...` を内部送信・画面/履歴に残さない)
4. **間違えたら古い画像は失効** — 必ず手順1から画像を取り直す

### SMS認証の手順
1. `bridge/scripts/request_sms_verify_code.sh`(`req_phone_verify_code`)
2. `bridge/scripts/submit_sms_verify_code.sh` — サイレント入力
   (`input_phone_verify_code -code=...`)
3. **SMSコード/図形コード/パスワードをチャットやドキュメントに絶対に貼らない**

### OpenDアップグレード・チェックリスト(10.8.6818で実証済みの経路)
1. Macで公式Ubuntu版OpenDをダウンロード
2. `scp <パッケージ> ubuntu@52.195.168.61:/home/ubuntu/moomoo_OpenD_latest.tar.gz`
3. `sudo systemctl stop argus-bridge`
4. OpenD停止(safe_opend_process_view.sh でPID確認 → kill。**重複プロセス厳禁**)
5. 旧ディレクトリをバックアップ(例: `mv moomoo_OpenD_new moomoo_OpenD_backup_$(date +%F)`)
6. 新パッケージを展開
7. `OpenD.xml` で `telnet_ip=127.0.0.1 / telnet_port=22222` と `api_ip=127.0.0.1` を維持
8. 新しいmoomooパスワードでOpenD起動 → 図形/SMS認証(上記手順)
9. USスナップショット手動テスト(下記) → `ret=0` を確認
10. `bridge/scripts/restart_argus_bridge.sh` → `pushed http=200 accepted=N mode=us_only`
11. `safe_public_bridge_status.sh` で bridgeProcess=ok / usRealtimeStatus=ok を確認
12. **JPN Stocks権限が Normal/LV1+ になるまで `ARGUS_DISABLE_JP_QUOTES=1` を外さない**

USスナップショット手動テスト:
```bash
python3 - <<'PY'
from moomoo import OpenQuoteContext
qc = OpenQuoteContext(host="127.0.0.1", port=11111)
ret, df = qc.get_market_snapshot(["US.NVDA", "US.TSLA"])
print("ret=", ret)   # 0 = OK
qc.close()
PY
```

### OpenDのsystemd化(提案・未デプロイ)と残存リスク
`bridge/opend.service.example` を用意した(引数なし起動・localhost限定・
Restart=on-failure・**Environment=に秘密なし**)。ただし前提として
**OpenD.xmlが資格情報欄をサポートするかをEC2上で実際に確認**すること
(リポジトリからは断定できない — example内の検証手順参照)。
確認できるまでは現行の手動起動を継続してよい。

**残存リスク(正直に):** `-login_pwd` 引数で起動する限り、このホストの
ローカルユーザー(root/ubuntu)は `ps` でパスワードを閲覧できる。
完全な隠蔽は未確認 — 「隠れている」と思い込まないこと。緩和策:
シェル履歴に残さない(起動コマンドは先頭スペース or `history -d`)、
ログへ流さない、資格情報ファイルは600、そして万一チャット等へ露出したら
**即パスワード変更+ARGUSトークン/HMACローテーション**(7/3-4で実施済みの手順)。

### 過去バージョンの記録(履歴)
- 10.7.6718: 7/3障害時の旧バージョン(ディスク満杯+SMS要求+JP権限喪失が複合)
- 10.8.6818: 2026-07-04アップグレード・図形認証→ログイン成功→US LV3確認

## 再起動(リブート)安全ランブック — v12.0.2

**現状の結論: EC2の再起動はまだ推奨しない。** bridgeはsystemd常駐だが、
OpenDのsystemd化は「提案のみ・未検証」。再起動するとOpenDが手動ログイン
(場合によりSMS/図形認証)待ちになり、USリアルタイムが停止する可能性がある。
「System restart required」表示だけを理由に再起動しないこと。

### 再起動前チェックリスト(全て満たすまで再起動しない)
1. OpenD自動起動+自動ログインの検証が完了している(未検証なら再起動しない)
2. 市場時間外である(US場中の再起動はリアルタイム停止に直結)
3. `bridge/scripts/check_opend_status.sh` が connected
4. `bridge/scripts/check_bridge_status.sh` が active
5. 認証コード受信手段(SMS/アプリ)が手元にある(再ログインに備える)

### 再起動後チェックリスト
1. OpenDポート確認: `bridge/scripts/check_opend_status.sh`
   (127.0.0.1:11111 / 22222 がLISTENか — 生のps/pgrepは使わない: 引数に資格情報が乗るため)
2. OpenDが未起動/ログイン待ちなら手動起動(既存手順・SMS/図形認証はチャットに貼らない)
3. bridge再開: `bridge/scripts/restart_argus_bridge.sh`
4. push確認: `bridge/scripts/check_bridge_status.sh`(pushed http=200 / mode=us_only)
5. 公開状態: `bridge/scripts/safe_public_bridge_status.sh`
   (bridgeProcess=ok / usRealtimeStatus=ok / jpRealtimeStatus=disabled)
6. アプリのData Qualityページで us-realtime-bridge=fresh を確認

## JPリアルタイム復帰ランブック — v12.0.2

**前提の事実: JP snapshot は現在 ret=-1 (No permission)。** これはmoomoo口座の
JPN Stocksクォート権限の問題であり、アプリ/ブリッジのコードでは直らない。

### 復帰条件(すべて満たすまでUS-onlyを外さない)
- moomoo側でJPN Stocksクォート権限を取得済み
- EC2の権限テストで JP.5803 / JP.8058 / JP.9984 のsnapshotが **ret=0**
- OpenD connected / bridge active

### 復帰手順(条件成立後のみ)
1. `sudo mv /etc/systemd/system/argus-bridge.service.d/no-jp-quotes.conf ~/no-jp-quotes.conf.bak`
2. `sudo systemctl daemon-reload`
3. `bridge/scripts/restart_argus_bridge.sh`
4. `bridge/scripts/safe_public_bridge_status.sh` で mode=full / jpRealtimeStatus=ok を確認
5. アプリのData Quality「JP REALTIME READINESS」で JP push 実測を確認

### ロールバック(No permissionで失敗した場合)
1. `sudo mv ~/no-jp-quotes.conf.bak /etc/systemd/system/argus-bridge.service.d/no-jp-quotes.conf`
2. `sudo systemctl daemon-reload`
3. `bridge/scripts/restart_argus_bridge.sh`
4. `bridge/scripts/safe_public_bridge_status.sh` で mode=us_only に戻ったことを確認

※ 本ランブックのコマンドは秘密値を一切表示しない。OpenDの起動引数を含む
生の `ps`/`pgrep` は使わないこと(`safe_opend_process_view.sh` を使う)。

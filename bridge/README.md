# Current bridge scope (v13.7.30 candidate)

The production entry point collects only SPY, QQQ, IWM, XLK, XLU, GLD, TLT and
HYG for shared market analysis. Individual watchlist quotes, capital-distribution
calls, dynamic watchlist expansion, capability sweeps and movers sweeps are no
longer executed, even when legacy environment flags remain enabled.

Shared quotes are collected no faster than every five minutes during the US
regular session, using the repository calendar (including early closes). Original
provider timestamps and HMAC authentication remain. The health heartbeat continues
outside trading hours without fetching prices. This is separate from the existing
Japan/US sector heatmap acquisition; no sector source is disabled here.

Deploy the reviewed repository revision, including `argus_market_clock.py`, to the
existing bridge installation before restarting that service. Do not delete its
credentials or OpenD configuration. Verify the heartbeat version and accepted ETF
set after deployment; a merged code change alone does not prove the EC2 process
has changed. Existing samples below describe archived versions and must not be
used to reenable individual or closing-window feeds.

---

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
curl -s https://argus-backend-3j2m.onrender.com/api/argus/bridge/status | python3 -m json.tool
# → bridge/market別の公開可能な状態と最終push時刻を確認
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
出ると自動で7日間バックオフ(週1回だけ再認定probe)し、USのpushは継続します。60秒毎に
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
1. `bridge/scripts/safe_opend_process_view.sh`(redacted表示) — **重複プロセスがあれば全部kill**してから1つ起動(生の`ps aux`は起動引数が見えるため使わない)
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
3. **ret=-1のままフラグだけ外さないこと**(自動バックオフでUSは継続し、
   JP権限は週1回だけ再認定する)

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

## OpenD 運用ランブック(2026-10-24 から 10.11.7108・systemd で自動起動)

### 現在の本番構成(2026-10-24時点)
- EC2: `ubuntu@52.195.168.61`(t3.nano・メモリ 0.5GB・Ubuntu 26.04)/ ディスク 48GB(使用 ~21%)
- スワップ: `/swapfile` 1GB。**`/etc/fstab` に登録済み**(再起動しても有効)。
- OpenD: **10.11.7108**(2026-09-17 公開。10.8.6818 から 2026-10-24 に更新)
  - 実行ディレクトリ: `/home/ubuntu/opend_10.11.7108/moomoo_OpenD_10.11.7108_Ubuntu18.04/moomoo_OpenD_10.11.7108_Ubuntu18.04/`
  - 起動: `opend.service`(systemd・`bridge/opend.service.example` と同じ内容)。
    記憶したパスワードで自動ログイン(`-login_by_remember=1`)。ログインID は `/etc/opend.env`(600)。
  - API: `127.0.0.1:11111` / telnet: `127.0.0.1:22222`(**どちらもlocalhostのみ**。
    配布時の `OpenD.xml` では telnet_ip / telnet_port の2行が `<!-- -->` で無効なので、有効にする)
  - 中の様子: `screen -r opend`(抜ける時は **Ctrl+A → D**。OpenD の画面では Ctrl+C が効かない)
- 権限: **US Stocks LV3(Normal)/ JPN Stocks 権限なし** → **US-onlyモードは意図的**
  (`ARGUS_DISABLE_JP_QUOTES=1`)。日本株はJ-Quants/Yahoo代替で判定(アプリに明示)。
  moomoo側でJPN Stocksが Normal/LV1+ になるまでJPは無効のまま維持する。
- HMAC秘密はローテーション済み・`/etc/argus-bridge.env`(root:root, 600)のみ。
  `systemctl cat argus-bridge` に秘密は出ない。
- SSH: セキュリティグループは **EC2 Instance Connect(ブラウザー・3.112.23.0/29)だけ**許可が基本。
  Mac から `ssh -i <鍵>` で入る時だけ、AWS のコンソールで「マイIP」の行を一時的に足し、終わったら消す。

### 安全な確認コマンド(このリポジトリの bridge/scripts/ を使う)
```bash
cd /opt/argus && sudo git pull        # スクリプト取得(初回)
bridge/scripts/check_opend_status.sh      # OpenDバージョン/ポート/プロセス(マスク済み)
bridge/scripts/check_bridge_status.sh     # argus-bridge状態+直近ログ(マスク済み)
bridge/scripts/safe_opend_process_view.sh # プロセス表示(資格情報を必ずマスク)
bridge/scripts/safe_public_bridge_status.sh  # 公開ステータス(どこからでも可)
bridge/scripts/check_reboot_readiness.sh  # 再起動してよいか(自動起動・ポート・スワップ)
systemctl is-active opend argus-bridge    # 2行とも active
```
**生の `ps aux | grep OpenD` をドキュメントやチャットに貼らないこと** —
ログインID などの起動引数が見られるため、マスク無しの出力は使わない。

### 記憶したパスワードが切れた時(自動ログインに失敗する時)
moomoo の公式 FAQ のとおり、記憶したパスワードには期限がある。切れると OpenD はログインできず、
ブリッジの状態の `openDStatus` が connected でなくなる。その時は手で一度ログインし直す。
1. 市場時間外を選ぶ。`sudo systemctl stop opend`
2. `screen -S opend_login` → 実行ディレクトリで `./OpenD`
3. アカウント → パスワード → 「記憶するか」に **Y**(入力は日本語入力を切って英数で。パスワードは画面に出ない)
4. 図形/SMS認証が出たら下の手順。`Login successful` が出たら、別の窓から
   `pkill -f '\./OpenD'` で止め(Ctrl+C は効かない)、`exit` で screen を出る
5. `sudo systemctl start opend` → `bridge/scripts/check_opend_status.sh`
6. 「Login failed ... N chances remained」は残りの回数。ID の打ち間違い(例 `.com`)を先に疑う

### 図形認証(graphic verification)の手順
- 画像の場所: `/home/ubuntu/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png`(中身は JPEG)
- **画像は短い時間で失効する。** 2026-10-24 に、ブラウザーの画面 → 文字(base64)→ チャット経由で
  数分かけて開いたら、10回続けて「incorrect」になった。**数秒で開ける方法を使う。**
1. (Mac から入る許可を足した上で)OpenD の画面で `req_pic_verify_code`
   (または `bridge/scripts/request_pic_verify_code.sh`)
2. Mac のターミナルで、すぐに取って拡大して開く:
   `ssh -i <鍵> ubuntu@52.195.168.61 'cat /home/ubuntu/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png' > ~/Desktop/pic.jpg && sips -s format png -z 204 510 ~/Desktop/pic.jpg --out ~/Desktop/pic.png >/dev/null && open ~/Desktop/pic.png`
3. 大文字と小文字で形が同じ字(C・S・W・X・Z・O・V など)が入っていたら、**入力せずに**
   `req_pic_verify_code` で取り替える(入力しなければ失敗の回数は増えない)
4. 見分けやすければ、すぐに `input_pic_verify_code -code=...`(最後に空白を入れない)。
   スクリプトなら `bridge/scripts/submit_pic_verify_code.sh`(サイレント入力)
5. **間違えたら古い画像は失効** — OpenD が自動で新しい画像を作るので、2から取り直す
6. 続けて何度も間違えたら止めて、30分〜1時間おく(moomoo の側で止められないように)

### SMS認証の手順
1. `bridge/scripts/request_sms_verify_code.sh`(`req_phone_verify_code`)
2. `bridge/scripts/submit_sms_verify_code.sh` — サイレント入力
   (`input_phone_verify_code -code=...`)
3. **SMSコード/図形コード/パスワードをチャットやドキュメントに絶対に貼らない**

### OpenDアップグレード・チェックリスト(10.11.7108で実証済みの経路・2026-10-24)
1. 最新版を公式の配布ページ(moomoo.com/download/OpenAPI)で確かめる
2. EC2 で直接取る: `wget https://softwaredownload.futunn.com/moomoo_OpenD_<版>_Ubuntu18.04.tar.gz`
3. `md5sum` が配布元の値(`curl -sI <URL>` の etag)と一致することを確かめる。違えば先へ進まない
4. 新しいディレクトリに展開する(古い版は消さずに残す)
5. `OpenD.xml` で ip=127.0.0.1 / api_port=11111 / `telnet_ip=127.0.0.1` / `telnet_port=22222` /
   auto_hold_quote_right=1(telnet の2行の `<!-- -->` を外す)
6. 市場時間外に、`sudo systemctl stop opend`(重複プロセス厳禁 — safe_opend_process_view.sh で確認)
7. 上の「記憶したパスワードが切れた時」の2〜4で、新しい版に手でログインして記憶させる
8. `/etc/systemd/system/opend.service` の WorkingDirectory を新しいディレクトリに替える →
   `sudo systemctl daemon-reload && sudo systemctl start opend`
9. USスナップショット手動テスト(下記) → `ret=0` を確認
10. `safe_public_bridge_status.sh` で bridgeProcess=ok / usRealtimeStatus=ok を確認
11. **JPN Stocks権限が Normal/LV1+ になるまで `ARGUS_DISABLE_JP_QUOTES=1` を外さない**

USスナップショット手動テスト(再起動の直後は重いので5分ほどおいてから):
```bash
python3 - <<'PY'
from moomoo import OpenQuoteContext
qc = OpenQuoteContext(host="127.0.0.1", port=11111)
ret, df = qc.get_market_snapshot(["US.NVDA", "US.TSLA"])
print("ret=", ret)   # 0 = OK
qc.close()
PY
```

### 残存リスク(正直に)
- 記憶したパスワード(ログインの鍵)は `~/.com.moomoo.OpenD/` の中にある。このホストの
  ubuntu / root ユーザーはそれでログインできる。SSH の入口が境界。
- 記憶には期限がある。切れたら手でのログインが要る(上の手順)。
- 万一パスワードや認証コードがチャット等へ露出したら、**即パスワード変更+ARGUSトークン/HMACローテーション**
  (7/3-4 で実施済みの手順)。2026-10-24 にもパスワードを変更済み。

### 過去バージョンの記録(履歴)
- 10.7.6718: 7/3障害時の旧バージョン(ディスク満杯+SMS要求+JP権限喪失が複合)
- 10.8.6818: 2026-07-04アップグレード(Mac から `moomoo_OpenD_latest.tar.gz` を scp)・図形認証→ログイン成功→US LV3確認。
  screen の中で手で起動し、パスワードを起動の引数で渡していた(10.10 から設定ファイルにパスワードを書けない)
- 10.11.7108: 2026-10-24 更新・systemd(opend.service)で自動起動・記憶したパスワードで自動ログイン

## 再起動(リブート)安全ランブック — 2026-10-24 改訂

**現状の結論: 準備の確認が「準備OK」なら、市場時間外に再起動してよい。** 2026-10-24 に
opend.service を入れて再起動し、OpenD とブリッジが自動で戻ることを確かめた。
「System restart required」表示だけを理由に急いで再起動しないこと(市場時間外を選ぶ)。

**2026-10-24 の教訓:** スワップ(`/swapfile`)が手で有効にされていただけで `/etc/fstab` に無く、
再起動で消えた。メモリ 0.5GB だけで OpenD のログインと読み込みが重なり、SSH も応答しなくなった
(AWS のコンソールから再起動し、`/etc/fstab` に登録して解消)。準備の確認でスワップも見る。

### 再起動前チェックリスト(全て満たすまで再起動しない)
0. `bridge/scripts/check_reboot_readiness.sh` の判定が「準備OK」(自動起動・ポート・スワップ・秘密ゼロ)
1. 市場時間外である(US場中の再起動はリアルタイム停止に直結)
2. `bridge/scripts/check_opend_status.sh` が connected
3. `bridge/scripts/check_bridge_status.sh` が active
4. 認証コード受信手段(SMS/アプリ)が手元にある(記憶したパスワードが切れていた時に備える)
5. US-only設定(no-jp-quotes.conf)がそのまま — 再起動をJP有効化の機会にしない

### 再起動後チェックリスト
1. **5分ほど待ってから**入る(起動の直後は OpenD のログインと読み込みで重い)
2. 軽い確認から: `free -m`(Swap が 1023 前後)・`systemctl is-active opend argus-bridge`(2行とも active)
3. OpenDポート確認: `bridge/scripts/check_opend_status.sh`
   (127.0.0.1:11111 / 22222 がLISTENか — 生のps/pgrepは使わない: 引数に資格情報が乗るため)
4. ログインの確認: USスナップショット手動テストで `ret=0`。入れていなければ `screen -r opend` で様子を見て、
   上の「記憶したパスワードが切れた時」の手順(SMS/図形認証はチャットに貼らない)
5. 公開状態: `bridge/scripts/safe_public_bridge_status.sh`
   (bridgeProcess=ok / usRealtimeStatus=ok / jpRealtimeStatus=disabled。週末は openDStatus=unknown が正常)
6. SSH が応答しない時は、AWS のコンソールの「インスタンスを再起動」(「停止」「終了」は押さない)

## JPメンテナンス復旧ランブック — v12.0.5(サポート確認済みメンテナンスからの復旧)

**前提の事実(2026-07-06・moomooサポート正式回答):**
- 日本株API相場情報サービスのメンテナンスが、OpenD APIの JP snapshot /
  ORDER_BOOK(JP.5803等)に影響している(現在 ret=-1)。
- 日本株フル板はアプリ内で契約済み。**契約済みなら追加申込は現時点で不要**。
- 復旧時期は未定。**復旧後はOpenDの再起動・再ログインが必要**。
- アプリ/ブリッジのコード変更では直らない。復旧まで US-only + JP代替データを維持。

### Step 1 — moomooのメンテナンス完了を待つ
- 完了告知またはサポートの確認が取れるまで何もしない(このランブックの以降の
  手順は実行しない)。焦って再試行を繰り返さないこと。

### Step 2 — 安全な時間帯を選ぶ
- できるだけ市場時間外(JST 15:30以降〜翌朝、または週末)に作業する。
  ザラ場中の作業はUSリアルタイム供給を巻き込むリスクがある。

### Step 3 — OpenDを安全に再起動・再ログイン
- 手順は上の「OpenD 10.8.6818 運用ランブック」の再起動/認証手順に従う。
- **SMS認証が要求される場合がある**(SMS認証チェックリスト参照)。
- **図形認証(graphic verification)が要求される場合がある**(同上参照)。
- **SMS認証コード・パスワード・パスフレーズはチャットやチケット等に貼らないこと。**
  認証はEC2上のOpenD操作の中だけで完結させる(SSHが資格情報の境界)。
- **EC2自体の再起動はしない**(REBOOT SAFETYがrebootSafe=trueになるまで非推奨)。

### Step 4 — JP APIの再テスト(すべてret=0を確認)
- JP.5803 snapshot → **ret=0**
- JP.8058 snapshot → **ret=0**
- JP.9984 snapshot → **ret=0**
- 板情報を使う場合: JP.5803 ORDER_BOOK → **ret=0**
- 1つでも ret=-1 なら Step 6 へ(US-onlyのまま・積極的な再試行はしない)。

### Step 5 — ret=0確認後のみ: US-only解除(下の復帰手順)
- アプリのData Quality「JP REALTIME READINESS」が復帰準備OKを表示してから、
  下の復帰手順を実行し、mode=full / jpRealtimeStatus=ok /
  lastJPQuotePushAt が非null / usRealtimeStatus=ok を確認する。

### Step 6 — 失敗した場合
- US-onlyへ戻す(下のロールバック手順)。JP代替データ(J-Quants/Yahoo)は
  そのまま動き続けるので判断機能は失われない。
- メンテナンス継続の可能性があるため、再試行を繰り返さずサポート回答を待つ。

### 復帰条件(すべて満たすまでUS-onlyを外さない)
- moomoo側のメンテナンス完了(告知またはサポート確認)
- OpenDを再起動・再ログイン済み
- EC2の権限テストで JP.5803 / JP.8058 / JP.9984 のsnapshotが **ret=0**
- 板情報を使う場合は JP.5803 の ORDER_BOOK も **ret=0**
- OpenD connected / bridge active

### 復帰手順(条件成立後のみ)
1. `sudo mv /etc/systemd/system/argus-bridge.service.d/no-jp-quotes.conf ~/no-jp-quotes.conf.bak`
2. `sudo systemctl daemon-reload`
3. `bridge/scripts/restart_argus_bridge.sh`
4. `bridge/scripts/safe_public_bridge_status.sh` で mode=full / jpRealtimeStatus=ok を確認
5. アプリのData Quality「JP REALTIME READINESS」で JP push 実測を確認

### ロールバック(ret=-1 / No permissionで失敗した場合)
1. `sudo mv ~/no-jp-quotes.conf.bak /etc/systemd/system/argus-bridge.service.d/no-jp-quotes.conf`
2. `sudo systemctl daemon-reload`
3. `bridge/scripts/restart_argus_bridge.sh`
4. `bridge/scripts/safe_public_bridge_status.sh` で mode=us_only に戻ったことを確認

※ 本ランブックのコマンドは秘密値を一切表示しない。OpenDの起動引数を含む
生の `ps`/`pgrep` は使わないこと(`safe_opend_process_view.sh` を使う)。

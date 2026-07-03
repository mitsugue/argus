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

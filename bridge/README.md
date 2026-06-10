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

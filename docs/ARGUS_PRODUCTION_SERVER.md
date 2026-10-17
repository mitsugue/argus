# ARGUS 本番サーバ移行計画(v12.2.9 準備 — 未適用)

## 現状
- Render Start Command: `python scanner.py`(Flask開発サーバ・threaded)
- Renderログに開発サーバ警告が出る(機能上は稼働)

## 準備済み(このリポジトリに追加済み・本番未適用)
- `wsgi.py` — WSGIエントリ(`wsgi:app`)。import時に起動復元を1回確定(冪等)
- `gunicorn.conf.py` — **workers=1固定** / threads=8 / timeout=120 /
  graceful_timeout=30 / worker_exit で最終ローカルWAL flush(冪等)
- `requirements.txt` — `gunicorn==23.0.0`(pinned)

## 将来のRender Start Command(オーナー操作でのみ切替)
```
gunicorn -c gunicorn.conf.py wsgi:app
```

## なぜ workers=1 か(変更禁止)
ARGUSはスケジューラ(ミッション台帳)・運用ジャーナルWAL・起動復元・soak状態を
プロセス内メモリ+/tmp WALで保持する。複数workerにすると:
- スケジューラ/ジャーナルがworker毎に分裂し、冪等キーが別メモリで重複判定不能
- soak/復元状態がworker間で不一致
これらの複数worker安全性は**未実証** — 実証されるまで1 workerを固定する。

## 切替手順(未実施 — v12.2.9マージ・soak完了後にオーナーが実施)
1. v12.2.9がmainへマージされ、デプロイ+build-scoped soak完了を確認
2. Render → Settings → Start Command を上記コマンドへ変更(env変更なし)
3. Deploy live後に `/healthz`(liveness=200)と `/readyz`(readiness=200)を確認
4. Data Quality `serverRuntime.productionReadinessStatus =
   production_wsgi_single_worker` を確認
5. 異常時は Start Command を `python scanner.py` に戻す(即ロールバック)

## healthz / readyz
- `/healthz` = プロセスliveness(200のみ・build SHA付き)
- `/readyz` = 運用readiness(復元完了まで503 → readyで200)。
  RenderのHealth Check Path変更は任意・本タスクでは未変更。

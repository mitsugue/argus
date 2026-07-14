# -*- coding: utf-8 -*-
"""ARGUS v12.2.9 — Gunicorn本番設定(準備のみ・Render Start Command未変更)。

安全原則:
- workers=1 固定: スケジューラ/WAL/復元が状態フル — 複数workerは
  スケジューラ重複・in-memory状態分裂が未実証のため禁止。
- threads: Flask app は threaded=True 相当の並行GETに耐える設計
  (書き込みは冪等キー/単調sequenceで保護)。
- graceful shutdown: worker終了時に最終ローカルWAL flush(冪等)。
- ログ: アクセスログにquery文字列由来の秘密が乗らないようredacted運用
  (ARGUSはURLに秘密を載せない設計だが、念のためアクセスログは無効)。
"""
import os

bind = "0.0.0.0:" + str(os.environ.get("PORT", "10000"))
workers = 1                 # 変更禁止: 複数workerは安全性未実証(v12.2.9)
threads = 8
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = None            # 秘密/私的情報がログへ乗る面を最小化
errorlog = "-"
loglevel = "warning"


def worker_exit(server, worker):    # noqa: ARG001
    """graceful shutdown: 最終ローカルWAL flush(安全時のみ・冪等)。"""
    try:
        import scanner
        scanner._graceful_shutdown()
    except Exception:
        pass

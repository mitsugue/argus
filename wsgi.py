# -*- coding: utf-8 -*-
"""ARGUS v12.2.9 — 本番WSGIエントリポイント(準備のみ・未デプロイ)。

将来のRender Start Command(オーナー操作でのみ切替・本タスクでは変更しない):
    gunicorn -c gunicorn.conf.py wsgi:app

1 worker構成が前提: スケジューラ/WAL/復元は状態フルのため、複数workerは
安全性未実証(gunicorn.conf.pyで構造的に1へ固定)。
"""
import scanner
from scanner import app  # noqa: F401  (gunicornが参照するWSGI callable)

scanner._SERVER_RUNTIME.update({"serverType": "gunicorn_wsgi",
                                "workers": 1,
                                "startupMode": "wsgi_import"})
# 起動復元はimport時に1回確定(冪等 — 既にready/テスト文脈なら何もしない)
scanner._startup_bootstrap()

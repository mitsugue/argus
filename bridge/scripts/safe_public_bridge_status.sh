#!/usr/bin/env bash
# どこからでも安全: 公開ブリッジ状態(セグメント別・秘密なし)を表示。
set -uo pipefail
BACKEND="${ARGUS_BACKEND:-https://argus-backend-3j2m.onrender.com}"
echo "== GET $BACKEND/api/argus/bridge/status =="
if curl -sf --max-time 20 "$BACKEND/api/argus/bridge/status" | python3 -m json.tool; then
  echo "OK"
else
  echo "NG: 取得失敗"
fi

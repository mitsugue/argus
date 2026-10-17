#!/usr/bin/env bash
# 図形認証コードを送信する。コードは silent 入力(画面・ログ・履歴に残さない)。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_redact.sh"; source "$DIR/_telnet.sh"

read -r -s -p "図形認証コード(表示されません): " CODE; echo ""
if [ -z "$CODE" ]; then echo "NG: コードが空です"; exit 1; fi
RESP="$(opend_cmd "input_pic_verify_code -code=$CODE" 5 | redact)"
unset CODE
echo "$RESP" | grep -viE 'code=' | head -6
if echo "$RESP" | grep -qiE 'success|成功'; then
  echo "OK: 図形認証成功"
elif echo "$RESP" | grep -qiE 'fail|error|wrong|invalid'; then
  echo "NG: 認証失敗 — 画像が失効した可能性。request_pic_verify_code.sh で取り直してください。"
else
  echo "結果不明 — check_opend_status.sh でログイン状態を確認してください。"
fi

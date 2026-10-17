#!/usr/bin/env bash
# SMS認証コードを送信する。コードは silent 入力(画面・ログ・履歴に残さない)。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_redact.sh"; source "$DIR/_telnet.sh"

read -r -s -p "SMS認証コード(表示されません): " CODE; echo ""
if [ -z "$CODE" ]; then echo "NG: コードが空です"; exit 1; fi
RESP="$(opend_cmd "input_phone_verify_code -code=$CODE" 5 | redact)"
unset CODE
echo "$RESP" | grep -viE 'code=' | head -6
if echo "$RESP" | grep -qiE 'success|成功|login'; then
  echo "OK: SMS認証を送信しました。check_opend_status.sh でログイン状態を確認してください。"
else
  echo "結果不明/失敗 — request_sms_verify_code.sh で再送してください。"
fi

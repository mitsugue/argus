#!/usr/bin/env bash
# SMS認証コードの送信を要求する(登録済み電話番号へ届く)。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_redact.sh"; source "$DIR/_telnet.sh"

echo "== req_phone_verify_code 送信 =="
opend_cmd 'req_phone_verify_code' 3 | redact
echo ""
echo "スマホに届いたコードは submit_sms_verify_code.sh で入力(画面に出ません)。"
echo "⚠ SMSコードをチャット(ChatGPT/Claude等)やドキュメントに絶対に貼らないこと。"

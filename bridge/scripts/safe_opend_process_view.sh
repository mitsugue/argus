#!/usr/bin/env bash
# OpenD/ブリッジのプロセス表示(資格情報を必ずマスク)。
# 生の ps/pgrep を直接叩かず、常にこのスクリプトを使うこと。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_redact.sh"
echo "== processes (login_account/login_pwd/token/secret/hmac/auth/password はマスク済み) =="
ps -eo pid,etime,cmd 2>/dev/null | grep -Ei 'opend|moomoo_push|argus' | grep -v grep | redact
echo ""
echo "注意: ローカルのroot/ubuntuユーザーはマスク前の引数を見られます(残存リスク)。"

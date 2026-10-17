#!/usr/bin/env bash
# OpenDの生死・バージョン・ポートを安全に確認する(秘密は一切表示しない)。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_redact.sh"; source "$DIR/_telnet.sh"

echo "== OpenD ports (127.0.0.1 のみで待受けているか) =="
ss -ltn 2>/dev/null | grep -E ':(11111|22222)\b' || echo "NG: 11111/22222 が待受けていません(OpenD停止?)"

echo ""
echo "== OpenD version (telnet banner) =="
BANNER="$(opend_cmd '' 2 | redact)"
if echo "$BANNER" | grep -qi 'version'; then
  echo "$BANNER" | grep -i 'version' | head -2
  echo "OK: OpenD telnet 応答あり"
else
  echo "NG: telnet 22222 からバージョン応答なし"
fi

echo ""
echo "== OpenD process (REDACTED — 引数の資格情報はマスク) =="
pgrep -af -i opend 2>/dev/null | redact || echo "NG: OpenDプロセスが見つかりません"

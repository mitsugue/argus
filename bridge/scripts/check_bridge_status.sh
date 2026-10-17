#!/usr/bin/env bash
# argus-bridge(systemd)の状態と直近ログを安全に確認(全出力をredact)。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_redact.sh"

echo "== systemctl status argus-bridge =="
systemctl status argus-bridge --no-pager -l 2>&1 | redact | head -20

echo ""
echo "== 直近ログ(30行・REDACTED) =="
journalctl -u argus-bridge -n 30 --no-pager 2>&1 | redact

echo ""
if systemctl is-active --quiet argus-bridge; then
  echo "OK: argus-bridge is active"
else
  echo "NG: argus-bridge is NOT active"
fi

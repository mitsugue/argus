#!/usr/bin/env bash
# argus-bridge を安全に再起動し、成功シグナルを確認する。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/_redact.sh"

echo "== restart argus-bridge =="
sudo systemctl restart argus-bridge
sleep 8
if systemctl is-active --quiet argus-bridge; then
  echo "OK: service active"
else
  echo "NG: service NOT active"; journalctl -u argus-bridge -n 20 --no-pager | redact; exit 1
fi
echo ""
echo "== 直近ログ(REDACTED) =="
journalctl -u argus-bridge -n 12 --no-pager 2>&1 | redact
echo ""
if journalctl -u argus-bridge -n 40 --no-pager 2>&1 | grep -qE 'pushed http=200 accepted=[0-9]+'; then
  echo "OK: push成功を確認 (pushed http=200)"
else
  echo "…push成功行がまだ見えません(市場時間外なら heartbeat のみで正常)。"
fi
echo ""
echo "== 公開ステータス =="
"$DIR/safe_public_bridge_status.sh" | head -30

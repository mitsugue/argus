#!/usr/bin/env bash
# ARGUS ops — send ONE command to the OpenD telnet console (127.0.0.1:22222)
# and print the (redacted) response. Local-only by design.
OPEND_TELNET_HOST="${OPEND_TELNET_HOST:-127.0.0.1}"
OPEND_TELNET_PORT="${OPEND_TELNET_PORT:-22222}"
opend_cmd() {
  local cmd="$1" waitsec="${2:-3}"
  exec 3<>"/dev/tcp/${OPEND_TELNET_HOST}/${OPEND_TELNET_PORT}" || {
    echo "NG: OpenD telnet ${OPEND_TELNET_HOST}:${OPEND_TELNET_PORT} に接続できません"; return 1; }
  printf '%s\r\n' "$cmd" >&3
  timeout "$waitsec" cat <&3 || true
  exec 3<&- 3>&- 2>/dev/null || true
}

#!/usr/bin/env bash
# v12.0.3 — EC2再起動の準備状況を秘密ゼロで判定する(EC2上で実行)。
# 生のps/pgrepは使わない(起動引数に資格情報が乗るため)。出力に資格情報は出ない。
set -u

ok=0; warn=0
say() { printf '%s\n' "$*"; }
pass() { say "  ✅ $*"; }
fail() { say "  ❌ $*"; warn=1; }
unknown() { say "  ❓ $*"; warn=1; }

say "=== ARGUS reboot readiness (secrets-free) ==="

# 1) bridge systemd
if systemctl is-enabled argus-bridge >/dev/null 2>&1; then
  pass "argus-bridge: enabled(自動起動あり)"
else
  fail "argus-bridge: enabled ではない(sudo systemctl enable argus-bridge)"
fi
systemctl is-active argus-bridge >/dev/null 2>&1 \
  && pass "argus-bridge: active" || fail "argus-bridge: 停止中"

# 2) OpenD systemd(提案ユニット)
if systemctl list-unit-files 2>/dev/null | grep -q '^opend\.service'; then
  if systemctl is-enabled opend >/dev/null 2>&1; then
    pass "opend.service: enabled(自動起動あり)"
  else
    fail "opend.service: 存在するが enabled ではない"
  fi
else
  unknown "opend.service: 未デプロイ(OpenDは手動運用) → 再起動するとOpenDは自動復帰しません"
fi

# 3) OpenDポート(プロセス引数を見ずにポートだけ確認)
for p in 11111 22222; do
  if ss -ltn 2>/dev/null | grep -q "127\.0\.0\.1:$p"; then
    pass "OpenD port $p: LISTEN (127.0.0.1)"
  else
    fail "OpenD port $p: 応答なし"
  fi
done

# 4) OS再起動要求
if [ -f /var/run/reboot-required ]; then
  say "  ⚠️ System restart required: あり(ただし下の判定がOKになるまで再起動しない)"
else
  pass "System restart required: なし"
fi

# 5) 判定
say ""
if [ "$warn" -eq 0 ]; then
  say "判定: 再起動準備OK。実施は市場時間外に、bridge/README.md の再起動前後チェックリストに従うこと。"
  say "     (OpenD再ログインでSMS/図形認証が要る可能性に備え、受信手段を手元に。)"
else
  say "判定: まだ再起動しないでください。上の❌/❓を解消してから再実行。"
  say "     OpenD自動起動が未デプロイの間は、再起動=OpenD手動ログイン作業が必ず発生します。"
fi

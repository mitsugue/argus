#!/usr/bin/env bash
set -euo pipefail

BASE="${ARGUS_BACKEND_URL:-https://argus-backend-3j2m.onrender.com}"

systemctl is-enabled --quiet argus-mission-tick.timer
systemctl is-active --quiet argus-mission-tick.timer
systemctl list-timers argus-mission-tick.timer --no-pager
curl --fail --silent --show-error --max-time 30 "${BASE}/healthz" >/dev/null
curl --fail --silent --show-error --max-time 30 "${BASE}/readyz" >/dev/null
curl --fail --silent --show-error --max-time 30 \
  "${BASE}/api/argus/cost-policy" | python3 -c \
  'import json,sys; d=json.load(sys.stdin); assert d.get("mode")=="DETERMINISTIC" and not d.get("automaticAiEnabled"); print("DETERMINISTIC=true AI_AUTO=false")'
journalctl -u argus-mission-tick.service -n 4 --no-pager \
  | sed -E 's/(X-ARGUS-ADMIN-TOKEN|ARGUS_ADMIN_TOKEN)=[^ ]+/<redacted>/g'

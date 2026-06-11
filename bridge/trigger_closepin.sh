#!/usr/bin/env bash
# ARGUS closepin-v1 — fire the close-pin workflow at the EXACT time (14:30 JST)
# from the always-on EC2. Same PAT/env as trigger_ledger.sh.
#
# Install (after trigger_ledger.sh is set up):
#   crontab -e   ->   30 5 * * 1-5  /home/ubuntu/argus/bridge/trigger_closepin.sh
set -eu
ENV_FILE="${ARGUS_TRIGGER_ENV:-$HOME/argus-trigger.env}"
# shellcheck disable=SC1090
source "$ENV_FILE"
LOG="${ARGUS_TRIGGER_LOG:-$HOME/argus-trigger.log}"

if curl -sf -X POST \
    -H "Authorization: Bearer $GH_WORKFLOW_PAT" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/mitsugue/argus/actions/workflows/closepin-pin.yml/dispatches" \
    -d '{"ref":"main"}' > /dev/null; then
  echo "$(date -u +%FT%TZ) closepin triggered" >> "$LOG"
else
  echo "$(date -u +%FT%TZ) closepin trigger FAILED (check PAT)" >> "$LOG"
fi

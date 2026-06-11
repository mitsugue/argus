#!/usr/bin/env bash
# ARGUS cron-reliability-v1 — fire the prediction-ledger workflow at the EXACT
# time from the always-on EC2 (GitHub's own schedule queue runs hours late on
# busy days; observed 2-3.5h on 2026-06-11).
#
# Setup (one-time):
#   1. Create a FINE-GRAINED GitHub PAT: github.com/settings/personal-access-tokens
#      -> Generate new token -> Repository access: ONLY mitsugue/argus
#      -> Permissions: Actions = Read and write  (nothing else)
#   2. On the EC2:  echo 'GH_WORKFLOW_PAT=github_pat_XXXX' > ~/argus-trigger.env
#                   chmod 600 ~/argus-trigger.env
#   3. Install the cron entry (EC2 clock is UTC; 07:05 UTC = 16:05 JST):
#      crontab -e   ->   5 7 * * 1-5  /home/ubuntu/argus/bridge/trigger_ledger.sh
#
# The workflow itself dedupes: if this trigger already recorded today, the
# delayed GitHub-schedule run exits without touching the ledger.
set -eu
ENV_FILE="${ARGUS_TRIGGER_ENV:-$HOME/argus-trigger.env}"
# shellcheck disable=SC1090
source "$ENV_FILE"
LOG="${ARGUS_TRIGGER_LOG:-$HOME/argus-trigger.log}"

if curl -sf -X POST \
    -H "Authorization: Bearer $GH_WORKFLOW_PAT" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/mitsugue/argus/actions/workflows/prediction-ledger.yml/dispatches" \
    -d '{"ref":"main"}' > /dev/null; then
  echo "$(date -u +%FT%TZ) ledger triggered" >> "$LOG"
else
  echo "$(date -u +%FT%TZ) trigger FAILED (check PAT expiry/permissions)" >> "$LOG"
fi

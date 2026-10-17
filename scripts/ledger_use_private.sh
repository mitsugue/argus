#!/usr/bin/env bash
# Point this checkout's ledger operations at the owner's private repository
# (owner decision 2026-10-17: nothing internal stays in the public repository).
#
# The ledger steps keep their own git commands ("origin", "HEAD:ledger"); this
# replaces the remote URL and the credential actions/checkout stored for
# github.com with the private-repository key. The key travels only as an HTTP
# header, masked in the log, never in a URL. Without the key the step fails.
set -euo pipefail
: "${LEDGER_TOKEN:?ARGUS_PRIVATE_LEDGER_TOKEN is not registered for this repository}"
BASIC=$(printf 'x-access-token:%s' "$LEDGER_TOKEN" | base64 | tr -d '\n')
echo "::add-mask::${BASIC}"
git config --local --unset-all 'http.https://github.com/.extraheader' || true
git config --local 'http.https://github.com/.extraheader' "AUTHORIZATION: basic ${BASIC}"
git remote set-url origin "https://github.com/mitsugue/argus-l2b-private.git"
echo "ledger remote: private repository"

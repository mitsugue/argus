#!/usr/bin/env bash
set -euo pipefail

: "${ARGUS_EXPECTED_SHA:?ARGUS_EXPECTED_SHA is required}"
: "${ARGUS_PUBLIC_URL:?ARGUS_PUBLIC_URL is required}"
: "${ARGUS_WARM_PROFILE_DIR:?ARGUS_WARM_PROFILE_DIR is required}"
: "${ARGUS_ACCEPTANCE_OUT:?ARGUS_ACCEPTANCE_OUT is required}"

ARGUS_ACCEPTANCE_MODE=seed node scripts/public-market-acceptance.mjs
node scripts/warm-profile-contract.mjs sanitize-validate \
  "$ARGUS_WARM_PROFILE_DIR" "$ARGUS_EXPECTED_SHA"

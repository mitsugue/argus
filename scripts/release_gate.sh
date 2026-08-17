#!/bin/bash
# ARGUS Release Gate (v12.2.5) — 完全緑+クリーンツリーの正確なSHAだけが適格。
# 「pushしてからテスト」は禁止 — このスクリプトが緑を出すまでpushしない。
# manifestは artifacts/(gitignore済み)に生成 — 生成物がツリーを汚さない。
set -u
cd "$(dirname "$0")/.."
# The release gate must not make a clean checkout dirty merely by importing
# repository modules.  Keep Python caches outside the release contract rather
# than weakening the worktree cleanliness check.
export PYTHONDONTWRITEBYTECODE=1
mkdir -p artifacts
GATE_LOG_DIR=$(mktemp -d "${TMPDIR:-/tmp}/argus-release-gate.XXXXXX")
trap 'rm -rf "$GATE_LOG_DIR"' EXIT
PY_LOG="$GATE_LOG_DIR/pytest.log"
TS_LOG="$GATE_LOG_DIR/typecheck.log"
BUILD_LOG="$GATE_LOG_DIR/build.log"
SHA=$(git rev-parse HEAD)
SHORT=$(git rev-parse --short HEAD)
FRONTEND_VERSION=$(python3 -c "import json;print(json.load(open('web/package.json'))['version'])")
BACKEND_VERSION=$(python3 -c "import json;print(json.load(open('backend-version.json'))['version'])")
PRODUCT_VERSION=$(python3 -c "import argus_release_identity as i; v=i.product_version(); assert v; print(v)")
# Capture both sides of the gate.  Pre-existing dirt must fail, and any dirt
# created by a test/build must also fail.  artifacts/ remains the sole ignored
# release-output location.
DIRTY_BEFORE=$(git status --porcelain | wc -l | tr -d ' ')
PY=fail; TS=fail; BUILD=fail
python3 -m pytest -q -p no:cacheprovider >"$PY_LOG" 2>&1 && PY=pass
TESTCOUNT=$(grep -aoE '[0-9]+ passed' "$PY_LOG" | tail -1)
(cd web && npm run lint >"$TS_LOG" 2>&1) && TS=pass
(cd web && DEPLOY_BASE=/argus/ npm run build >"$BUILD_LOG" 2>&1) && BUILD=pass
DIRTY_AFTER=$(git status --porcelain | wc -l | tr -d ' ')
DIRTY=$DIRTY_AFTER
[ "$DIRTY_BEFORE" -le "$DIRTY" ] || DIRTY=$DIRTY_BEFORE
ELIGIBLE=true
[ "$PY" = pass ]    || ELIGIBLE=false
[ "$TS" = pass ]    || ELIGIBLE=false
[ "$BUILD" = pass ] || ELIGIBLE=false
[ "$DIRTY" = "0" ]  || ELIGIBLE=false   # 汚れたツリーは不適格(妥協なし)
REASONS=""
[ "$PY" = pass ]    || REASONS="$REASONS tests_failed"
[ "$TS" = pass ]    || REASONS="$REASONS typecheck_failed"
[ "$BUILD" = pass ] || REASONS="$REASONS build_failed"
[ "$DIRTY" = "0" ]  || REASONS="$REASONS dirty_tree($DIRTY files)"
cat > artifacts/release_manifest.json <<EOF
{"productVersion": "$PRODUCT_VERSION",
 "frontendVersion": "$FRONTEND_VERSION", "frontendBuildSha": "$SHA",
 "backendVersion": "$BACKEND_VERSION", "backendBuildShaCandidate": "$SHA",
 "commitSha": "$SHA", "commitShaShort": "$SHORT", "dirtyFiles": $DIRTY,
 "testResult": "$PY", "testCount": "${TESTCOUNT:-0}",
 "typecheckResult": "$TS", "buildResult": "$BUILD",
 "generatedAt": "$(date -u +%FT%TZ)",
 "failureReasons": "$(echo $REASONS | xargs)",
 "eligibleForDeploy": $ELIGIBLE}
EOF
echo "release-gate: sha=$SHORT dirty=$DIRTY py=$PY ts=$TS build=$BUILD eligible=$ELIGIBLE"
[ "$ELIGIBLE" = true ]

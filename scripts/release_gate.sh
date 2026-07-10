#!/bin/bash
# ARGUS Release Gate (v12.2.4) — 完全緑の正確なSHAだけがデプロイ適格。
# 「pushしてからテスト」は禁止 — このスクリプトが緑を出すまでpushしない。
set -u
cd "$(dirname "$0")/.."
SHA=$(git rev-parse --short HEAD)
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
PY=fail; TS=fail; BUILD=fail
python3 -m pytest -q >/tmp/gate_py.log 2>&1 && PY=pass
TESTCOUNT=$(grep -oE '[0-9]+ passed' /tmp/gate_py.log | head -1)
(cd web && npm run lint >/tmp/gate_ts.log 2>&1) && TS=pass
(cd web && DEPLOY_BASE=/argus/ npm run build >/tmp/gate_build.log 2>&1) && BUILD=pass
ELIGIBLE=false
[ "$PY" = pass ] && [ "$TS" = pass ] && [ "$BUILD" = pass ] && [ "$DIRTY" != "0" -o "$DIRTY" = "0" ] && ELIGIBLE=true
[ "$PY" = pass ] || ELIGIBLE=false
cat > release_manifest.json <<EOF
{"version": "$(python3 -c "import json;print(json.load(open('web/package.json'))['version'])")",
 "commitSha": "$SHA", "dirtyFiles": $DIRTY,
 "testResult": "$PY", "testCount": "${TESTCOUNT:-0}",
 "typecheckResult": "$TS", "buildResult": "$BUILD",
 "generatedAt": "$(date -u +%FT%TZ)",
 "eligibleForDeploy": $ELIGIBLE}
EOF
echo "release-gate: sha=$SHA py=$PY ts=$TS build=$BUILD eligible=$ELIGIBLE"
[ "$ELIGIBLE" = true ]

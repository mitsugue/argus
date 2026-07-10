#!/bin/bash
# ARGUS Release Gate (v12.2.5) — 完全緑+クリーンツリーの正確なSHAだけが適格。
# 「pushしてからテスト」は禁止 — このスクリプトが緑を出すまでpushしない。
# manifestは artifacts/(gitignore済み)に生成 — 生成物がツリーを汚さない。
set -u
cd "$(dirname "$0")/.."
mkdir -p artifacts
SHA=$(git rev-parse HEAD)
SHORT=$(git rev-parse --short HEAD)
# クリーンツリー判定を最初に行う(artifacts/はgitignoreで除外される)
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
PY=fail; TS=fail; BUILD=fail
python3 -m pytest -q >/tmp/gate_py.log 2>&1 && PY=pass
TESTCOUNT=$(grep -oE '[0-9]+ passed' /tmp/gate_py.log | head -1)
(cd web && npm run lint >/tmp/gate_ts.log 2>&1) && TS=pass
(cd web && DEPLOY_BASE=/argus/ npm run build >/tmp/gate_build.log 2>&1) && BUILD=pass
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
{"version": "$(python3 -c "import json;print(json.load(open('web/package.json'))['version'])")",
 "commitSha": "$SHA", "commitShaShort": "$SHORT", "dirtyFiles": $DIRTY,
 "testResult": "$PY", "testCount": "${TESTCOUNT:-0}",
 "typecheckResult": "$TS", "buildResult": "$BUILD",
 "generatedAt": "$(date -u +%FT%TZ)",
 "failureReasons": "$(echo $REASONS | xargs)",
 "eligibleForDeploy": $ELIGIBLE}
EOF
echo "release-gate: sha=$SHORT dirty=$DIRTY py=$PY ts=$TS build=$BUILD eligible=$ELIGIBLE"
[ "$ELIGIBLE" = true ]

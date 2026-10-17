# ARGUS Frontend Display Truth — Frontend-Only Release

This release is intentionally limited to the static GitHub Pages frontend.

## Deployment invariants

```text
backendDeploy=false
RenderRestart=false
preserveBackendSoak=true
commitSubjectSuffix=[skip render]
```

The production backend identity must remain unchanged before and after the
Pages deployment:

```text
backendSha=e66680d2c999b6cc881611d85b2c43c2a36e26dc
backendBoot=2026-07-27T09:05:36.438481+09:00
backendSoakId=soak-e66680d-99407148
backendSoakStartedAt=2026-07-27T00:07:25Z
backendRestartCount=0
```

## Included

- exact ETF names instead of index-only headline labels;
- ETF / STOCK instrument badges;
- EOD / T-1 / UNKNOWN freshness labels;
- provider, `asOf`, and age;
- explicit separation of LIVE QUOTE from ANALYSIS;
- fail-closed UNKNOWN handling for missing truth fields;
- no conversion of missing prices to zero;
- compatibility with old backend payloads.

## Excluded

- `scanner.py`;
- `bridge/moomoo_push.py`;
- backend LiveQuote contract changes;
- bridge telemetry changes;
- `backend-version.json`;
- any backend deploy, Render restart, or bridge restart.

## Release gate

Publish to GitHub Pages only after required pull-request checks pass. After
Pages reports success, verify the public screen with a cache-busted URL and
read the production backend identity again using public GET endpoints. Any
change in SHA, boot time, Soak ID, Soak start time, or restart count fails this
frontend-only release.

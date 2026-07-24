# A.R.G.U.S. release-plane contract

## Independent identities

| Plane | Version source | Build SHA source | Deploy authority |
|---|---|---|---|
| Frontend | `web/package.json` | GitHub Pages workflow `github.sha` | `.github/workflows/deploy-pages.yml` |
| Backend | `backend-version.json` | Render `RENDER_GIT_COMMIT` | `render.yaml` build filter |

The public-URL acceptance artifact combines these independently observed
coordinates. The backend must not infer the live Pages SHA from its own
checkout.

## Backend-sensitive paths

`render.yaml` uses Render's documented `buildFilter.paths` allowlist. The list
is mirrored and regression-tested in `scripts/deploy_scope.py`. A matching main
commit deploys immediately because PR checks have already passed; waiting for
all main checks would create a cycle with public acceptance, which waits for the
new backend. Backend Python, runtime entry points, dependencies, bridge code,
backend version, runtime seed, and the shared frontend API type directory
trigger a backend deployment.

Frontend implementation, CSS, frontend-only tests/build configuration, and the
Guide do not match that allowlist. They deploy through Pages without restarting
the Render process. `render.yaml` is the documented exception: Render always
processes a Blueprint file change regardless of build filters.

## Soak

- Frontend-only: backend SHA and Soak ID remain unchanged; heartbeat continues.
- Backend-sensitive: Render deploys only after checks pass; the previous Soak
  remains history and the first valid natural heartbeat starts the new build's
  Soak.

## Confirmed incident retained

On 2026-07-24, the frontend-only v13.2.1 merge `8f13904` triggered a Render
backend deployment because no build filter existed. The process restarted,
`soak-f664101-fd0d32b6` was marked `superseded`, and the new
`soak-8f13904-30411910` began at the first valid natural heartbeat. Production
read-only evidence showed `restartCount=0` after that boot, two natural
heartbeats, and source `ec2_systemd`; the supersession record is not rewritten.
The v13.2.2 filter closes the triggering configuration defect.

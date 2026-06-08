# A.R.G.U.S.

**Autonomous Risk and Global Uncertainty Scanner** — a personal
action-decision engine for daily investing. Not a chart app, not a
visual toy: it classifies the current market environment into action
categories and tells you, within ten seconds, what today's call is,
what the risk is, why, what to touch, what to avoid, and what to wait
for next.

- **Live app:** https://mitsugue.github.io/argus/
- **Backend API:** https://argus-backend-3j2m.onrender.com

A.R.G.U.S. does not predict the future. It classifies current market
conditions and organizes possible action categories based on risk
signals. Every action card answers three questions: what is the action,
why, and what would change it.

## Design direction

Calm dark-navy financial command center — Bloomberg Terminal + Linear +
Raycast + Stripe Dashboard. No HUD, no cyberpunk, no neon, no fake
terminal chrome. One dominant primary judgment; quiet supporting data.

**Intentional bilingual structure:** English chrome (navigation, section
names, action labels, system UI) + Japanese content (news, scanner
rationale, market commentary, user-facing investment reasoning). This
mix is by design, not a transition state.

## Structure

```
web/                  React + TypeScript + Vite frontend (deployed to GitHub Pages)
  src/
    routes/           Today / Action Alerts / Market Regime / Event Radar / Watchlist / Core Portfolio + AI Review (#review)
    components/        AppShell, NavRail, action/, dashboard/, regime/
    domain/actions.ts Single source of truth for action labels (color / tone)
    hooks/            useRatesSnapshot — wraps the live FRED endpoint, mock fallback
    mock/             Seed data (mock until each signal is wired to a real source)
    types/            action / dashboard / regime / watch
  .env.production     VITE_ARGUS_BACKEND_URL → live backend (not a secret)

scanner.py            Flask backend (Render). Serves /api/argus/* — FRED rates, ledger, picks.
argus_ledger.py       Prediction-calibration ledger (JSONL).
render.yaml           Render Blueprint (deploys from main, autoDeploy).
DEPLOY_BACKEND.md     Backend deploy + env-var guide.
```

## Action vocabulary

Tactical (individual stocks, satellites): `EXIT` · `TRIM` · `WAIT` ·
`WAIT FOR PULLBACK` · `BUY DIP` · `ADD` · `HOLD`.

Core (long-term index funds): `CONTINUE` · `GRADUAL ADD` ·
`DEFER LUMP SUM` · `NO SELL ACTION`.

## Frontend — develop & build

```bash
cd web
npm install
npm run dev          # local dev server (reads .env.local if present)
npm run lint         # tsc -b --noEmit
DEPLOY_BASE=/argus/ npm run build   # production build for GitHub Pages
```

The base path comes from `DEPLOY_BASE` (defaults to `/`); GitHub Pages
serves under `/argus/`. `VITE_ARGUS_BACKEND_URL` (in `.env.production`)
points the FRED Rates Snapshot at the live backend; if unset or
unreachable the UI degrades to a mock snapshot labelled `mock`.

## Backend

Flask app exposing `/api/argus/*`. The FRED rates endpoint
(`/api/argus/rates`) reads `FRED_API_KEY` server-side only — it is never
exposed to the frontend. Missing key or any fetch failure returns a mock
snapshot with `status: "mock"`. See `DEPLOY_BACKEND.md` for the full
environment-variable list and Render deploy steps.

## Data sources

| Signal | Source | Status |
| --- | --- | --- |
| US rates + VIX (10Y / 2Y / Real 10Y / VIX) | FRED (St. Louis Fed) | **live** |
| Everything else (alerts, watchlist, regime, events) | mock | pending real wiring |

Market visuals (Regime Matrix, Capital Rotation Board, Top Rotations)
are supporting evidence for the action labels — never trading signals by
themselves.

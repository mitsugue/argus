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
    hooks/            useRatesSnapshot / useJapanWatchlist — live backend endpoints, mock fallback
    mock/             Seed data (mock until each signal is wired to a real source)
    types/            action / dashboard / regime / watch
  .env.production     VITE_ARGUS_BACKEND_URL → live backend (not a secret)

scanner.py            Flask backend (Render). Serves /api/argus/* — FRED rates, J-Quants Japan watchlist, ledger, picks.
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
(`/api/argus/rates`) reads `FRED_API_KEY`, and the Japan watchlist
(`/api/argus/japan-watchlist`) reads `JQUANTS_API_KEY` (J-Quants V2, sent as
the `x-api-key` header) — both server-side only, never exposed to the
frontend. Missing key or any fetch failure returns a mock snapshot with
`status: "mock"`. See `DEPLOY_BACKEND.md` for the full environment-variable
list and Render deploy steps.

## Data sources

| Signal | Source | Status |
| --- | --- | --- |
| US rates + VIX (10Y / 2Y / Real 10Y / VIX) | FRED (St. Louis Fed) | **live** |
| Japan watchlist (price / change / volume / date, 7 names) | J-Quants V2 | **live** |
| US watchlist (price / change / volume / date, 4 names) | Twelve Data | **live** |
| Event Radar (official calendar: FOMC / BLS / BEA / BOJ + Treasury auctions) | Fed · BLS · BEA · BOJ · TreasuryDirect | **live / partial** |
| Action labels (watchlist stance / reason / risk / confidence / next condition) | Action Label Engine v0 (rule-based, internal) | **live** |
| Market Regime, Alerts, earnings, flow/news scanners | mock | pending real wiring |

Watchlist **action** labels come from the **Action Label Engine v0** — a
transparent, rule-based classifier over existing live data (price move + event
escalation + rates posture), served at `/api/argus/action-labels`. It is
deliberately conservative: it only emits `HOLD` / `WAIT` / `WAIT FOR PULLBACK`
in v0 (no `EXIT`/`TRIM`/`ADD`/`BUY DIP` until trend/flow/news confirmation
arrives), and degrades to neutral `HOLD` when a source is missing. No external
LLM and no invented VWAP/flow/news.

Event Radar (Phase 1) covers FOMC, BOJ, CPI, PPI, Employment Situation, JOLTS,
PCE / Personal Income and Outlays, GDP, and Treasury auctions. It is
schedule/risk-timing only — no forecast/actual/consensus interpretation yet.
Treasury auctions are fetched **live** from TreasuryDirect's JSON API; the
FOMC / BOJ / BLS / BEA dates are **official curated calendar data** (Fed, BOJ,
and the OMB/OIRA PFEI 2026 schedule) served directly rather than scraped —
refresh them for 2027. Top-level status is `partial` if the live auction fetch
fails. Today/CommandCenter's compact event preview still uses seed data — only
the Event Radar page is wired to live events.

Market visuals (Regime Matrix, Capital Rotation Board, Top Rotations)
are supporting evidence for the action labels — never trading signals by
themselves.

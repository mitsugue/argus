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
| AI Security Gate v1 + GPT-5.5 Pro Handoff (manual second opinion) | internal (no AI API calls yet) | **live (gate + handoff)** |
| Corporate Catalyst Layer (earnings / filings / news / disclosures) | SEC EDGAR + Finnhub + J-Quants (TDnet pending) | **live / partial** |
| Automated AI judgment (GPT-5.5 primary + Gemini double-check) | OpenAI + Gemini | pending (v8.10.x+) |
| Market Regime, Alerts, earnings, flow/news scanners | mock | pending real wiring |

Watchlist **action** labels come from the **Action Label Engine v0** — a
transparent, rule-based classifier over existing live data (price move + event
escalation + rates posture), served at `/api/argus/action-labels`. It is
deliberately conservative: it only emits `HOLD` / `WAIT` / `WAIT FOR PULLBACK`
in v0 (no `EXIT`/`TRIM`/`ADD`/`BUY DIP` until trend/flow/news confirmation
arrives), and degrades to neutral `HOLD` when a source is missing. No external
LLM and no invented VWAP/flow/news.

**v8.10.0 — AI Security Gate v1 + GPT-5.5 Pro Handoff.** This version adds the
*safety/cost infrastructure* for future expensive AI runs plus a manual Pro
review workflow. **No OpenAI/Gemini API call is made in this version** (the
OpenAI/Gemini judge code is kept dormant for a future version).

- **Security Gate v1** — `POST /api/argus/ai-judgment/run` is admin-gated
  (`X-ARGUS-ADMIN-TOKEN` == `ARGUS_ADMIN_TOKEN`; 401 if missing/wrong, 503 if the
  token isn't configured) and validates `AI_JUDGE_ENABLED`, a runtime soft lock
  (`AI_JUDGE_LOCKED` + repeated-failure auto-lock), a daily cap
  (`AI_JUDGE_MAX_RUNS_PER_DAY`, default 3), a minimum interval
  (`AI_JUDGE_MIN_INTERVAL_MINUTES`, default 30) and a country allow-list
  (`AI_JUDGE_ALLOW_COUNTRIES`, default JP, via CF-IPCountry). When the gate
  passes it returns `{"status":"ready", ... "AI execution not implemented in
  this version."}` — it does NOT call any model. `GET /api/argus/ai-judgment` is
  public/safe and returns `disabled` / `ai-judge-v1-pending`. Admin-only
  `GET /api/argus/security-status` and `POST /api/argus/security-unlock` manage
  the lock/limits. `send_security_alert()` logs alerts now and is structured for
  a Phase-2 Resend/SendGrid + signed "It was me / not me" links integration
  (`SECURITY_ALERT_EMAIL`/`PROVIDER`/`WEBHOOK`). The run ledger is in-memory
  (resets on dyno restart; move to persistent storage later if needed).
- **GPT-5.5 Pro Handoff** — `GET /api/argus/pro-handoff` aggregates the current
  ARGUS state (rates, events, both watchlists, action labels) into one
  copy-paste prompt for **manual** ChatGPT GPT-5.5 Pro review. The "Copy for
  GPT-5.5 Pro" button on the Watchlist copies it to the clipboard. This makes
  **no** API call, costs nothing, and exposes no secrets. (ChatGPT Pro
  subscription is separate from OpenAI API billing.)
- Future **v8.10.x+** can wire the automated GPT-5.5 API + Gemini double-check;
  expensive AI calls must stay backend-protected, cached, and rate-limited
  behind this gate. Env vars: `OPENAI_API_KEY`, `OPENAI_MODEL`,
  `GEMINI_API_KEY`, `GEMINI_JUDGE_MODEL`, `AI_JUDGE_ENABLED`,
  `AI_JUDGE_MAX_RUNS_PER_DAY`, `AI_JUDGE_MIN_INTERVAL_MINUTES`, `AI_JUDGE_LOCKED`,
  `AI_JUDGE_ALLOW_COUNTRIES`, `ARGUS_ADMIN_TOKEN`,
  `SECURITY_ALERT_EMAIL`/`PROVIDER`/`WEBHOOK`.

**v9.0.0 — Corporate Catalyst Layer.** `GET /api/argus/catalysts` surfaces the
company-specific events behind watchlist moves (earnings, filings, news,
disclosures) for the 11 watched names, and is folded into the Pro Handoff
prompt. It never fabricates — each source degrades to unavailable/partial
honestly, and it returns metadata only (no filing text, no long article bodies).
Sources:
- **SEC EDGAR** — official US filings (8-K / 10-Q / 10-K) via `data.sec.gov`,
  **no API key**; set `SEC_USER_AGENT` to `ARGUS/1.0 your-real-email` (SEC policy
  requires a descriptive UA with contact). Cached 6h.
- **Finnhub** — US earnings calendar (≤90d) + 7-day company-news *metadata* if
  `FINNHUB_API_KEY` is set, else unavailable. Cached ~45m.
- **J-Quants V2** — JP earnings calendar (`/v2/equities/earnings-calendar`, next
  business day) + latest financial disclosure (`/v2/fins/details`) per symbol if
  the plan supports it, else partial/unavailable. Cached 6h.
- **TDnet add-on** — `pending_addon` (off unless `JQUANTS_TDNET_ENABLED=true`);
  future optional enhancement for intraday Japan disclosures. No TDnet scraping.

Catalyst risk is conservative (earnings ≤3d → high/wait_for_event; ≤7d → medium;
recent 8-K ≤3d or news spike → caution; recent JP disclosure → post_event_review).
Env vars: `SEC_USER_AGENT` (recommended), `FINNHUB_API_KEY` (optional),
`JQUANTS_API_KEY` (existing), `JQUANTS_TDNET_ENABLED` (default false). Still
pending: Market Regime, Alerts, order-book/flow, earnings *interpretation*.

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

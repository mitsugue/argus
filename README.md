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
| US rates + VIX + HY OAS (10Y / 2Y / Real 10Y / VIX / HY OAS) | FRED (St. Louis Fed) | **live** |
| Japan watchlist (price / change / volume / date, 7 names) | J-Quants V2 | **live** |
| US watchlist (price / change / volume / date, 4 names) | Twelve Data | **live** |
| Crypto watchlist (BTC/ETH + any added coin, USD, 24h change) | CoinGecko `simple/price` (keyless, 10-min cache) | **live** |
| Today hero / "Today's call" pill (composed judgment) | action-labels + market-regime + events (rule-based composition) | **live** |
| Event Radar (official calendar: FOMC / BLS / BEA / BOJ + Treasury auctions) | Fed · BLS · BEA · BOJ · TreasuryDirect | **live / partial** |
| Action labels (watchlist stance / reason / risk / confidence / next condition) | Action Label Engine v0 (rule-based, internal) | **live** |
| Market Regime / Capital Rotation v1 (regime label / axes / rotation board / top rotations) | FRED macro + Twelve Data ETF proxies + JP breadth (rule-based, `regime-v1`) | **live / partial** |
| GPT-5.5 Pro Handoff (manual high-stakes second opinion) | manual copy-paste (no API call, no cost) | **live (manual)** |
| Integration health (provider configured/live/partial/missing) | `/api/argus/integrations` (`integrations-v1`, secret-free) | **live** |
| Corporate Catalyst Layer (earnings / filings / news / disclosures) | SEC EDGAR + Finnhub + J-Quants (TDnet pending) | **live / partial** |
| AI Judgment Layer v1 (automated second opinion) | GPT-5.5 primary + Gemini double-check (code path; needs Render keys + `AI_JUDGE_ENABLED` + admin run) | **disabled / missing_keys until configured** |
| Alerts scanner, earnings *interpretation*, order-book / flow / tape | mock | pending real wiring |

> **AI status is truthful, not flag-driven.** `aiJudgment` is **never** reported
> `live` merely because `AI_JUDGE_ENABLED=true`. Its status comes from real key +
> cache state: `disabled` (flag off) · `missing_keys` (enabled, no OpenAI/Gemini
> key) · `partial` (only one provider configured) · `no_cached_result` (keys
> present, no successful admin run yet) · `live` (a fresh cached admin-run result).
> The **GPT-5.5 Pro Handoff is manual copy-paste and makes no API call** — it is
> separate from ChatGPT Pro billing and from the OpenAI/Gemini API. The public
> frontend **never** triggers an expensive AI call (it reads cache only). See
> **Guide → API / Integration status** and the admin-only
> `/api/argus/ai-provider-status` (requires `X-ARGUS-ADMIN-TOKEN`).

**Market Regime / Capital Rotation v1** (`/api/argus/market-regime`, `regime-v1`)
is a transparent rule-based engine — **no OpenAI/Gemini, no prediction**. It reads
FRED macro (10Y/2Y/real/VIX + ICE BofA US HY OAS `BAMLH0A0HYM2`) and a focused
8-symbol Twelve Data ETF proxy universe (SPY/QQQ/IWM/XLK/XLU/GLD/TLT/HYG, ONE
batched `time_series` request, **6h cache** to stay credit-safe) plus JP watchlist
breadth, and emits a regime label (RISK_ON / RISK_OFF / CAUTIOUS / EVENT_WAIT /
MIXED), a Growth↔Defensive × Risk↔Duration matrix, a capital-rotation board, top
rotations, a rates backdrop, confidence, and honest data limitations. **ETF
rotation is a proxy for capital flow, not direct flow** — it is supporting
evidence, not a trading signal by itself. The regime feeds the Action Label Engine
(high-beta names lean WAIT under RISK_OFF / EVENT_WAIT) and the Pro Handoff.

Watchlist **action** labels come from the **Action Label Engine v0** — a
transparent, rule-based classifier over existing live data (price move + event
escalation + rates posture), served at `/api/argus/action-labels`. It is
deliberately conservative: it only emits `HOLD` / `WAIT` / `WAIT FOR PULLBACK`
in v0 (no `EXIT`/`TRIM`/`ADD`/`BUY DIP` until trend/flow/news confirmation
arrives), and degrades to neutral `HOLD` when a source is missing. No external
LLM and no invented VWAP/flow/news.

**v9.11.0 — moomoo bridge: real-time quotes + smarter notifications.** A small
bridge (`bridge/moomoo_push.py`, systemd-ready) runs NEXT TO the user's OpenD
(AWS, 24h) and POSTs real-time JP/US quotes to the admin-gated
`POST /api/argus/quote-push` (sanitized, capped, price-validated). Fresh pushes
(≤10 min) overlay J-Quants(T-1)/Twelve Data across ALL watchlist paths
(cache-safe `_overlay_pushed`; automatic fallback when the bridge stops; OpenD
port stays closed to the internet — the bridge talks to 127.0.0.1).
`/integrations` shows the bridge as live/stale by push freshness. Notifications:
digest text redesigned for the phone (emoji sections, short lines); morning
digest now runs twice (08:30 JST JP pre-open + 22:00 JST US pre-open); market
alerts add a stress-spike detector (backdrop→stress transition, VIX crossing
26 — catches black-swan REACTIONS within the hour; cause/headline detection is
the v9.12 candidate); all pushes carry a Click header that opens the app.

**v9.10.0 — Change-detection alerts + rule tests + rate limit + AI ping.**
**Alerts:** `market-alerts.yml` polls the digest hourly through JP+US sessions
(JST 7–24, weekdays) and pushes a ntfy notification ONLY on real change —
posture flip or a high-impact event entering its D-1/D window (state carried via
the Actions cache; first run seeds silently; same `NTFY_TOPIC` secret; bonus:
keeps the Render free dyno warm through market hours). **Tests:** `test_rules.py`
(17 pytest cases) locks the judgment core — rates/VIX thresholds, regime
momentum scaling + backdrop, action-label rules, symbol sanitization, freshness
lag, and the AI-truth state machine — and a new `ci.yml` runs backend tests +
frontend typecheck/build + a bundle secret-grep on every push. **Abuse guard:**
per-IP sliding-window rate limit on `/api/argus/*` (120/min default, 30/min for
cache-busting query requests; OPTIONS exempt; 429 JSON). **AI ping:** admin-only
`POST /api/argus/ai-provider-status/ping` makes a minimal "pong" call to OpenAI
and Gemini so a renewed key can be verified in one command without burning a
full judgment run (returns ok/error per provider; never key values).

**v9.9.0 — Judgment log + morning digest (the agent's first push).** ARGUS now
has memory and a voice. **Judgment log:** every LIVE/PARTIAL Today composition
is recorded device-locally (`argus.judgmentLog.v1`, one entry per JST date,
~180 entries; mock is never logged) and the Today page shows "what changed since
yesterday" plus a 7-day call strip — the foundation for future outcome tracking.
**Morning digest:** new `GET /api/argus/daily-digest` (`digest-v1`) composes a
notification-ready Japanese brief (posture/call/confidence, rates backdrop,
today's high-impact events, label highlights, top rotations — rule-based, no
LLM), and a GitHub Actions cron (`morning-digest.yml`, 07:15 JST Mon–Fri,
manual-run capable) pushes it via **ntfy.sh** (zero-signup push relay) when the
`NTFY_TOPIC` repo secret is set; without the secret it no-ops gracefully. The
digest contains market commentary only — no holdings, no personal data.

**v9.8.0 — User watchlist ⇔ engine + data-freshness honesty.** The engine no
longer watches a fixed 11-symbol list: `/japan-watchlist`, `/us-watchlist`, and
`/action-labels` accept the user's ACTUAL assets (`?symbols=` / `?jp=&us=`,
sanitized + capped — JP ≤ 20, US ≤ 8 to respect Twelve Data's 8-credits/min —
with bounded per-set caches). Symbols added in the UI now get live quotes AND
rule labels (names resolved from the J-Quants master; unknown symbols default to
the conservative high-beta class). Failed rows are OMITTED, never faked.
Freshness honesty: a label computed from a quote older than 7 days is damped
(confidence × 0.5) and prefixed 【価格データn日遅れ】 with
`supportingData.quoteDate/quoteLagDays`; the Watchlist shows an amber
`delayed Xw` pill instead of a green `live`, and mock rows render "—" instead of
plausible fake prices (Today's priority list uses live quotes only).

**v9.7.0 — Live Today hero + CoinGecko crypto.** The Daily Command Center is no
longer seeded: the hero judgment ("today's call" / risk / regime tags / summary /
reasons / touch-avoid / next condition), the sidebar "Today's call" pill, the
header Next-event chip, the priority watchlist (real prices + rule labels,
urgency-sorted), the event preview, and the core-fund preview are all **composed
live** from `/action-labels` + `/market-regime` + `/events` + watchlist quotes
(`lib/todayCall.ts`, rule-based, no hand-written judgment, no LLM; the page shows
its live/partial/mock phase honestly and degrades to a neutral cautious call).
Core funds flip CONTINUE → DEFER_LUMP_SUM under EVENT_WAIT/RISK_OFF (accumulation
itself never stops on market mood). New keyless **`GET
/api/argus/crypto-watchlist?ids=…`** (CoinGecko `simple/price`, sanitized ids,
10-min per-ids cache) gives BTC/ETH and any added coin live USD prices + 24h
change in the Watchlist strategy cards; quote-less crypto stays an honest manual
placeholder. `/integrations` now reports CoinGecko configured/live.

**v9.6.0 — Integration Health + AI provider truth status.** Adds a secret-free
public **`GET /api/argus/integrations`** (`integrations-v1`) summarizing every
provider's `configured` / `runtimeStatus` (live / partial / missing / disabled /
pending) for FRED, J-Quants, Twelve Data, Finnhub, OpenAI, Gemini, CoinGecko, and
moomoo — plus an admin-only **`GET /api/argus/ai-provider-status`**
(`X-ARGUS-ADMIN-TOKEN`; 401/503 if missing) returning safe booleans only (no key
values, no model call). **Fixes the AI-status truth bug:** `aiJudgment` is no
longer marked `live` from `AI_JUDGE_ENABLED` alone — a single source of truth
(`_ai_judgment_truth`) reports `disabled` / `missing_keys` / `partial` /
`no_cached_result` / `live` from real key + cache state, and the Pro Handoff, the
public `/api/argus/ai-judgment` GET, the AI Review sheet, and the new **Guide →
API / Integration status** panel all use it. No OpenAI/Gemini call is made on any
public page load.

**Next API roadmap:** (1) v9.7.0 CoinGecko crypto live (BTC/ETH); (2) v9.8.0
Alerts Scanner live (events + regime + catalysts + action labels); (3) v9.9.0
moomoo / VWAP / order-flow validation (local OpenD feasibility, JP/US coverage,
no cloud secret leakage); (4) v10.0 Portfolio Exposure Layer (holdings, quantity,
average cost, valuation, unrealized P/L, allocation); (5) v10.1 What-if Simulator
(*scenario analysis* — "if I add ¥X to asset Y, how do exposure/risk/scenario P/L
shift?" — framed as scenarios, NOT deterministic prediction).

**v9.5.0 — Live Market Regime + Capital Rotation scoring.** `GET
/api/argus/market-regime` (`regime-v1`) replaces the mock Market Regime / Capital
Rotation source with a transparent **rule-based** engine (no OpenAI/Gemini, no
prediction). It scores a focused 8-symbol Twelve Data ETF proxy universe
(SPY/QQQ/IWM/XLK/XLU/GLD/TLT/HYG, one batched `time_series` request, **6h cache**,
credit-safe) by capped 1d/5d/20d momentum, reads FRED macro (10Y/2Y/real/VIX +
ICE BofA US HY OAS), and uses JP watchlist breadth as a temporary Japan proxy. It
emits a regime label (RISK_ON / RISK_OFF / CAUTIOUS / EVENT_WAIT / MIXED), a
Growth↔Defensive × Risk↔Duration matrix, a capital-rotation board, top rotations,
a rates backdrop, confidence, source statuses, and honest data limitations. The
Market Regime page, Today's Top Rotations preview, Action Label Engine (high-beta
names lean WAIT under RISK_OFF / EVENT_WAIT), and the Pro Handoff all consume it.
**ETF rotation is a proxy for capital flow, not direct flow.** Stale v9.2 "not
built yet" / "Capital Rotation is mock" review text was removed.

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
**v9.1.0 — Automated AI Judgment Layer v1 (code path; disabled until keys are
configured).** The `GPT-5.5` (OpenAI, primary reviewer) + `gemini-2.5-flash`
(independent double-check, with Google Search grounding when the client supports
it) judge code reviews the rule-based labels behind the Security Gate. The
conservative arbiter always preserves the rule label, blocks
`ADD`/`BUY DIP`/`EXIT`/`TRIM` unless both models support it, and defers to Gemini
on high-severity disagreement; malformed/failed model output degrades to partial
/ rule-only. **This path is NOT live unless** `OPENAI_API_KEY` + `GEMINI_API_KEY`
are set in Render, `AI_JUDGE_ENABLED=true`, and an admin run has succeeded — until
then its status is `disabled` / `missing_keys` / `no_cached_result` (see v9.6.0).
**GPT-5.5 Pro is NOT used automatically** — it stays the manual
Copy-for-GPT-5.5-Pro Handoff path (and a future Deep Scan).
- The public frontend reads the **cached** judgment only via
  `GET /api/argus/ai-judgment` (never triggers a model call; returns `disabled`
  or `no_cached_result` when there's nothing cached).
- A fresh run is **admin-only**: `POST /api/argus/ai-judgment/run` with header
  `X-ARGUS-ADMIN-TOKEN`, behind the gate (enabled flag, daily limit, min
  interval, country allow-list, soft lock). Example (placeholder token only):
  ```
  curl -X POST https://argus-backend-3j2m.onrender.com/api/argus/ai-judgment/run \
    -H "X-ARGUS-ADMIN-TOKEN: <ARGUS_ADMIN_TOKEN>"
  ```
- Cost control: `AI_JUDGE_ENABLED` gates execution; `AI_JUDGE_MAX_RUNS_PER_DAY`
  and `AI_JUDGE_MIN_INTERVAL_MINUTES` are enforced; results cache for
  `AI_JUDGE_CACHE_TTL_MINUTES`. API keys live ONLY in Render env. ChatGPT Pro
  subscription is separate from OpenAI API billing; the GPT-5.5 Pro Handoff is
  free because it is manual copy-paste.
- Env vars: `OPENAI_API_KEY`, `OPENAI_MODEL` (default gpt-5.5), `GEMINI_API_KEY`,
  `GEMINI_JUDGE_MODEL` (default gemini-2.5-flash), `AI_JUDGE_ENABLED`,
  `AI_JUDGE_MAX_RUNS_PER_DAY`, `AI_JUDGE_MIN_INTERVAL_MINUTES`,
  `AI_JUDGE_CACHE_TTL_MINUTES`, `AI_JUDGE_LOCKED`, `AI_JUDGE_ALLOW_COUNTRIES`,
  `ARGUS_ADMIN_TOKEN`, `SECURITY_ALERT_EMAIL`/`PROVIDER`/`WEBHOOK`.

**v9.2.0 — Unified asset Watchlist + Strategy Cards.** The Watchlist is now a
unified asset manager (tabs: All / Japan / US / Core / Crypto) over a single
asset model.
- **Japanese names:** JP stocks display Japanese names. **8058 = 三菱商事**
  (Mitsubishi Corporation) — NOT 三菱重工 (Mitsubishi Heavy Industries = 7011);
  symbol↔name is curated, never guessed. The backend serves `nameJa`.
- **Add / remove / reorder** with localStorage persistence (key
  `argus.assets.v1`, cap 50). *Limitation: per browser/device — no cross-device
  sync yet (would need auth + a database).* Reorder is via up/down controls in
  the All tab (stable on mobile).
- **Strategy Cards v1:** each row expands (accordion) to a rule-based strategy —
  strategy / why / what to wait for / what changes it / catalyst note / data
  limitations / "updated Xm ago", derived in the frontend from
  `/action-labels` + watchlist quotes + `/catalysts`. A **Rescan** button
  refreshes the rule-based snapshots (stale-while-revalidate; **no OpenAI/Gemini
  call**). Scenario probabilities (1–3 trading days, sum to 100) are
  decision-support, NOT prediction.
- **Core / funds:** Core/manual funds live in the same model (calm core labels
  CONTINUE / GRADUAL ADD / DEFER LUMP SUM / NO SELL ACTION); no live NAV claimed
  for non-listed mutual funds. The Core Portfolio route is unchanged.
- **Crypto:** addable as an asset type; v9.2.0 keeps it **manual / pending**
  (no live CoinGecko quotes yet — a backend `/crypto-watchlist` is a v9.x hook).
- **Top Rotations "full board"** now lands cleanly on the Capital Rotation Board
  on mobile (anchored target + deferred scroll). **Glossary / Guide** route added
  at the sidebar bottom (用語一覧 + 使い方, Japanese). Pro Handoff unchanged (no
  AI calls). Still pending: automated AI judgment run (admin/keys), live crypto,
  non-listed fund NAV, moomoo flow/order book, cross-device sync.

**v9.4.0 — Watchlist genre groups + drag reorder.** The Watchlist is now grouped
into labelled sections — **Japanese Stocks / US Stocks / Investment Trusts /
Crypto** (in that order, with spacing between groups; empty groups are hidden).
Reordering is drag-and-drop: each row has a ⋮⋮ handle (pointer + keyboard via
[@dnd-kit](https://dndkit.com/)) and reorder is scoped to within a genre, so a
drag never moves an asset across sections. Newly added assets float to the **top
of their genre** (smallest `sortOrder`). Order persists per device in
`localStorage` (`argus.assets.v1`). The old up/down buttons and tab bar are gone.

**v9.3.0 — Add-Asset symbol search.** The Add-Asset dialog now searches by name
or code and shows clickable candidates instead of requiring an exact symbol, via
a backend proxy (`GET /api/argus/symbol-search?market=JP|US|CRYPTO&q=…`, keys
server-side, read-only, 10-min per-query cache): JP = J-Quants listed-issue
master (`/v2/equities/master`, cached 24h, search by コード/社名 incl. CoNameEn);
US = Twelve Data `symbol_search`; Crypto = CoinGecko `search` (no key, returns
the coingecko id stored in the asset memo for future live quotes). Core/manual
funds stay manual entry. Degrades to empty results on failure.

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
pending: Alerts scanner, order-book/flow/tape, earnings *interpretation*
(Market Regime / Capital Rotation v1 is now live/partial — see v9.5.0).

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

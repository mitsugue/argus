# Tachibana live shadow production plane

## Isolation contract

Run Tachibana as a Render background worker named
`argus-tachibana-live-shadow`, in the existing Singapore Production
environment, on exactly one `0.5c-512mb` instance. A background worker has no
public or private inbound endpoint. It must not have a persistent disk, import
the scanner, receive Recovery environment variables, or access `/var/data`.

The worker start command is:

```text
python scripts/tachibana_live_sensor_service.py
```

The build command is:

```text
pip install -r requirements-tachibana.txt
```

This dedicated dependency file contains only Requests, Cryptography, and the
WebSocket client. It intentionally does not install the scanner, Moomoo,
Recovery, AI, Flask, or frontend dependency surfaces.

The service follows protected `main`. Previews are disabled. Only Tachibana
paths and its dedicated requirements file belong in its build filter.

## Required non-secret configuration

```text
ARGUS_TACHIBANA_ENABLED=true
ARGUS_TACHIBANA_SHADOW_ONLY=true
ARGUS_TACHIBANA_AUTHORITATIVE=false
ARGUS_TACHIBANA_WEBSOCKET_ENABLED=true
ARGUS_TACHIBANA_MAX_SYMBOLS=3
ARGUS_TACHIBANA_SYMBOLS=8058,9984,5803
ARGUS_TACHIBANA_REQUESTS_PER_MINUTE=12
ARGUS_TACHIBANA_MAX_READ_ATTEMPTS=1
ARGUS_TACHIBANA_EVENT_RECONNECTS_PER_DAY=3
ARGUS_TACHIBANA_AUTH_ID_PATH=/etc/secrets/e_api_authid.txt
ARGUS_TACHIBANA_PRIVATE_KEY_PATH=/etc/secrets/e_api_private_key.pem
ARGUS_TACHIBANA_SINGLETON_PATH=/tmp/argus-tachibana-live-sensor.lock
```

The only secret files are `e_api_authid.txt` and `e_api_private_key.pem`.
Provision them through Render secret files from local paths. Never place their
contents in Git, environment variables, browser automation, command arguments,
build output, or logs.

## Runtime truth and acceptance

The host `flock` lease is held for the entire process lifetime. Render is also
fixed to one instance. EVENT reconnects are bounded to three per Tokyo day.
The provider's 05:35 service-availability boundary is not treated as live-market
readiness. The worker makes no Tachibana request before its 07:55 JST live
sensor boundary and keeps one healthy session across morning pre-open and the
09:00 execution transition. If that start window is operationally missed, the
same proof may instead span the official 12:05 afternoon pre-open and 12:30
afternoon execution transition. A confirmed `SESSION_EXPIRED` state can use at most
two delayed reauthentication attempts in a rolling 15-minute window. That is a
bounded recovery policy, not a once-per-day product constraint. Maintenance,
outside-hours, exhausted recovery, and other faults remain truthfully degraded
without an authentication or platform-restart storm.

The sensor emits only aggregate operational logs. It retains a bounded window
in memory and never persists raw frames or market values. The official JPX
order-acceptance phases are represented separately from execution phases:
morning `PREOPEN` begins at 08:00 and `AFTERNOON_PREOPEN` begins at 12:05.
`UNKNOWN` always fails closed. Acceptance requires both distinct stages:

Before PRICE/EVENT acceptance, the same authenticated session performs the
current official read-only MASTER inquiry `CLMStkGetDateZyouhou` and requires
exactly one day-key `001` row with a valid `sTheDay`. Provider calendar date,
packet date, SS/US effective time, and execution time remain separate evidence.

- `PREOPEN_BOOK_LIVE`: a verified current JPX date, advancing EVENT chronology,
  and a current-session bid/ask, quantity, or depth change in either the
  08:00–09:00 primary window or 12:05–12:30 fallback window; it does not require
  an execution-price, volume, turnover, or VWAP change;
- `EXECUTION_MARKET_LIVE`: after the corresponding 09:00 or 12:30 open, current
  observations for all configured symbols, post-open EVENT and trade-source
  timestamp progression, an observed execution-field change, independent
  current-source coverage for at least two of three symbols, and no
  unclassified cross-provider mismatch.

A connected WebSocket without packet progression remains unproven. The exact
official provider operation code is retained in secret-safe acceptance metadata
without translating an undocumented code into a stronger market semantic.
The same metadata retains only safe SS codes, whether their effective date was
current, per-key conflict state, and bounded field-degradation tokens. It never
retains a status frame or market value.

Authentication diagnostics retain only the HTTP status, safe `sCLMID`, numeric
`sResultCode`, official normalized reason, Ack-shape match, and whether all five
encrypted virtual-URL fields were present. They never retain `sResultText`, an
authentication ID, request body, encrypted/decrypted URL, key, or credential
hash. The live canary distinguishes `AUTH_SERVER_REJECTED_<RESULT_CODE>`,
`AUTH_SUCCESS_VIRTUAL_URLS_WITHHELD`, `AUTH_SUCCESS_DECRYPT_FAILED`,
`AUTH_HTTP_FAILED`, `AUTH_PROTOCOL_FAILED`, `AUTH_TIMEOUT`,
`AUTH_MAINTENANCE`, `AUTH_IP_REJECTED`, and `AUTH_LOCKED`. A successful Ack
with no virtual URLs is not an authentication rejection; current official
documentation identifies unread required documents as one possible cause.

The cross-validation policy is frozen before live observation. Execution
fields are current price, previous close, open, high, low, volume, and market
status only when both providers expose the same semantic; board scope adds
best bid/ask only when both providers expose those quote semantics. The trusted row must
be explicitly live, carry realtime evidence, and have a non-future source
timestamp no older than 20 minutes. At least two of three configured symbols
must be comparable; execution scope requires current price, while board scope
requires a bid or ask. Tolerances are one yen or
10 bp for independently sampled current price, exact-to-1-bp daily
reference/OHLC values, and one board lot or 2% for volume. A classified
feed-delay difference is acceptable only within 50 bp for price/OHLC or 5% for
volume. Missing fields reduce coverage; they are never treated as a match.
Mismatch classes are `TIMESTAMP_SKEW`, `DELAY_DIFFERENCE`,
`SESSION_DIFFERENCE`, `FIELD_SEMANTICS`, `CORPORATE_ACTION`, `MARKET_STATE`,
`PROVIDER_ERROR`, `NORMALIZATION_ERROR`, and `UNKNOWN`; only no mismatch or a
bounded delay-only result is acceptable.

Eligibility is scope-specific. Board validation requires the verified provider
calendar date, a current FD/quote packet, and PREOPEN or OPEN phase; it compares
bid/ask only when the trusted provider exposes the same semantics. Execution
validation additionally requires OPEN, a current-date execution timestamp, and
execution-field progression. A current FD packet can remain truthful current
board data while unresolved phase keeps execution validation and SDA promotion
ineligible.

Tachibana remains `SHADOW_NON_AUTHORITATIVE`. It has no public route, no order
surface, no scanner integration, and no path to SDA authority or Japanese
execution.

## Deferred merge, deployment, and production acceptance

Do not execute this sequence until the local dual-phase gate passes:

1. Fetch protected `main`, rebase the isolated branch, and rerun the full
   backend suite plus frontend lint/build. Reconfirm the diff contains only the
   Tachibana slice and these operations notes.
2. Push the isolated branch, open a review, require all protected checks, merge
   through the repository's protected path, and fetch the resulting immutable
   main commit and tree identities.
3. Create exactly one Singapore `0.5c-512mb` background worker in the existing
   Production environment. Use the build/start commands above, no disk, no
   inbound endpoint, and no `/var/data` access.
4. Upload the two secret files from their canonical local paths through the
   platform's secret-file mechanism. Secret contents must never enter a shell
   argument, environment value, browser form, Git object, or log.
5. Apply only the non-secret flags listed above. Confirm one instance,
   `SHADOW_NON_AUTHORITATIVE`, no execution capability, and no Recovery
   configuration inheritance before starting the worker.
6. Observe the worker's bounded `TACHIBANA_SENSOR_STATE` metadata until the
   same PREOPEN-to-corresponding-OPEN transition produces
   `TACHIBANA_PRODUCTION_ACCEPTANCE`. A connected socket alone is not a pass.

## v13.5.38 product integration boundary

The product consumes Tachibana through exactly one module,
`argus_tachibana_live.py` (`TachibanaLiveService`):

- lifecycle: one lazily started daemon thread runs the read-only
  `TachibanaLiveRuntime` inside the JPX cash window (07:55-15:31 JST, trading
  days) under the host singleton lease, with the bounded reauthentication
  budget (2 per 15 min) and a 300 s hold on any other failure — no retry
  storm, no start unless `ARGUS_TACHIBANA_ENABLED=true`;
- state: latest observation per configured symbol (at most three), no
  history, no raw frames, no persistence;
- projection: `current_evidence_safe()` — provenance `provider = TACHIBANA`,
  authority `SHADOW_NON_AUTHORITATIVE`, status one of `LIVE`, `DEGRADED`,
  `STALE`, `UNAVAILABLE`, `AUTH_FAILED`, `MAINTENANCE`, `DISABLED`. `LIVE`
  requires every configured symbol to carry a current `FRESH` price; a
  connected socket alone never reads `LIVE`.

Topology: the ARGUS backend is a single process (`python scanner.py`,
`workers = 1` policy), so the sensor is colocated in that process and the
evidence is read in-memory; there is no inter-process transport and no
public raw-data endpoint. The backend consumes the document through the
decision-evidence route as `marketView.japaneseLive`, and the Today market
view renders `TACHIBANA LIVE` (status + per-symbol price / change / VWAP /
bid-ask / freshness / provenance). The same seven evidence families are
re-labeled for the owner as `MARKET SIGNALS` (`SIG-01`..`SIG-07`) by
`argus_market_signals.py` with a count recomputed from the per-signal states.

Wiring status: `scanner.py` is under the Recovery admission pin, so the
three-line consumer wiring (import, lazy `ensure_started()` in the request
autostart hook, `"japaneseLive": argus_tachibana_live.current_evidence_safe()`
in the decision-evidence document) is delivered as a handoff patch and lands
when that pin is lifted. Until then the Today indicator truthfully renders
`UNAVAILABLE` (`未接続`). Production enablement additionally requires the two
Tachibana secret files on the backend service and `ARGUS_TACHIBANA_ENABLED=true`
(owner dashboard action; secrets never enter Git, env values, or logs).

## v13.5.39 EVENT recovery order and owner-visible LIVE

Live finding (2026-09-03 afternoon acceptance on `ab9951e7`): AUTH, Date,
PRICE, EVENT (8,510 frames, FD active, sequence and timestamp progression,
`PREOPEN_BOOK_LIVE = PASS`, execution progression) all passed; the session
then lost the socket and every reconnect failed at CONNECT within seconds
(1 s, 2 s, 4 s), exhausting the daily budget. The final REST logout also
failed with NETWORK, which points at a transport interruption, not a session
fault. The official contract keeps the virtual URLs valid across a socket
close and asks the client to wait for the previous disconnect to finish.

Recovery order now implemented in `TachibanaEventLifecycle.run`:

1. CONNECT failure while the EVENT host is unreachable (plain TCP probe to the
   public hostname only) → wait `outage_backoff_seconds` (30 s), never consume
   the reconnect budget, never re-authenticate; bounded by
   `outage_budget_seconds` (900 s) per run, then `EVENT_RECONNECT_EXHAUSTED`.
2. An established connection closed → wait `drain_wait_seconds` (5 s) for the
   provider's disconnect processing, then reconnect in the SAME session.
3. Consume one reconnect and back off 5 s → 60 s (jittered), bounded by
   `ARGUS_TACHIBANA_EVENT_RECONNECTS_PER_DAY`.
4. Re-authentication only on evidenced session invalidity
   (`SESSION_EXPIRED` from the provider), through the existing bounded
   2-per-15-minute budget in the service/runtime.

Owner-visible product (v13.5.39): the top command area renders
`MARKET SIGNALS  x / 7` with the seven `SIG-01..07` states from the real
projection (the SDA Seven Sign level stays as a secondary line). When the
decision-evidence document carries current Tachibana evidence
(`japaneseLive`, status `LIVE`/`DEGRADED`, a `FRESH` row with a ≤ 60 s
exchange timestamp), the JP watchlist row for that symbol is replaced by the
Tachibana observation (provider `tachibana`, `delayClass: LIVE`), so prices,
freshness labels, and non-LIVE warnings reflect the live source; all other
rows keep their truthfully labeled delayed source.

## Rollback

Rollback affects only the new background worker: suspend it, confirm its single
session is torn down and its in-memory URLs are erased, then delete the worker
if rollback is final. The merged files are inert while their enable flag is
false and have no scanner or public-route integration. Do not roll back the
existing backend, alter its environment, remove or edit `/var/data`, change any
Recovery service/timer/workflow, or start Formal Recovery. Verify the public
backend identity and all Recovery identities remain exactly as observed before
the Tachibana deployment.

## v13.5.40 — owner-visible cutover (slice 3)

- **No "mock" label.** The asset desk freshness word for an absent quote is
  `未取得` (`deskFormat.freshnessOf`). Production never renders the word
  "mock" to the owner; the frozen backend status value is unchanged.
- **JP realtime lamp follows Tachibana.** `useSystemHealth` overlays the
  backend `jp_realtime` lamp with the Tachibana evidence document
  (`applyTachibanaHealthOverlay`): LIVE → green `LIVE — Tachibanaから更新中（symbols）`,
  DEGRADED/STALE/MAINTENANCE → amber, AUTH_FAILED → amber with the auth
  boundary code, UNAVAILABLE → gray waiting. The logo beacon (`overall`) is
  recomputed from the lamps (worst-of; a `stopped` lamp elsewhere still
  dominates). A DISABLED or absent document leaves the backend lamp untouched,
  so the retired moomoo JP message can only be replaced by real evidence.
- **Auth boundary (slice 1).** `japaneseLive.authBoundary` +
  `secretFiles` (safe properties only: exists / regular / mode / size>0 /
  readable / platform-managed; never contents). Platform secret files under
  `/etc/secrets` are resolved through their symlink and accepted with read bits.
- **Asset Detail board.** The overlaid JP row carries `tachibana`
  (`TachibanaBoard`: price / VWAP / best bid+qty / best ask+qty / volume /
  exchange timestamp). The desk forwards it into `QuoteLite.tachibana`;
  Asset Detail's first viewport renders `立花ライブ(参考)` rows
  (`data-argus-contract="tachibana-board-v1"`, labelled 売買権限なし) and the
  data-limitation line says VWAP/板 are Tachibana evidence while 資金フロー
  stays 未取得. Absent fields render `—`, never a fabricated number.
- **Private key tolerance (slice 1b).** Production read both secret files
  after slice 1 but reported `AUTH_KEY_PARSE_FAILED` (`PRIVATE_KEY_INVALID`).
  `session.load_private_key` now tries, in order: the literal PEM, a
  normalized PEM (BOM/CRLF stripped, base64 body re-wrapped at 64 columns),
  bare base64 re-armored as PKCS#8 then PKCS#1, and raw DER; the result must
  still be an RSA key of 2048..4096 bits. `secretFiles.privateKey.keyShape`
  reports structure only (bytes, lineCount, crlf, bom, armored, beginLabel
  from a fixed label set, base64Body, parsed encoding, keyType, keySize) —
  never contents, never a hash.

## Recovery handoff (state after v13.5.40 / v13.5.41)

- Product surface is frozen at v13.5.41 (this PR). Tachibana LIVE is wired
  read-only through `argus_tachibana_live` (product) and the RECOVERY_ONLY
  scanner seam from PR #257 (`japaneseLive` at the decision-evidence
  document level, `_tachibana_live_autostart` once per process). Scanner
  and the other Recovery payload paths were not modified by v13.5.38–41.
- Production state at handoff: `ARGUS_TACHIBANA_ENABLED=true`; both Render
  secret files exist (symlinks, mode 0640, readable); the private key file
  content is not a key (`keyShape`: 63 bytes, one line, no armor, not
  base64). Until the owner re-uploads the PEM the boundary stays
  `AUTH_FAILED / AUTH_KEY_PARSE_FAILED` and the owner sees 認証失敗 truthfully.
- Recovery Smoke must not start before the owner has accepted both
  v13.5.40 (Tachibana cutover) and v13.5.41 (Events/News) on the real app.

## v13.5.42 — closed-session probe, CLOSED vocabulary, chart bootstrap

- **Closed-session probe.** Outside the JPX window the product boundary runs
  one bounded AUTH → DATE → PRICE → logout (`_run_closed_probe`), at most
  every 4 h on success and every 30 min after a failure. Evidence:
  `lastAuthResult`, `closedSessionProbe {at, result, stages}` (stage
  classifications only). Price baseline rows are retained with
  `marketStatus CLOSED`; status becomes **CLOSED** (provider proven, market
  closed) instead of UNAVAILABLE. No streaming, no reauth storm.
- **Owner vocabulary.** TACHIBANA LIVE card: 市場クローズ; JP realtime lamp:
  green `Tachibana 接続確認済 · 市場クローズ（symbols）`; glossary
  `tachibana_closed`. Asset Detail attaches the closed board as reference
  evidence without replacing the row's own price/provider (no false LIVE).
- **Chart bootstrap.** `argus_chart_bootstrap` (product module, started from
  the request autostart seam because scanner is Recovery-frozen) walks the
  existing asset-chart tick over every target once after the durable-state
  restore, using the tick's own bounded provider seed (J-Quants, 2 pages).
  Kill switch `ARGUS_CHART_BOOTSTRAP=0`. No public-GET fetches, no raw tick
  warehouse.
- **Chart current point.** Asset charts draw the Tachibana current price
  (LIVE when current within 60 s, CLOSED for the baseline) as a marker plus
  `現在値ソース: TACHIBANA`; the point never replaces the historical series.

## v13.5.43 — owner symbols resolve from the curated JP snapshot

- Production defect found after v13.5.42: the public read-only
  `/api/argus/japan-watchlist?symbols=…` (the mode the real app uses) serves
  only the per-symbol-set cache, which is filled solely by provider-fetching
  callers, so after hours it answers an EMPTY `mock` snapshot → the owner saw
  価格データ未取得 for 5803 although the curated snapshot carried its
  J-Quants EOD row. `useJapanWatchlist` now falls back to the curated
  snapshot and keeps only the requested symbols (`jpWatchFallback.ts`):
  status stays `delayed`/`mixed` (never live), uncovered symbols stay absent.
- TACHIBANA LIVE rows show 市場クローズ instead of STALE when the provider
  reports the market closed.

## v13.5.44 — boot warm, real signal conditions, ARGUS-derived valuation, owner rows

- **Root cause of cold signals/charts:** every SHO/asset feed is a process-local
  cache warmed only by cron paths (`institutional-intelligence/collect` from
  market-watch/caos-scan). caos-scan has not run since 2026-08-28 and each
  deploy wipes the caches, so production stayed cold (margin1570/nikkei/
  earnings = cold, owner symbols without market truth → 価格データ未取得).
- **Boot warm** (`argus_chart_bootstrap`, after the chart pass): `_sho_pit_inputs(warm=True)`
  at boot and every 4 h; interest-symbol daily history (`_jq_price_history`)
  for 5803 + curated + the JP codes the device already sent to public routes
  (decision-evidence subjects, supply-demand extras, watchlist hints; bounded
  24) every 10 min; ARGUS-derived valuation published to `argus_japan_valuation`.
- **Signal conditions:** D03 proxy relative strength > 0; D05 published net
  foreign flow > 0 (INFLOW); D06 VIX MACD(12/26/9) histogram < 0 — each
  labelled with `conditionRule` / `conditionLineage`. D04 uses the
  ARGUS-derived universe forward-PER (median <= 21x = SHO ladder top) when
  no licensed Nikkei EPS exists; `nikkeiOfficialPer: NOT_CLAIMED`. D07 reports
  **NOT_APPLICABLE** (new signal state 該当なし) when the statements feed is
  warm but holds no supported disclosure in the window.
- **Owner symbols:** the JP watchlist hook resolves symbols the curated list
  lacks from `/api/argus/price-history` (real EOD close, delayed/EOD, jquants;
  volume marked unavailable) once the boot warm has cached them.

## v13.5.45 — interest registry, curated/reference warm, per-issuer statements

- The decision-evidence subject cache expires in 120 s, so a single device
  request could miss the 10-minute warm cycle. The boot warm now scans the
  host caches every minute into a product-side registry (7-day TTL, bounded)
  and warms from the registry.
- Each cycle also warms the curated JP watch snapshot (the decision-evidence
  watch row and curated quotes read it; cold after every deploy) and the
  SIG-03 proxy histories (1321, SPY). With the 4-hourly SHO warm it fetches
  each interest issuer's latest `/fins/statements` rows (2 pages) so the
  ARGUS-derived valuation has forecast EPS beyond the 14-day SHO window.
- `japaneseLive.productBoot` exposes a bounded, symbol-free warm summary.

## v13.5.46 — per-issuer statements retry (SIG-04)

- Production after v13.5.45 showed `statementsFetched: 0`: `/fins/statements?code=`
  returns the issuer's full history and the 2-page bound raised
  `jquants_pagination_limit`, swallowed silently. The fetch now allows 8
  pages, runs for up to 6 pending issuers per 10-minute cycle until every
  interest issuer is covered (refreshed with the 4-hourly SHO warm), and
  records the last failure class (`statementsErrorClass`,
  `referenceErrorClass`) in `japaneseLive.productBoot`.

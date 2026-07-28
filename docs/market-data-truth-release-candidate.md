# ARGUS Market Data Truth — Release Candidate Contract

## Release boundary

This release candidate changes truth labelling and evidence collection. It does
not change trading behavior and it does not claim a new market-data entitlement.

It delivers:

- exact instrument labels for 1321, 1306, SPY, and QQQ;
- explicit instrument type, delay class, provider, `asOf`, and age;
- separation of `LIVE QUOTE` from daily-close `ANALYSIS`;
- runtime measurement of moomoo source timestamp freshness, split by market.

It does **not** guarantee:

- Japanese equities within 20 minutes;
- Japanese equities in realtime;
- US equities in realtime;
- official Nikkei 225, TOPIX, S&P 500, or Nasdaq index values.

Until a display/redistribution contract is proven, the four headline
instruments remain ETF proxies:

- `1321 日経225 ETF`
- `1306 TOPIX ETF`
- `SPY S&P 500 ETF`
- `QQQ Nasdaq 100 ETF`

## Three layers

### 1. Frontend display truth

`LiveQuote` is normalized client-side so an older backend payload cannot crash
the page or inherit a realtime claim. Missing or malformed evidence fails
closed:

| Input condition | Display result |
| --- | --- |
| missing `exchangeTs` | `UNKNOWN`, age unverified |
| missing entitlement | `unknown`; never used alone to prove LIVE |
| missing session | `UNKNOWN` session |
| date-only old cache | date-only `asOf`, no second-level age |
| stale cache | prior LIVE claim revoked to `UNKNOWN` |
| offline/mock | `OFFLINE` |
| malformed timestamp | timestamp discarded, `UNKNOWN` |
| `delayClass: LIVE` without proof | downgraded to `UNKNOWN` |

LIVE requires all of: `realtimeEvidence: true`, a parseable source timestamp,
and source age no greater than 60 seconds.

### 2. Backend LiveQuote contract

Each quote row can add these fields without breaking old clients:

```text
provider
instrumentType
sourceTimestamp
receivedAt
ageSec
transportAgeSec
delayClass
session
quoteRight
entitlement
realtimeEvidence
```

The backend computes source age from the venue/source timestamp. Transport age
only measures ARGUS's copy and cannot prove realtime. A public watchlist GET is
cache/bridge-only and does not fetch a provider.

Market-level classification is independent for JP and US:

- `LIVE`: source timestamp coverage is 100% and source-age p95 is at most 60s;
- `15m`: delayed quote right is reported, or source-age p50 is at least 600s;
- `EOD`: market session is closed;
- `UNKNOWN`: proof is incomplete or contradictory.

### 3. moomoo bridge telemetry

The bridge transports only public-safe timestamps, counts, and coarse error
classes. It never transports credentials, account identifiers, or raw provider
bodies.

After deployment, `/api/argus/moomoo-capability` exposes
`moomoo-runtime-evidence-v2`, with separate `markets.JP` and `markets.US`
objects. Each market records:

```text
market
symbols
quoteRight
sourceAgeP50Sec
sourceAgeP95Sec
sourceTimestampCoverage
staleCount
errors
lastErrorClass
verdict
```

Each symbol row records:

```text
market
symbol
quoteRight
sourceTimestamp
receivedTimestamp
sourceAgeSec
receivedAgeSec
session
stale
errors
entitlementVerdict
```

JP and US samples, percentiles, stale counts, and errors must never be pooled.

## Provider decision

No monthly price is inferred where the vendor requires a quote. “Contact
sales” is an unresolved commercial fact, not zero cost.

| Option | Achievable latency now | Symbols | Exact index coverage | Display rights | Monthly cost | Public web use | Implementation effort |
| --- | --- | --- | --- | --- | --- | --- | --- |
| moomoo JP | `UNKNOWN`; production entitlement is unavailable and runtime proof is absent | account-entitled JP instruments | no official index guarantee; ETFs only | account/API terms must be confirmed for public redistribution | not verified; entitlement-dependent | not approved until contract review | Medium |
| moomoo US | `UNKNOWN`; 15s push cadence is transport frequency, not source freshness | configured/account-entitled US instruments | ETFs such as SPY/QQQ, not official index values | account/API terms must be confirmed for public redistribution | not verified; entitlement-dependent | not approved until contract review | Low–Medium |
| licensed JP delayed vendor | contract target such as 15m/20m, only after timestamp proof | contract-defined JP universe | only if index rights are expressly included | delayed display and redistribution rights must be explicit | RFP/contact sales | possible only when expressly licensed | Medium |
| licensed JP/US index vendor | contract-defined realtime or delayed values | contracted indices | official Nikkei/TOPIX/S&P/Nasdaq values as licensed | external display/redistribution licence required | contact sales; typically separate index fees | possible only within licensed site/app scope | High |

Commercial and licence references:

- Nikkei Index licensing: <https://indexes.nikkei.co.jp/nkave/license/index.en.html>
- JPX TOPIX: <https://www.jpx.co.jp/english/markets/indices/topix/>
- JPX real-time values terms: <https://www.jpx.co.jp/english/markets/indices/realvalues/>
- S&P DJI data capabilities: <https://www.spglobal.com/spdji/en/documents/index-policies/index-data-capabilities-brochure.pdf>
- Nasdaq GIDS: <https://www.nasdaq.com/solutions/global-indexes/data/gids>
- Nasdaq Composite versus Nasdaq-100: <https://www.nasdaq.com/newsroom/nasdaq-composite-vs-nasdaq-100-what-investors-should-know>

## Release/deploy scope

The release candidate contains frontend, backend, and bridge changes. Frontend
deployment alone would not activate the new backend evidence fields. Backend
and bridge activation must wait for the current production soak to complete or
for explicit interruption approval.

**SOAK INTERRUPTION APPROVAL REQUIRED**

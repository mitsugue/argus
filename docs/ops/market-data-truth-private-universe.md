# Market data truth and private registered-symbol universe

## Authority and privacy

| Source | Authority | Server visibility | Bridge use |
|---|---|---|---|
| Owner portfolio | `argus.assets.v1` inside the client-encrypted vault | Ciphertext only; the server cannot enumerate positions | Not read or decrypted. A held/protected symbol must also be registered in Layer 2B to enter the bridge universe. |
| Owner watchlist / registration | Private Layer 2B `membership/latest.json` | Symbol, market, enabled flag, and non-monetary owner state only | Authenticated membership source. No quantity, cost, value, P/L, account, or note fields. |
| Mandatory market/macro set | `argus_market_universe.MANDATORY_CODES` | Repository configuration | Always merged ahead of private membership. |
| Emergency baseline | EC2 `PUSH_SYMBOLS` | Bridge-local environment | Preserved as an emergency/startup baseline; it is not the complete registered universe. |

The authenticated endpoint is
`GET /api/argus/bridge/private-symbol-universe`. Its response may contain private
symbols and therefore must never be proxied to a public client, logged, or copied
into heartbeat diagnostics. `verified=false` means the private membership could
not be read. The bridge then keeps its last verified set. An empty or unknown
response is never interpreted as complete coverage.

## Bounded synchronization

- Refresh interval: 600 seconds (10 minutes).
- Per-market defaults: 200 JP and 200 US; hard maximum 400 each.
- Normalization: canonical `JP.<listing>` / `US.<ticker>` codes only.
- Ordering: emergency baseline + mandatory symbols + registered membership,
  order-preserving and deduplicated, then capped independently by market.
- OpenD calls: US and JP are requested separately. A JP entitlement or service
  failure cannot suppress US quotes.
- JP suspension: membership remains registered while quote calls follow the
  existing bounded backoff. The fallback remains J-Quants EOD. moomoo resumes
  only after a successful JP quote probe.

## Public truth contract

`GET /api/argus/bridge/status` is aggregate-only. `transportStatus` proves that
the bridge/OpenD transport is recent; it does not prove either market is live.
`markets.us` and `markets.jp` independently report:

- status and provider;
- fallback provider where applicable;
- quote right / entitlement status;
- `exchangeAsOf` and backend `transportReceivedAt`;
- source age p50/p95;
- REALTIME / DELAYED / EOD / UNKNOWN freshness;
- configured, requested, returned, unavailable, stale, and missing-timestamp
  counts plus coverage percentage.

A stale or missing bridge heartbeat overrides any previous per-market `live`
status with `transport_unavailable`. A successful response with missing or old
exchange timestamps is not live. Partial symbol coverage is `partial`, never
silently promoted to full coverage.

## Deployment boundary

This contract is prepared as a Draft PR only during Checkpoint V2 Stage 1. It
does not change production `PUSH_SYMBOLS`, EC2, OpenD, bridge processes, Render,
or the active backend until a later explicit owner-approved merge and deploy.

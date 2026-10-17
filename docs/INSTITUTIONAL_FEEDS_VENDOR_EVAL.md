# ARGUS — Licensed Institutional Feed Vendor Evaluation (§25)

Status: **evaluation only — no vendor contracted, no purchase made.** Adapters in
`argus_licensed_feeds.py` are disabled (`NOT_CONFIGURED`) until a signed contract +
credentials + a successful runtime fetch flip them on. **No prices are stated below —
they must be obtained from each vendor's sales team.** No purchase without owner
approval.

## Candidates
| Vendor | Product | Why considered |
|---|---|---|
| Bloomberg | Event-Driven Feeds | lowest-latency machine-readable market-moving events |
| Bloomberg | Terminal Research | sell-side research aggregation (Terminal entitlement) |
| LSEG (Refinitiv) | Machine Readable News | tagged real-time news + analytics, strong entitlements |
| Dow Jones | Factiva AI News Feed | licensed full-text + AI-processing rights |
| RavenPack | News Analytics | entity/event analytics + sentiment, quant-friendly |

## Questions for vendor sales (ask every candidate)
1. Does the product support individual / internal personal use (not redistribution)?
2. Is machine-readable real-time delivery available (protocol/format)?
3. Are institutional research notes included? Analyst rating actions?
4. Are full texts included, or headlines/metadata only?
5. Can content be processed by an LLM (AI-processing rights)?
6. Can derived summaries be **stored**? Retention period?
7. Can results be **displayed** in a private personal app?
8. Redistribution restrictions?
9. Latency (event → delivery)?
10. API / protocol formats (REST, streaming, FIX, etc.)?
11. Historical search included? Depth?
12. JP-language + Japan-market coverage? Named JP analysts/brokers tagged?
13. Are named analysts and institutions tagged (entity IDs)?
14. Setup / one-time fees? Recurring fees? Minimum term?
15. Trial / demo available?

## Side-by-side scorecard (fill after demos — 1–5, higher = better)
| Criterion | Bloomberg EDF | Bloomberg Terminal | LSEG MRN | Factiva AI | RavenPack |
|---|---|---|---|---|---|
| Speed / latency | _ | _ | _ | _ | _ |
| Institutional-research coverage | _ | _ | _ | _ | _ |
| Japan coverage | _ | _ | _ | _ | _ |
| Machine readability | _ | _ | _ | _ | _ |
| AI-usage rights | _ | _ | _ | _ | _ |
| Display rights | _ | _ | _ | _ | _ |
| Implementation complexity (lower=better, invert) | _ | _ | _ | _ | _ |
| Total cost (obtain from vendor) | _ | _ | _ | _ | _ |
| Fit for ARGUS | _ | _ | _ | _ | _ |

## Integration readiness
`argus_licensed_feeds.py` already exposes the `LicensedNewsProvider` interface
(`connect / health / stream / fetch_since / normalize_item / capabilities /
usage_policy`). When a vendor is contracted: supply credentials, set
`contract_signed=True`, implement `fetch_since/normalize_item`, and set the matching
`SOURCE_RIGHTS[...]` access class from `usage_policy()` (e.g. `LICENSED_AI` /
`LICENSED_DISPLAY`). Event Intelligence consumes normalized IntelligenceItems with no
redesign. Staged activation only after a production capability test.

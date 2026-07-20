# Licensed Market Data Imports

`nikkei_per_pbr_licensed_template.csv` is the review template for licensed or
manually supplied Nikkei 225 close, PER, and PBR data. Until redistribution
rights are confirmed its production contract is
`status=license_blocked`, `coreRequired=false`, `automaticFetch=false`, and
`productionDisplay=false`.

After source and redistribution rights are confirmed, map each reviewed date to
`nikkei_market_ledger_import_template.csv` as `valuation.nikkei` (JPY),
`valuation.per` (ratio), and `valuation.pbr` (ratio). The existing Market Ledger
then derives EPS, BPS, and PER 16–21 levels. Do not import index-based PER/PBR
into weighted series or invent a new series without a reviewed schema change.

The JPX credit CSV contains only official two-market total value columns. Its
historical `availableFrom` is conservatively set seven days after each period;
the two current individual files use their Wednesday publication timestamps.

## J-Quants breadth source of truth

| Dataset | Source of truth | Publication/availability | Production handling |
|---|---|---|---|
| Prime domestic-common breadth | J-Quants V2 historical issue master + adjusted daily close | provider update 16:30 JST; consumed from 17:00 JST | aggregate observations only |
| All TSE domestic-common breadth | Same; Prime/Standard/Growth, historical membership | same | aggregate observations only |
| 6/10/15/25-day ratios | Market Ledger derived from daily advances/declines | after source observations are available | `sho_heuristic`, never `validated` without walk-forward evidence |
| Nikkei 225 PER/PBR | Licensed reviewed import only | source publication time | blocked from automatic fetch/display until rights review |

Raw licensed J-Quants rows are processed in memory and are not written to the
repository, Remote Journal, or public API. Backfill/incremental jobs use the
admin-only foundation-job endpoint, checkpoint their last committed date, and
persist only aggregate counts, provenance hashes, and verification receipts.

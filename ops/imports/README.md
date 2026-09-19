# Reviewed market-data imports

The owner-confirmed existing data-use entitlement is retained. Do not request
that same confirmation again or interpret a technical HTTP 403 as proof that
no historical series exists. Do not purchase another contract implicitly.

The active index valuation path is `jp_market_valuation.py`, sharing the
`jp_market_valuation.sqlite3` vintage store with daily summary acquisition.
Use `scripts/import_index_valuation.py --csv <reviewed-export> --store <existing-store>`
to validate first, then the same command with `--apply` to append. See
`acquisition_20260920/source_registry.json` and the acceptance checklist for the
43 requested indicator groups. These are acquisition specifications, not values.

An export must explicitly contain `date,nikkei_close,index_per,per_basis,source_url,source_sha256`.
Only `INDEX_WEIGHT_BASIS`, the same-session Nikkei 225 price-index close, and
the named official summary reference are accepted. Imported-file hash and
claimed original-page hash are distinguished. Actual receipt is the known-at
time; an unverified publication timestamp cannot authorize historical replay.
EPS is close / index-based PER, an approximation using rounded published PER,
not an independently published EPS. No fixed PER support/resistance is created.

The older ledger templates remain archived import/research assets; do not
route an index-based PER into an ambiguous weighted series or use their fixed
PER bands as current formal price scenarios. The current index chart uses the
existing `jp_market_price_paths.py` calculation and unchanged decision authority.

The JPX credit CSV contains only official two-market total value columns. Its
historical `availableFrom` is conservatively set seven days after each period;
the two current individual files use their Wednesday publication timestamps.

## J-Quants breadth source of truth

| Dataset | Source of truth | Publication/availability | Production handling |
|---|---|---|---|
| Prime domestic-common breadth | J-Quants V2 historical issue master + adjusted daily close | provider update 16:30 JST; consumed from 17:00 JST | aggregate observations only |
| All TSE domestic-common breadth | Same; Prime/Standard/Growth, historical membership | same | aggregate observations only |
| 6/10/15/25-day ratios | Market Ledger derived from daily advances/declines | after source observations are available | `argus_heuristic`, never `validated` without walk-forward evidence |
| Nikkei 225 index PER | Official daily summary or reviewed export into the existing valuation store | verified receipt; original publication unknown | derived EPS explicitly approximate; failed acquisition remains unavailable |

Raw licensed J-Quants rows are processed in memory and are not written to the
repository, Remote Journal, or public API. Backfill/incremental jobs use the
admin-only foundation-job endpoint, checkpoint their last committed date, and
persist only aggregate counts, provenance hashes, and verification receipts.

# Licensed Market Data Imports

`nikkei_per_pbr_licensed_template.csv` is the review template for licensed or
manually supplied Nikkei 225 close, PER, and PBR data. Automatic acquisition is
disabled while `licenseStatus=unverified`.

After source and redistribution rights are confirmed, map each reviewed date to
`nikkei_market_ledger_import_template.csv` as `valuation.nikkei` (JPY),
`valuation.per` (ratio), and `valuation.pbr` (ratio). The existing Market Ledger
then derives EPS, BPS, and PER 16–21 levels. Do not import index-based PER/PBR
into weighted series or invent a new series without a reviewed schema change.

The JPX credit CSV contains only official two-market total value columns. Its
historical `availableFrom` is conservatively set seven days after each period;
the two current individual files use their Wednesday publication timestamps.

#!/usr/bin/env python3
"""Calibration Ledger v4 — parallel DRY-RUN recorder/scorer.

Reads a prediction-snapshot JSON, records today's forecasts and scores due
horizons into a SEPARATE epoch dir (e.g. ledger/calibration_v1/), using the
tested argus_ledger_v4 scorer. Writes ONLY inside that dir — it NEVER touches the
v3 ledger (ledger/days, ledger/scores, summary.json). Idempotent per date
(records once/day), append-only.

Usage:  python3 argus_v4_dryrun.py <snapshot.json> <epoch_dir>
"""
import glob  # noqa: F401  (kept for parity; not required)
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import argus_ledger_v4 as V4

_KIND_MARKET = {"equity_jp": "JP", "etf_us": "US", "crypto": "CRYPTO", "fx": "FX", "vol": "VIX"}


def _normalize(src):
    """Snapshot prediction/sensor row → the record shape argus_ledger_v4 wants.
    Predictions key the symbol as 'symbol'/'market'; sensors as 'sensor'/'kind'."""
    sym = src.get("symbol") or src.get("sensor")
    mkt = src.get("market") or _KIND_MARKET.get(src.get("kind", ""), "")
    if not sym or not src.get("scenarios"):
        return None
    return {
        "symbol": sym, "market": mkt, "cohortId": src.get("cohortId") or "unknown",
        "scenarios": src.get("scenarios"), "priceAtPrediction": src.get("price"),
        "bandPct": src.get("bandPct"), "marketClock": src.get("marketClock"),
        "scored": {"1d": None, "3d": None, "5d": None},
    }


def _rows_from_snapshot(snap):
    return (snap.get("predictions") or []) + (snap.get("sensors") or [])


def main():
    if len(sys.argv) != 3:
        print("usage: argus_v4_dryrun.py <snapshot.json> <epoch_dir>", file=sys.stderr)
        sys.exit(2)
    snap_path, epoch_dir = sys.argv[1], sys.argv[2]
    snap = json.load(open(snap_path, encoding="utf-8"))
    today = snap.get("dateJst") or datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    os.makedirs(epoch_dir, exist_ok=True)
    pred_file = os.path.join(epoch_dir, "predictions.jsonl")

    rows = []
    if os.path.exists(pred_file):
        for ln in open(pred_file, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass

    new = 0
    if not any(r.get("date") == today for r in rows):   # record once per date
        for src in _rows_from_snapshot(snap):
            n = _normalize(src)
            if not n:
                continue
            n["date"] = today
            rows.append(n)
            new += 1

    # price_lookup: today's snapshot prices (the realized price on/after target)
    prices = {}
    for src in _rows_from_snapshot(snap):
        sym = src.get("symbol") or src.get("sensor")
        pr = src.get("price")
        if sym and isinstance(pr, (int, float)) and pr > 0:
            prices[sym] = pr

    # Pass now (UTC) so US/crypto are scored at their OWN market close (v10.101):
    # a horizon with a targetClose timestamp is due once that close has passed,
    # regardless of market — JP-only holding falls away.
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = V4.score_records(rows, lambda s: prices.get(s), today, now_iso=now_iso)

    with open(pred_file, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = V4.aggregate_by_cohort(rows)
    summary.update({
        "epochId": "calibration_v1", "status": "dry_run", "updated": today,
        "recorded": new, "scored": res["scored"], "held": res["held"],
        "totalRows": len(rows), "tradingDays": len({r.get("date") for r in rows}),
        "noteJa": "v4のparallel dry-run(本番ヘッドラインではない)。v3とは別ディレクトリ。"
                  "市場別クロックでJPを採点、US/cryptoは正しい時刻のジョブ実装まで保留。",
    })
    json.dump(summary, open(os.path.join(epoch_dir, "summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"v4-dryrun: date={today} recorded={new} scored={res['scored']} "
          f"held={res['held']} rows={len(rows)}")


if __name__ == "__main__":
    main()

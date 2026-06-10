#!/usr/bin/env python3
"""ARGUS moomoo bridge — runs NEXT TO OpenD (same machine, e.g. your AWS box).

Reads real-time JP/US quotes from the LOCAL OpenD gateway and pushes them to
the ARGUS backend (/api/argus/quote-push, admin-token gated). While pushes are
fresh (≤10 min) they override J-Quants(T-1)/Twelve Data in the app; when this
bridge stops, ARGUS falls back automatically. Account credentials and OpenD
never need to be reachable from the internet — keep port 11111 CLOSED in the
AWS security group (this script talks to 127.0.0.1).

Setup:
  pip3 install moomoo-api requests
  cp bridge.env.example /etc/argus-bridge.env   # then edit values
  sudo cp argus-bridge.service /etc/systemd/system/
  sudo systemctl daemon-reload && sudo systemctl enable --now argus-bridge

Logs: journalctl -u argus-bridge -f
"""
import os
import sys
import time

import requests

try:
    from moomoo import OpenQuoteContext, RET_OK
except ImportError:
    print("moomoo-api is not installed: pip3 install moomoo-api", file=sys.stderr)
    sys.exit(1)

BACKEND  = os.environ.get("ARGUS_BACKEND", "https://argus-backend-3j2m.onrender.com").rstrip("/")
TOKEN    = os.environ.get("ARGUS_ADMIN_TOKEN", "")
HOST     = os.environ.get("OPEND_HOST", "127.0.0.1")
PORT     = int(os.environ.get("OPEND_PORT", "11111"))
INTERVAL = max(20, int(os.environ.get("PUSH_INTERVAL_SEC", "60")))
# moomoo codes: "<MARKET>.<SYMBOL>", e.g. JP.7203 / US.NVDA. Edit to match the
# assets you watch in ARGUS (and your account's quote permissions).
CODES = [c.strip() for c in os.environ.get(
    "PUSH_SYMBOLS",
    "JP.8058,JP.9984,JP.5801,JP.5803,JP.6584,JP.285A,JP.9501,"
    "US.NVDA,US.AAPL,US.TSLA,US.META").split(",") if c.strip()]


def rows_from_snapshot(df):
    """moomoo market-snapshot dataframe → quote-push payload rows."""
    stocks = []
    for _, r in df.iterrows():
        code = str(r.get("code", ""))
        market, _, sym = code.partition(".")
        try:
            last = float(r.get("last_price") or 0)
            prev = float(r.get("prev_close_price") or 0)
        except (TypeError, ValueError):
            continue
        if not sym or last <= 0:
            continue
        stocks.append({
            "market": market.upper(),
            "symbol": sym.upper(),
            "price": last,
            "changeAbs": round(last - prev, 4) if prev else 0.0,
            "changePct": round((last - prev) / prev * 100, 4) if prev else 0.0,
            "volume": int(r.get("volume") or 0),
        })
    return stocks


def main():
    if not TOKEN:
        print("ARGUS_ADMIN_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    print(f"argus-bridge: OpenD {HOST}:{PORT} -> {BACKEND} every {INTERVAL}s, {len(CODES)} codes")
    qc = OpenQuoteContext(host=HOST, port=PORT)
    try:
        while True:
            try:
                ret, df = qc.get_market_snapshot(CODES)
                if ret == RET_OK:
                    stocks = rows_from_snapshot(df)
                    if stocks:
                        resp = requests.post(
                            f"{BACKEND}/api/argus/quote-push",
                            json={"stocks": stocks, "source": "moomoo"},
                            headers={"X-ARGUS-ADMIN-TOKEN": TOKEN},
                            timeout=30,
                        )
                        body = resp.json() if resp.ok else {}
                        print(time.strftime("%H:%M:%S"),
                              f"pushed http={resp.status_code} accepted={body.get('accepted')}")
                    else:
                        print(time.strftime("%H:%M:%S"), "no valid rows in snapshot")
                else:
                    # df carries the error message on failure — never a secret.
                    print(time.strftime("%H:%M:%S"), "snapshot error:", str(df)[:160])
            except Exception as e:
                print(time.strftime("%H:%M:%S"), "loop error:", type(e).__name__, str(e)[:120])
            time.sleep(INTERVAL)
    finally:
        qc.close()


if __name__ == "__main__":
    main()

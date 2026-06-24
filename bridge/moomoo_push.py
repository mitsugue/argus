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
import hashlib
import hmac
import json
import os
import secrets
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
# v10.44: HMAC anti-replay. When set (must match Render's ARGUS_BRIDGE_HMAC_SECRET)
# each push is signed so a captured admin token alone can't replay/forge it.
# Empty = unsigned (works while Render's ARGUS_BRIDGE_HMAC_REQUIRED is off).
HMAC_SECRET = os.environ.get("ARGUS_BRIDGE_HMAC_SECRET", "")
HOST     = os.environ.get("OPEND_HOST", "127.0.0.1")
PORT     = int(os.environ.get("OPEND_PORT", "11111"))
# v10.10.1: 15s quote cadence (get_market_snapshot is 1 request per cycle —
# 2/30s, far inside moomoo's ~10/30s quota). Big-money flow stays on its own
# slower cadence below (up to 1 request per code per flow cycle).
INTERVAL = max(10, int(os.environ.get("PUSH_INTERVAL_SEC", "15")))
FLOW_INTERVAL = max(INTERVAL, int(os.environ.get("FLOW_INTERVAL_SEC", "60")))
# moomoo codes: "<MARKET>.<SYMBOL>", e.g. JP.7203 / US.NVDA. Edit to match the
# assets you watch in ARGUS (and your account's quote permissions).
# v10.11: the JP Layer-1 sensors (1306/1321/8306/7203/9432) ride along so the
# Close Pin ledger can pin them with realtime prices (16 codes, still 1
# snapshot request per cycle).
CODES = [c.strip() for c in os.environ.get(
    "PUSH_SYMBOLS",
    "JP.8058,JP.9984,JP.5801,JP.5803,JP.6584,JP.285A,JP.9501,"
    "JP.1306,JP.1321,JP.8306,JP.7203,JP.9432,"
    "US.NVDA,US.AAPL,US.TSLA,US.META").split(",") if c.strip()]
# Always push the 8 regime ETFs realtime (v10.146) so the backend regime engine
# reads moomoo prices instead of rate-limited Twelve Data — independent of the
# user's PUSH_SYMBOLS. Deduped, order-preserving.
_REGIME_ETF_CODES = ["US.SPY", "US.QQQ", "US.IWM", "US.XLK", "US.XLU", "US.GLD", "US.TLT", "US.HYG"]
CODES = list(dict.fromkeys(CODES + _REGIME_ETF_CODES))


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


# ── Capital distribution (大口/中口/小口の売買フロー) — v10.2 ──
# get_capital_distribution returns today's cumulative in/out amounts split by
# order size. "Big money" = super + big. Availability varies by market and by
# the account's quote rights — failures are skipped per symbol, never fatal.
_FLOW_FAIL_UNTIL = {}   # code -> epoch; back off codes that keep failing

def fetch_flow(qc, code):
    now = time.time()
    if _FLOW_FAIL_UNTIL.get(code, 0) > now:
        return None
    try:
        ret, df = qc.get_capital_distribution(code)
        if ret != RET_OK or df is None or len(df) == 0:
            _FLOW_FAIL_UNTIL[code] = now + 1800  # 30-min back-off
            return None
        r = df.iloc[0]
        def f(k):
            try:
                return float(r.get(k) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        big_in  = f("capital_in_super") + f("capital_in_big")
        big_out = f("capital_out_super") + f("capital_out_big")
        all_in  = big_in + f("capital_in_mid") + f("capital_in_small")
        all_out = big_out + f("capital_out_mid") + f("capital_out_small")
        return {"bigIn": big_in, "bigOut": big_out, "allIn": all_in, "allOut": all_out}
    except Exception:
        _FLOW_FAIL_UNTIL[code] = now + 1800
        return None


def _push_quotes(stocks):
    """POST the quotes, signing the EXACT body bytes (data=raw) so the server's
    HMAC over '<ts>.<nonce>.<rawbody>' matches. Signs only when HMAC_SECRET is
    set; otherwise sends the admin token alone (backward compatible)."""
    raw = json.dumps({"stocks": stocks, "source": "moomoo"},
                     separators=(",", ":")).encode("utf-8")
    headers = {"X-ARGUS-ADMIN-TOKEN": TOKEN, "Content-Type": "application/json"}
    if HMAC_SECRET:
        ts, nonce = str(time.time()), secrets.token_hex(8)
        sig = hmac.new(HMAC_SECRET.encode("utf-8"),
                       f"{ts}.{nonce}.".encode("utf-8") + raw, hashlib.sha256).hexdigest()
        headers["X-ARGUS-TIMESTAMP"] = ts
        headers["X-ARGUS-NONCE"] = nonce
        headers["X-ARGUS-SIGNATURE"] = sig
    return requests.post(f"{BACKEND}/api/argus/quote-push", data=raw, headers=headers, timeout=30)


# ── JP all-market capability test (Phase 1) ─────────────────────────────────
# When CAP_TEST_ENABLED=1, once per JP trading day the bridge sweeps the full
# JP universe via get_market_snapshot (batches of <=400) and POSTs a metrics
# report (coverage, quote-age via update_time, entitlement, sweep timing) so we
# can PROVE whether moomoo can do realtime all-market — without claiming it until
# the venue timestamps say so. Runs alongside (not instead of) the watchlist push.
import datetime as _dt

CAP_TEST_ENABLED = os.environ.get("JP_ALL_MARKET_CAP_TEST", "0") not in ("0", "false", "")
CAP_BATCH = max(50, min(400, int(os.environ.get("CAP_BATCH_SIZE", "400"))))
# Cap the sweep size so a small EC2 instance (e.g. 411MB RAM) doesn't OOM on the
# full ~3,900-symbol universe. Default 500 = a representative sample that still
# proves freshness/entitlement. Set 0 for the full universe (needs a bigger box).
CAP_UNIVERSE_MAX = int(os.environ.get("CAP_UNIVERSE_MAX", "500"))
_JST = _dt.timezone(_dt.timedelta(hours=9))
_cap_done_date = None  # JST date string the test last ran
_bridge_start = time.time()   # warm-up reference (v10.114)
CAP_WARMUP_SEC = 150          # let OpenD push fresh quotes before measuring freshness

# ── Realtime JP movers sweep (v10.135) ───────────────────────────────────────
# Periodically sweep (CAP_UNIVERSE_MAX-sample ∪ watchlist) during the JP session,
# extract the biggest movers, and POST them so the backend can push them WHILE the
# TSE is open (moomoo realtime — seconds), instead of relying on Yahoo (~20min) or
# post-close J-Quants. Same get_market_snapshot path as the cap-test.
MOVER_SWEEP_ENABLED  = os.environ.get("JP_MOVER_SWEEP", "1") not in ("0", "false", "")
MOVER_SWEEP_INTERVAL = max(120, int(os.environ.get("JP_MOVER_SWEEP_SEC", "300")))   # 5 min
MOVER_MIN_PCT        = float(os.environ.get("JP_MOVER_MIN_PCT", "8"))               # report |move| >= 8%
MOVER_MAX            = int(os.environ.get("JP_MOVER_MAX", "60"))
_mover_sweep_at = 0.0


def _now_jst():
    return _dt.datetime.now(_JST)


def _jp_open_jst():
    n = _now_jst()
    if n.weekday() >= 5:
        return False
    hm = n.hour * 60 + n.minute
    return (9 * 60 <= hm <= 11 * 60 + 30) or (12 * 60 + 30 <= hm <= 15 * 60 + 30)


def _cap_active_window():
    """Run the cap-test ONLY during active CONTINUOUS trading — skip the open /
    lunch-reopen edges where 'traded' names are naturally stale (no trades just
    happened) and would misread as delayed. Morning 09:15–11:25, afternoon
    12:45–15:25 JST. (v10.114: fixes false delayed_evidence at edges.)"""
    n = _now_jst()
    if n.weekday() >= 5:
        return False
    hm = n.hour * 60 + n.minute
    return (9 * 60 + 15 <= hm <= 11 * 60 + 25) or (12 * 60 + 45 <= hm <= 15 * 60 + 25)


def _fetch_jp_universe():
    try:
        r = requests.get(f"{BACKEND}/api/argus/jp-universe",
                         headers={"X-ARGUS-ADMIN-TOKEN": TOKEN}, timeout=40)
        return r.json().get("codes", []) if r.ok else []
    except Exception:
        return []


def _post_capability_report(report):
    raw = json.dumps({"report": report}, separators=(",", ":")).encode("utf-8")
    headers = {"X-ARGUS-ADMIN-TOKEN": TOKEN, "Content-Type": "application/json"}
    if HMAC_SECRET:
        ts, nonce = str(time.time()), secrets.token_hex(8)
        sig = hmac.new(HMAC_SECRET.encode("utf-8"),
                       f"{ts}.{nonce}.".encode("utf-8") + raw, hashlib.sha256).hexdigest()
        headers["X-ARGUS-TIMESTAMP"] = ts
        headers["X-ARGUS-NONCE"] = nonce
        headers["X-ARGUS-SIGNATURE"] = sig
    return requests.post(f"{BACKEND}/api/argus/moomoo-capability-report",
                         data=raw, headers=headers, timeout=40)


def run_capability_test(qc):
    """One full-universe sweep + metrics. Returns the report (also POSTed)."""
    codes = _fetch_jp_universe()
    if not codes:
        print(_now_jst().strftime("%H:%M:%S"), "cap-test: no universe (J-Quants/admin?)")
        return None
    full = len(codes)
    if CAP_UNIVERSE_MAX and full > CAP_UNIVERSE_MAX:
        codes = codes[:CAP_UNIVERSE_MAX]   # sample to fit small-instance memory
    batches = [codes[i:i + CAP_BATCH] for i in range(0, len(codes), CAP_BATCH)]
    t0 = time.time()
    requested = returned = stale = errors = 0
    ages, latencies, traded_ages = [], [], []
    for b in batches:
        requested += len(b)
        bt = time.time()
        try:
            ret, df = qc.get_market_snapshot(b)
            latencies.append(round(time.time() - bt, 2))
            if ret != RET_OK:
                errors += 1
                continue
            for _, row in df.iterrows():
                returned += 1
                ut = str(row.get("update_time") or "")[:19]
                try:
                    vol = float(row.get("volume") or 0)
                except (TypeError, ValueError):
                    vol = 0
                try:
                    dt = _dt.datetime.strptime(ut, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_JST)
                    age = (_now_jst() - dt).total_seconds()
                    ages.append(age)
                    # Control set: only names that ACTUALLY TRADED today. An
                    # illiquid name's old update_time means "no trade", not a feed
                    # delay — so the entitlement verdict uses traded names (GPT).
                    if vol > 0:
                        traded_ages.append(age)
                    if age >= 300:
                        stale += 1
                except Exception:
                    pass
        except Exception:
            errors += 1
        time.sleep(0.5)  # stagger batches — stay well under the rate quota
    ages.sort(); traded_ages.sort()

    def _pct(a, p):
        return round(a[min(len(a) - 1, int(p * len(a)))], 1) if a else None
    p95, med = _pct(ages, 0.95), _pct(ages, 0.5)
    tp95, tmed = _pct(traded_ages, 0.95), _pct(traded_ages, 0.5)
    # Verdict from the TRADED control set (falls back to all if no volume data).
    vp95 = tp95 if traded_ages else p95
    vmed = tmed if traded_ages else med
    verdict = ("realtime_evidence" if vp95 is not None and vp95 <= 60 else
               "delayed_evidence" if vmed is not None and vmed >= 600 else "unknown")
    report = {
        "asOf": _now_jst().isoformat(), "universeCount": len(codes),
        "universeFull": full, "sampled": full != len(codes),
        "batches": len(batches),
        "batchSize": CAP_BATCH, "requested": requested, "returned": returned,
        "coveragePct": round(returned / requested * 100, 1) if requested else 0,
        "sweepSeconds": round(time.time() - t0, 1),
        "batchLatencyMaxS": max(latencies) if latencies else None,
        "quoteAgeMedianS": med, "quoteAgeP95S": p95,
        "tradedCount": len(traded_ages),
        "quoteAgeMedianTradedS": tmed, "quoteAgeP95TradedS": tp95,
        "staleCount": stale, "errors": errors, "entitlementVerdict": verdict,
        "noteJa": "鮮度は『本日約定あり銘柄(volume>0)』で判定。約定の無い低流動性銘柄の古いupdate_timeは"
                  "配信遅延ではないため除外。traded p95<=60sでrealtime_evidence。",
    }
    try:
        resp = _post_capability_report(report)
        print(_now_jst().strftime("%H:%M:%S"),
              f"cap-test: cov={report['coveragePct']}% tradedP95={tp95}s "
              f"(traded={len(traded_ages)}) allP95={p95}s verdict={verdict} "
              f"post={resp.status_code}")
    except Exception as e:
        print(_now_jst().strftime("%H:%M:%S"), "cap-test post error:", str(e)[:120])
    return report


def _post_movers(movers, as_of, coverage):
    """Signed POST of realtime JP movers to the backend (same HMAC scheme)."""
    raw = json.dumps({"movers": movers, "asOf": as_of, "coverage": coverage,
                      "source": "moomoo"}, separators=(",", ":")).encode("utf-8")
    headers = {"X-ARGUS-ADMIN-TOKEN": TOKEN, "Content-Type": "application/json"}
    if HMAC_SECRET:
        ts, nonce = str(time.time()), secrets.token_hex(8)
        sig = hmac.new(HMAC_SECRET.encode("utf-8"),
                       f"{ts}.{nonce}.".encode("utf-8") + raw, hashlib.sha256).hexdigest()
        headers["X-ARGUS-TIMESTAMP"] = ts
        headers["X-ARGUS-NONCE"] = nonce
        headers["X-ARGUS-SIGNATURE"] = sig
    return requests.post(f"{BACKEND}/api/argus/jp-movers-push", data=raw, headers=headers, timeout=30)


def sweep_jp_movers(qc):
    """One realtime sweep of (CAP_UNIVERSE_MAX-sample ∪ watchlist) → POST the biggest
    movers. Reuses get_market_snapshot + rows_from_snapshot. Never raises fatally."""
    uni = _fetch_jp_universe()
    if CAP_UNIVERSE_MAX and len(uni) > CAP_UNIVERSE_MAX:
        uni = uni[:CAP_UNIVERSE_MAX]
    # Always include the watchlist (the sample may not contain it).
    codes, seen = [], set()
    for c in list(CODES) + uni:
        cu = c.upper()
        if cu not in seen:
            seen.add(cu)
            codes.append(c)
    if not codes:
        print(_now_jst().strftime("%H:%M:%S"), "mover-sweep: no universe")
        return
    rows = []
    for i in range(0, len(codes), CAP_BATCH):
        ret, df = qc.get_market_snapshot(codes[i:i + CAP_BATCH])
        if ret == RET_OK:
            rows.extend(rows_from_snapshot(df))
        time.sleep(0.5)   # stay under the rate quota
    movers = [r for r in rows if abs(r.get("changePct") or 0) >= MOVER_MIN_PCT]
    movers.sort(key=lambda r: abs(r.get("changePct") or 0), reverse=True)
    movers = movers[:MOVER_MAX]
    try:
        resp = _post_movers(movers, _now_jst().isoformat(), len(codes))
        body = resp.json() if resp.ok else {}
        print(_now_jst().strftime("%H:%M:%S"),
              f"mover-sweep: swept={len(codes)} movers>={MOVER_MIN_PCT}%={len(movers)} "
              f"accepted={body.get('accepted')} http={resp.status_code}")
    except Exception as e:
        print(_now_jst().strftime("%H:%M:%S"), "mover-sweep post error:", str(e)[:120])


# ── US realtime mover sweep (v10.146) — same idea for the US session ──────────
def _us_open():
    """Rough US regular session in UTC (covers EDT/EST). The backend applies the
    precise ET gate; the bridge just needs to sweep during the right window."""
    n = _dt.datetime.now(_dt.timezone.utc)
    if n.weekday() >= 5:
        return False
    hm = n.hour * 60 + n.minute
    return 13 * 60 + 30 <= hm <= 20 * 60 + 30


def _fetch_us_universe():
    try:
        r = requests.get(f"{BACKEND}/api/argus/us-universe",
                         headers={"X-ARGUS-ADMIN-TOKEN": TOKEN}, timeout=40)
        return r.json().get("codes", []) if r.ok else []
    except Exception:
        return []


def _post_us_movers(movers, as_of, coverage):
    raw = json.dumps({"movers": movers, "asOf": as_of, "coverage": coverage, "source": "moomoo"},
                     separators=(",", ":")).encode("utf-8")
    headers = {"X-ARGUS-ADMIN-TOKEN": TOKEN, "Content-Type": "application/json"}
    if HMAC_SECRET:
        ts, nonce = str(time.time()), secrets.token_hex(8)
        sig = hmac.new(HMAC_SECRET.encode("utf-8"),
                       f"{ts}.{nonce}.".encode("utf-8") + raw, hashlib.sha256).hexdigest()
        headers["X-ARGUS-TIMESTAMP"] = ts
        headers["X-ARGUS-NONCE"] = nonce
        headers["X-ARGUS-SIGNATURE"] = sig
    return requests.post(f"{BACKEND}/api/argus/us-movers-push", data=raw, headers=headers, timeout=30)


def sweep_us_movers(qc):
    """Realtime sweep of the backend US universe (curated ∪ watchlist ∪ ETFs) → POST
    the biggest movers. Mirrors sweep_jp_movers; replaces Alpha Vantage's stale feed."""
    uni = _fetch_us_universe()
    codes, seen = [], set()
    for c in [c for c in CODES if c.upper().startswith("US.")] + uni:
        cu = c.upper()
        if cu not in seen:
            seen.add(cu); codes.append(c)
    if not codes:
        print(_now_jst().strftime("%H:%M:%S"), "us-mover-sweep: no universe")
        return
    rows = []
    for i in range(0, len(codes), CAP_BATCH):
        ret, df = qc.get_market_snapshot(codes[i:i + CAP_BATCH])
        if ret == RET_OK:
            rows.extend(rows_from_snapshot(df))
        time.sleep(0.5)
    movers = sorted([r for r in rows if abs(r.get("changePct") or 0) >= MOVER_MIN_PCT],
                    key=lambda r: abs(r.get("changePct") or 0), reverse=True)[:MOVER_MAX]
    try:
        resp = _post_us_movers(movers, _now_jst().isoformat(), len(codes))
        body = resp.json() if resp.ok else {}
        print(_now_jst().strftime("%H:%M:%S"),
              f"us-mover-sweep: swept={len(codes)} movers>={MOVER_MIN_PCT}%={len(movers)} "
              f"accepted={body.get('accepted')} http={resp.status_code}")
    except Exception as e:
        print(_now_jst().strftime("%H:%M:%S"), "us-mover-sweep post error:", str(e)[:120])


_us_mover_sweep_at = 0.0


def main():
    if not TOKEN:
        print("ARGUS_ADMIN_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    print("argus-bridge: HMAC signing " + ("ON" if HMAC_SECRET else "OFF (no secret set)"))
    print(f"argus-bridge: OpenD {HOST}:{PORT} -> {BACKEND} every {INTERVAL}s "
          f"(flow every {FLOW_INTERVAL}s), {len(CODES)} codes")
    qc = OpenQuoteContext(host=HOST, port=PORT)
    flow_cache = {}   # code -> last known flow dict (carried between flow cycles)
    last_flow_at = 0.0
    try:
        while True:
            try:
                ret, df = qc.get_market_snapshot(CODES)
                if ret == RET_OK:
                    stocks = rows_from_snapshot(df)
                    # Big-money flow on its own slower cadence (quota: the
                    # capital-distribution calls are 1/code). Between flow
                    # cycles the LAST KNOWN value rides along so the backend
                    # row never flickers flow-less.
                    do_flow = time.time() - last_flow_at >= FLOW_INTERVAL
                    if do_flow:
                        last_flow_at = time.time()
                    by_sym = {s["market"] + "." + s["symbol"]: s for s in stocks}
                    for code in CODES:
                        s = by_sym.get(code.upper())
                        if s is None:
                            continue
                        if do_flow:
                            flow = fetch_flow(qc, code)
                            if flow:
                                flow_cache[code] = flow
                            time.sleep(0.25)
                        if flow_cache.get(code):
                            s["flow"] = flow_cache[code]
                    if stocks:
                        resp = _push_quotes(stocks)
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

            # JP all-market capability test: auto-run ONCE per JP trading day, at
            # the first loop where the market is open. Separate from (and after)
            # the watchlist push so it never degrades the 16-symbol bridge.
            if CAP_TEST_ENABLED:
                global _cap_done_date
                today = _now_jst().strftime("%Y-%m-%d")
                # Active continuous window + warm-up only — avoids the open/lunch
                # edges and cold-reconnect snapshots that misread as delayed (v10.114).
                warm = (time.time() - _bridge_start) >= CAP_WARMUP_SEC
                if _cap_active_window() and warm and _cap_done_date != today:
                    _cap_done_date = today
                    try:
                        run_capability_test(qc)
                    except Exception as e:
                        print(_now_jst().strftime("%H:%M:%S"), "cap-test error:", str(e)[:120])

            # Realtime mover sweep — periodic during the JP session (v10.135).
            if MOVER_SWEEP_ENABLED and _jp_open_jst():
                global _mover_sweep_at
                if time.time() - _mover_sweep_at >= MOVER_SWEEP_INTERVAL:
                    _mover_sweep_at = time.time()
                    try:
                        sweep_jp_movers(qc)
                    except Exception as e:
                        print(_now_jst().strftime("%H:%M:%S"), "mover-sweep error:", str(e)[:120])

            # US realtime mover sweep — curated S&P500 ∪ watchlist ∪ ETFs (v10.146).
            if MOVER_SWEEP_ENABLED and _us_open():
                global _us_mover_sweep_at
                if time.time() - _us_mover_sweep_at >= MOVER_SWEEP_INTERVAL:
                    _us_mover_sweep_at = time.time()
                    try:
                        sweep_us_movers(qc)
                    except Exception as e:
                        print(_now_jst().strftime("%H:%M:%S"), "us-mover-sweep error:", str(e)[:120])

            time.sleep(INTERVAL)
    finally:
        qc.close()


if __name__ == "__main__":
    main()

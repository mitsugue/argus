#!/usr/bin/env python3
"""ARGUS moomoo bridge — runs NEXT TO OpenD (same machine, e.g. your AWS box).

Collects shared US ETFs and confirmed registered US prices during regular and
extended (pre-market, after-hours, overnight) sessions, each with its own time.
Money-flow calls and broad universe sweeps remain retired.
Existing tokens, HMAC signing and provider observation timestamps are retained.
OpenD remains local; never expose port 11111 to the internet.

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
import math
import os
import secrets
import shutil
import sys
import time
from threading import Thread

import requests

# v11.5.7: LAZY import — the module must be importable without moomoo-api so the
# repo's tests can exercise the market-split / entitlement / heartbeat logic.
# main() still refuses to run without the real library.
try:
    from moomoo import OpenQuoteContext, RET_OK
except ImportError:
    OpenQuoteContext = None
    RET_OK = 0

BRIDGE_VERSION = "13.8.166"

BACKEND  = os.environ.get("ARGUS_BACKEND", "https://argus-backend-3j2m.onrender.com").rstrip("/")
TOKEN    = os.environ.get("ARGUS_ADMIN_TOKEN", "")
# v10.44: HMAC anti-replay. When set (must match Render's ARGUS_BRIDGE_HMAC_SECRET)
# each push is signed so a captured admin token alone can't replay/forge it.
# Empty = unsigned (works while Render's ARGUS_BRIDGE_HMAC_REQUIRED is off).
HMAC_SECRET = os.environ.get("ARGUS_BRIDGE_HMAC_SECRET", "")
HOST     = os.environ.get("OPEND_HOST", "127.0.0.1")
PORT     = int(os.environ.get("OPEND_PORT", "11111"))
# v11.5.7 (Jul-3 incident): the account can lose JP quote entitlement while US
# stays fine ("No permission to get quotes"). One market's failure must NEVER
# stop the other. ARGUS_DISABLE_JP_QUOTES=1 = operator-forced US-only mode
# (skips JP push/watchlist/mover-sweep/cap-test). Without the flag, JP is tried
# normally but a permission error degrades gracefully with a weekly probe.
DISABLE_JP = os.environ.get("ARGUS_DISABLE_JP_QUOTES", "0") not in ("0", "false", "")
JP_ENTITLEMENT_BACKOFF_SEC = max(3600, int(os.environ.get("JP_ENTITLEMENT_BACKOFF_SEC", "604800")))
HEARTBEAT_INTERVAL = max(30, int(os.environ.get("BRIDGE_HEARTBEAT_SEC", "60")))
# One bounded snapshot every 30 seconds; do not subscribe to a stream or
# acquire flow/boards/orders. The registered set comes only from admin sync.
INTERVAL = 30
_REGIME_ETF_CODES = ["US.SPY", "US.QQQ", "US.IWM", "US.XLK", "US.XLU", "US.GLD", "US.TLT", "US.HYG"]
CODES = list(_REGIME_ETF_CODES)


# ── v11.5.7 market isolation + entitlement state (testable, no moomoo import) ──
STATE = {
    "jpBlockUntil": 0.0,           # epoch until which JP fetch is skipped (entitlement backoff)
    "jpLastErrorClass": None,      # "permission" | "other" | None
    "usLastErrorClass": None,      # "api_unhealthy" | "sms_required" | None
    "jpSnapshotErrors": 0,         # public-safe cumulative counters, split by market
    "usSnapshotErrors": 0,
    "jpLastErrorLogAt": 0.0,       # log-dedup stamp (no 15s spam)
    "lastPushAt": None,            # iso — any accepted push
    "lastUsPushAt": None,
    "lastJpPushAt": None,
    "acceptedLastPush": 0,
    "lastSnapshotOkAt": 0.0,       # epoch — OpenD API healthy signal
    "consecutiveSnapshotErrors": 0,
    "openDErrorClass": None,       # "sms_required" | "api_unhealthy" | None
}


def split_codes_by_market(codes):
    """'JP.8058'/'US.NVDA' style codes → {"JP": [...], "US": [...]}. Unknown
    prefixes ride with US (moomoo accepts them in the same snapshot call)."""
    out = {"JP": [], "US": []}
    for c in codes or []:
        (out["JP"] if str(c).upper().startswith("JP.") else out["US"]).append(c)
    return out


def is_permission_error(msg):
    return "no permission" in str(msg or "").lower()


def classify_opend_error(msg):
    """OpenD failure text → coarse class (never contains secrets)."""
    low = str(msg or "").lower()
    if "sms" in low or "verification" in low or "verify" in low:
        return "sms_required"
    return "api_unhealthy"


def jp_push_active(now=None, state=None, disable_jp=None):
    """Is JP realtime push allowed right now? False when operator-disabled or
    inside the entitlement backoff window."""
    now = time.time() if now is None else now
    state = STATE if state is None else state
    disable_jp = DISABLE_JP if disable_jp is None else disable_jp
    if disable_jp:
        return False
    return now >= float(state.get("jpBlockUntil") or 0.0)


def jp_realtime_status(state=None, disable_jp=None):
    """ok | entitlement_unavailable | disabled | degraded | unknown."""
    state = STATE if state is None else state
    disable_jp = DISABLE_JP if disable_jp is None else disable_jp
    if disable_jp:
        return "disabled"
    if time.time() < float(state.get("jpBlockUntil") or 0.0):
        return ("entitlement_unavailable" if state.get("jpLastErrorClass") == "permission"
                else "degraded")
    if state.get("lastJpPushAt"):
        return "ok"
    return "unknown"


def us_realtime_status(state=None):
    state = STATE if state is None else state
    if state.get("lastUsPushAt"):
        age = time.time() - (state.get("_lastUsPushEpoch") or 0.0)
        return "ok" if age <= 300 else "degraded"
    return "unknown"


def opend_status(state=None):
    """connected | sms_required | api_unhealthy | unknown."""
    state = STATE if state is None else state
    if state.get("openDErrorClass") == "sms_required":
        return "sms_required"
    if time.time() - float(state.get("lastSnapshotOkAt") or 0.0) <= 300:
        return "connected"
    if int(state.get("consecutiveSnapshotErrors") or 0) >= 3:
        return state.get("openDErrorClass") or "api_unhealthy"
    return "unknown"


def bridge_mode(state=None, disable_jp=None):
    """full | us_only | fallback — us_only = operator-forced; fallback = JP lost
    at runtime (entitlement/backoff) while US keeps going."""
    disable_jp = DISABLE_JP if disable_jp is None else disable_jp
    if disable_jp:
        return "us_only"
    if not jp_push_active(state=state, disable_jp=disable_jp):
        return "fallback"
    return "full"


def disk_usage_pct(path="/"):
    try:
        du = shutil.disk_usage(path)
        return round(du.used / du.total * 100, 1)
    except Exception:
        return None


def _systemd_enabled(unit):
    """v12.0.3 reboot-safety self-report — 'is-enabled' only (no args, no env,
    no secrets). Returns True/False, or None when systemd/unit is unavailable."""
    try:
        import subprocess
        r = subprocess.run(["systemctl", "is-enabled", unit],
                           capture_output=True, text=True, timeout=5)
        out = (r.stdout or "").strip()
        if out == "enabled":
            return True
        if out in ("disabled", "masked", "static"):
            return False
        return None            # not-found 等 — 不明はNone(捏造しない)
    except Exception:
        return None


def reboot_safety_facts():
    """自動復旧の自己申告(EC2実測)。秘密ゼロ — enabled/存在フラグのみ。"""
    facts = {}
    for key, unit in (("bridgeAutostart", "argus-bridge"), ("opendAutostart", "opend")):
        v = _systemd_enabled(unit)
        if v is not None:
            facts[key] = v
    try:
        facts["systemRestartRequired"] = os.path.exists("/var/run/reboot-required")
    except Exception:
        pass
    return facts


def build_heartbeat(state=None, disable_jp=None, now_iso=None):
    """The public-safe heartbeat payload — statuses/timestamps/counts ONLY.
    Never tokens, never account identifiers, never raw provider bodies."""
    state = STATE if state is None else state
    disable_jp = DISABLE_JP if disable_jp is None else disable_jp
    import datetime as _dt2
    return {
        **reboot_safety_facts(),   # v12.0.3: opendAutostart/bridgeAutostart/systemRestartRequired
        "at": now_iso or _dt2.datetime.now(_dt2.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bridgeVersion": BRIDGE_VERSION,
        "bridgeMode": bridge_mode(state, disable_jp),
        "openDStatus": opend_status(state),
        "lastQuotePushAt": state.get("lastPushAt"),
        "lastUSQuotePushAt": state.get("lastUsPushAt"),
        "lastJPQuotePushAt": state.get("lastJpPushAt"),
        "acceptedCountLastPush": int(state.get("acceptedLastPush") or 0),
        "usRealtimeStatus": us_realtime_status(state),
        "jpRealtimeStatus": jp_realtime_status(state, disable_jp),
        "jpFallbackActive": not jp_push_active(state=state, disable_jp=disable_jp),
        "jpLastErrorClass": state.get("jpLastErrorClass"),
        "usLastErrorClass": state.get("usLastErrorClass"),
        "jpSnapshotErrors": int(state.get("jpSnapshotErrors") or 0),
        "usSnapshotErrors": int(state.get("usSnapshotErrors") or 0),
        "diskUsagePct": disk_usage_pct(),
        "intervalSec": INTERVAL,
        # 2026-10-22: 時間外の価格の数(銘柄名は出さない)。
        "usExtendedSession": state.get("usExtendedSession"),
        "usExtendedPriced": state.get("usExtendedPriced"),
        "usExtendedUnpriced": state.get("usExtendedUnpriced"),
        "usExtendedStatus": state.get("usExtendedStatus"),
        "usExtendedCheckedAt": state.get("usExtendedCheckedAt"),
        # 2026-10-22: 日足の取り込みと過去の日足の取得枠(数だけ)。
        "dailyKlineStatus": state.get("dailyKlineStatus"),
        "dailyKlineCheckedAt": state.get("dailyKlineCheckedAt"),
        "dailyKlineRequested": state.get("dailyKlineRequested"),
        "dailyKlineSent": state.get("dailyKlineSent"),
        "dailyKlineSkippedQuota": state.get("dailyKlineSkippedQuota"),
        "dailyKlineFailed": state.get("dailyKlineFailed"),
        "dailyKlineQuotaUsed": state.get("dailyKlineQuotaUsed"),
        "dailyKlineQuotaRemain": state.get("dailyKlineQuotaRemain"),
        "symbolListStatus": state.get("symbolListStatus"),
        "symbolListCount": state.get("symbolListCount"),
        "symbolListCheckedAt": state.get("symbolListCheckedAt"),
        # 2026-10-24: VWAP 用の当日の5分足の取得(数だけ・銘柄名なし)。
        "vwapStatus": state.get("vwapStatus"),
        "vwapCheckedAt": state.get("vwapCheckedAt"),
        "vwapSent": state.get("vwapSent"),
        "vwapSkipped": state.get("vwapSkipped"),
        "vwapFailed": state.get("vwapFailed"),
    }


def _post_signed(path, payload, timeout=20):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"X-ARGUS-ADMIN-TOKEN": TOKEN, "Content-Type": "application/json"}
    if HMAC_SECRET:
        ts, nonce = str(time.time()), secrets.token_hex(8)
        sig = hmac.new(HMAC_SECRET.encode("utf-8"),
                       f"{ts}.{nonce}.".encode("utf-8") + raw, hashlib.sha256).hexdigest()
        headers["X-ARGUS-TIMESTAMP"] = ts
        headers["X-ARGUS-NONCE"] = nonce
        headers["X-ARGUS-SIGNATURE"] = sig
    return requests.post(f"{BACKEND}{path}", data=raw, headers=headers, timeout=timeout)


def send_heartbeat(state=None, disable_jp=None):
    """POST the heartbeat — runs even when every market is closed, so the backend
    can tell 'bridge alive, waiting' from 'bridge dead'. Never raises."""
    try:
        resp = _post_signed("/api/argus/bridge/heartbeat",
                            {"heartbeat": build_heartbeat(state, disable_jp), "source": "moomoo-bridge"})
        return resp.status_code
    except Exception:
        return None


def fetch_market_quotes(qc, codes_by_market, state=None, disable_jp=None, now=None,
                        ret_ok=None):
    """Fetch US and JP SEPARATELY so one market's permission failure can never
    poison the other (Jul-3 incident). Returns (stocks, jp_attempted).
    JP permission error → weekly probe + entitlement_unavailable; other JP
    errors → shorter degraded backoff. US errors are logged but never block JP."""
    state = STATE if state is None else state
    disable_jp = DISABLE_JP if disable_jp is None else disable_jp
    now = time.time() if now is None else now
    ret_ok = RET_OK if ret_ok is None else ret_ok
    stocks = []
    jp_attempted = False

    us_codes = codes_by_market.get("US") or []
    if us_codes:
        try:
            ret, df = qc.get_market_snapshot(us_codes)
            if ret == ret_ok:
                stocks.extend(rows_from_snapshot(df))
                state["lastSnapshotOkAt"] = now
                state["consecutiveSnapshotErrors"] = 0
                state["openDErrorClass"] = None
                state["usLastErrorClass"] = None
            else:
                state["consecutiveSnapshotErrors"] = int(state.get("consecutiveSnapshotErrors") or 0) + 1
                state["openDErrorClass"] = classify_opend_error(df)
                state["usLastErrorClass"] = state["openDErrorClass"]
                state["usSnapshotErrors"] = int(state.get("usSnapshotErrors") or 0) + 1
                print(time.strftime("%H:%M:%S"), "US snapshot error:", str(df)[:160])
        except Exception as e:
            state["consecutiveSnapshotErrors"] = int(state.get("consecutiveSnapshotErrors") or 0) + 1
            state["openDErrorClass"] = classify_opend_error(str(e))
            state["usLastErrorClass"] = state["openDErrorClass"]
            state["usSnapshotErrors"] = int(state.get("usSnapshotErrors") or 0) + 1
            print(time.strftime("%H:%M:%S"), "US snapshot exception:", type(e).__name__, str(e)[:120])

    jp_codes = codes_by_market.get("JP") or []
    if jp_codes and jp_push_active(now, state, disable_jp):
        jp_attempted = True
        try:
            ret, df = qc.get_market_snapshot(jp_codes)
            if ret == ret_ok:
                stocks.extend(rows_from_snapshot(df))
                state["lastSnapshotOkAt"] = now
                state["jpLastErrorClass"] = None
            elif is_permission_error(df):
                state["jpBlockUntil"] = now + JP_ENTITLEMENT_BACKOFF_SEC
                state["jpLastErrorClass"] = "permission"
                state["jpSnapshotErrors"] = int(state.get("jpSnapshotErrors") or 0) + 1
                if now - float(state.get("jpLastErrorLogAt") or 0.0) >= JP_ENTITLEMENT_BACKOFF_SEC - 60:
                    state["jpLastErrorLogAt"] = now
                    print(time.strftime("%H:%M:%S"),
                          f"JP quotes: no permission — JP push suspended "
                          f"{JP_ENTITLEMENT_BACKOFF_SEC // 86400}d (US continues). "
                          "Fix: enable JP quote permission in moomoo, or set ARGUS_DISABLE_JP_QUOTES=1")
            else:
                state["jpBlockUntil"] = now + 300      # transient JP error: 5-min degrade
                state["jpLastErrorClass"] = "other"
                state["jpSnapshotErrors"] = int(state.get("jpSnapshotErrors") or 0) + 1
                if now - float(state.get("jpLastErrorLogAt") or 0.0) >= 240:
                    state["jpLastErrorLogAt"] = now
                    print(time.strftime("%H:%M:%S"), "JP snapshot error (5min backoff):", str(df)[:160])
        except Exception as e:
            state["jpBlockUntil"] = now + 300
            state["jpLastErrorClass"] = "other"
            state["jpSnapshotErrors"] = int(state.get("jpSnapshotErrors") or 0) + 1
            if now - float(state.get("jpLastErrorLogAt") or 0.0) >= 240:
                state["jpLastErrorLogAt"] = now
                print(time.strftime("%H:%M:%S"), "JP snapshot exception:", type(e).__name__, str(e)[:120])
    return stocks, jp_attempted


def record_push_result(stocks, accepted, state=None, now_iso=None):
    """Update last-push bookkeeping (per market) after a successful POST."""
    state = STATE if state is None else state
    import datetime as _dt2
    now_iso = now_iso or _dt2.datetime.now(_dt2.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["lastPushAt"] = now_iso
    state["acceptedLastPush"] = int(accepted or 0)
    if any(s.get("market") == "US" for s in stocks):
        state["lastUsPushAt"] = now_iso
        state["_lastUsPushEpoch"] = time.time()
    if any(s.get("market") == "JP" for s in stocks):
        state["lastJpPushAt"] = now_iso
    return state


def _quote_right(row):
    raw = (row.get("quote_right") or row.get("quote_right_status")
           or row.get("entitlement") or "unknown")
    value = str(raw).strip().lower()
    return value[:40] if value and all(c.isalnum() or c in "_- /" for c in value) else "unknown"


def _exchange_timestamp(value, market):
    """OpenD update_time is market-local. Normalize it before transport so
    the backend never mistakes New York/Tokyo wall time for UTC."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() in ("nan", "nat", "none", "n/a"):
        return None
    try:
        import datetime as _dt
        numeric = float(raw)
        if numeric > 0:
            return _dt.datetime.fromtimestamp(
                numeric, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo
        parsed = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            zone = ZoneInfo("Asia/Tokyo" if market == "JP" else "America/New_York")
            parsed = parsed.replace(tzinfo=zone)
        return parsed.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _first_present(*values):
    for value in values:
        raw = str(value).strip()
        if raw and raw.lower() not in ("nan", "nat", "none", "n/a"):
            return value
    return None


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _snapshot_update_ts(r, market):
    return _exchange_timestamp(_first_present(
        r.get("update_timestamp"), r.get("updateTimestamp"),
        r.get("update_time"), r.get("updateTime")), market)


def rows_from_snapshot(df):
    """moomoo market-snapshot dataframe → quote-push payload rows."""
    quote_right = _quote_right
    exchange_timestamp = _exchange_timestamp
    first_present = _first_present

    stocks = []
    for _, r in df.iterrows():
        code = str(r.get("code", ""))
        market, _, sym = code.partition(".")
        try:
            last = float(r.get("last_price") or 0)
            prev = float(r.get("prev_close_price") or 0)
        except (TypeError, ValueError):
            continue
        if not sym or not math.isfinite(last) or last <= 0:
            continue
        if not math.isfinite(prev) or prev <= 0:
            prev = 0
        try:
            raw_volume = float(r.get("volume") or 0)
            volume = int(raw_volume) if math.isfinite(raw_volume) and raw_volume >= 0 else 0
        except (TypeError, ValueError, OverflowError):
            volume = 0
        exchange_ts = exchange_timestamp(first_present(
            r.get("update_timestamp"), r.get("updateTimestamp"),
            r.get("update_time"), r.get("updateTime")), market.upper())
        right = quote_right(r)
        raw_name = first_present(r.get("name"))
        row = {
            "market": market.upper(),
            "symbol": sym.upper(),
            "name": str(raw_name or "")[:100],
            "price": last,
            "changeAbs": round(last - prev, 4) if prev else 0.0,
            "changePct": round((last - prev) / prev * 100, 4) if prev else 0.0,
            "volume": volume,
            "exchangeTs": exchange_ts,
            # Snapshot success does not itself identify the contracted quote
            # right. Runtime timestamp distribution proves freshness separately.
            "quoteRight": right,
            "entitlement": right,
        }
        for source_key, target_key in (
                ("open_price", "open"), ("high_price", "high"),
                ("low_price", "low"), ("bid_price", "bid"),
                ("ask_price", "ask"), ("turnover", "turnover"),
                ("turnover_rate", "turnoverRate"), ("pe_ratio", "peRatio"),
                ("pb_ratio", "pbRatio")):
            try:
                value = float(r.get(source_key))
                if value == value and abs(value) != float("inf"):
                    row[target_key] = value
            except (TypeError, ValueError):
                pass
        stocks.append(row)
    return stocks


# ── 2026-10-22: 米国の取引時間外の価格(moomoo が主役・Twelve Data を使わない) ──
# 取引所の暦(argus_market_clock)の時間帯を、行の印に使う短い名前へ写す。
# OVERNIGHT_CLOSED は取引日の 20:00〜翌4:00(米国東部)で、夜間取引の時間帯。
_US_PRICE_SESSIONS = {
    "PRE_MARKET": "PRE", "REGULAR": "REGULAR",
    "AFTER_HOURS": "POST", "OVERNIGHT_CLOSED": "OVERNIGHT",
}
# snapshot の欄の頭(公式 get_market_snapshot: pre_* / after_* / overnight_*)
_EXTENDED_FIELD_PREFIX = {"PRE": "pre", "POST": "after", "OVERNIGHT": "overnight"}


def _market_clock():
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    import argus_market_clock
    return argus_market_clock


def us_quote_session(now=None):
    """REGULAR / PRE / POST / OVERNIGHT, or None when no US price session runs.

    週末・休場日は None(夜間取引の有無は推測しない)。"""
    clock = _market_clock()
    state = clock.market_session(clock.US_EQUITY, now)
    if not state.get("isTradingDay"):
        return None
    return _US_PRICE_SESSIONS.get(state.get("session"))


def quote_session_active(now=None):
    return us_quote_session(now) is not None


def _iso_to_datetime(value):
    import datetime as _dt
    try:
        parsed = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def extended_rows_from_snapshot(df, session, now=None):
    """時間外(PRE/POST/OVERNIGHT)の価格の行と、価格が付いていない銘柄の一覧。

    moomoo の snapshot には時間外の価格ごとの時刻が無いため、行の更新時刻
    (update_time)を時間外の価格の時刻として使う。ただしその時刻が今と同じ
    時間外の時間帯の中にある時だけ。外なら(まだ時間外の約定が無い等)
    その銘柄は価格なしとして数え、受信時刻で代用しない。"""
    import datetime as _dt
    prefix = _EXTENDED_FIELD_PREFIX[session]
    now = now or _dt.datetime.now(_dt.timezone.utc)
    rows, unpriced = [], []
    for _, r in df.iterrows():
        code = str(r.get("code", ""))
        market, _, sym = code.partition(".")
        if market.upper() != "US" or not sym:
            continue
        sym = sym.upper()
        price = _finite_number(r.get(f"{prefix}_price"))
        stamp = _snapshot_update_ts(r, "US")
        stamp_at = _iso_to_datetime(stamp) if stamp else None
        # 境界ちょうど(例: 16:00:00 の引けの約定)は時間外の価格の時刻と認めない。
        in_session = (stamp_at is not None
                      and stamp_at <= now + _dt.timedelta(seconds=5)
                      and us_quote_session(stamp_at) == session
                      and us_quote_session(stamp_at - _dt.timedelta(seconds=1)) == session)
        if price is None or price <= 0 or not in_session:
            unpriced.append(sym)
            continue
        right = _quote_right(r)
        row = {
            "market": "US", "symbol": sym,
            "name": str(_first_present(r.get("name")) or "")[:100],
            "price": price,
            "session": session,
            "exchangeTs": stamp,
            "extendedTs": stamp,
            "quoteRight": right, "entitlement": right,
        }
        change = _finite_number(r.get(f"{prefix}_change_val"))
        rate = _finite_number(r.get(f"{prefix}_change_rate"))
        if change is not None and rate is not None:
            # 公式の欄の値(rate は 20 = 20%)をそのまま運ぶ。比べる基準は moomoo の定義。
            row["changeAbs"] = round(change, 4)
            row["changePct"] = round(rate, 4)
        for source_key, target_key in ((f"{prefix}_high_price", "high"),
                                       (f"{prefix}_low_price", "low"),
                                       (f"{prefix}_turnover", "turnover")):
            value = _finite_number(r.get(source_key))
            if value is not None:
                row[target_key] = value
        volume = _finite_number(r.get(f"{prefix}_volume"))
        if volume is not None and volume >= 0:
            row["volume"] = int(volume)
        regular = _finite_number(r.get("last_price"))
        if regular is not None and regular > 0:
            row["regularClose"] = regular
        rows.append(row)
    return rows, unpriced


def fetch_us_extended_quotes(qc, codes, session, state=None, now=None, ret_ok=None):
    """時間外の snapshot を1回だけ取る。数は心拍に出す(夜間の権利が無い等の確認用)。"""
    import datetime as _dt
    state = STATE if state is None else state
    ret_ok = RET_OK if ret_ok is None else ret_ok
    now = now or _dt.datetime.now(_dt.timezone.utc)
    state["usExtendedSession"] = session
    state["usExtendedCheckedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        ret, df = qc.get_market_snapshot(list(codes))
    except Exception as exc:
        state["usExtendedStatus"] = "snapshot_error"
        state["usSnapshotErrors"] = int(state.get("usSnapshotErrors") or 0) + 1
        print(time.strftime("%H:%M:%S"), "US extended snapshot exception:", type(exc).__name__)
        return []
    if ret != ret_ok:
        state["usExtendedStatus"] = "snapshot_error"
        state["usSnapshotErrors"] = int(state.get("usSnapshotErrors") or 0) + 1
        state["usLastErrorClass"] = classify_opend_error(df)
        print(time.strftime("%H:%M:%S"), "US extended snapshot error:", str(df)[:160])
        return []
    state["lastSnapshotOkAt"] = time.time()
    state["consecutiveSnapshotErrors"] = 0
    state["openDErrorClass"] = None
    rows, unpriced = extended_rows_from_snapshot(df, session, now=now)
    state["usExtendedPriced"] = len(rows)
    state["usExtendedUnpriced"] = len(unpriced)
    # 1銘柄も価格が付かない時は、時間帯の権利(特に夜間)が無い可能性を示す。
    state["usExtendedStatus"] = "ok" if rows else "no_price_in_session"
    return rows


# ── 2026-10-22: 米国の日足(確定足)を moomoo から取り込む ─────────────────────
# サーバーからブリッジへは届かないので、サーバーが「欲しい日足の一覧」を
# us-universe?scope=reference で出し、ブリッジが取引時間外に読みに行く。
# 過去の日足の取得枠(get_history_kl_quota)を毎回確かめ、残りを心拍に出し、
# 予備を残して枠を超えないようにする。注文・口座の機能には触れない。
REFERENCE_CHECK_SEC = max(300, int(os.environ.get("ARGUS_REFERENCE_CHECK_SEC", "1800")))
KLINE_QUOTA_RESERVE = max(0, int(os.environ.get("ARGUS_KLINE_QUOTA_RESERVE", "5")))
KLINE_MAX_NEW_PER_RUN = max(0, int(os.environ.get("ARGUS_KLINE_MAX_NEW_PER_RUN", "20")))
KLINE_PAUSE_SEC = 0.6          # 公式の上限 60回/30秒 を下回る間隔
KLINE_MAX_PAGES = 4            # 1000本 × 4 = 約15年分まで
_US_CODE_RE = None


def _valid_us_code(code):
    global _US_CODE_RE
    if _US_CODE_RE is None:
        import re
        _US_CODE_RE = re.compile(r"US\.[A-Z][A-Z0-9.\-]{0,9}")
    return isinstance(code, str) and bool(_US_CODE_RE.fullmatch(code))


def fetch_reference_plan():
    """サーバーの依頼一覧。読めない時は None(古い一覧で取りに行かない)。"""
    try:
        response = requests.get(f"{BACKEND}/api/argus/us-universe",
                                params={"scope": "reference"},
                                headers={"X-ARGUS-ADMIN-TOKEN": TOKEN}, timeout=20)
        if not response.ok:
            return None
        body = response.json()
        return body if isinstance(body, dict) and body.get("scope") == "reference" else None
    except Exception:
        return None


def read_kline_quota(qc, ret_ok=None):
    """(使った数, 残り, 期間内に取得済みのコードの集合) または None。"""
    ret_ok = RET_OK if ret_ok is None else ret_ok
    try:
        ret, data = qc.get_history_kl_quota(get_detail=True)
    except Exception:
        return None
    if ret != ret_ok or not isinstance(data, (list, tuple)) or len(data) < 2:
        return None
    try:
        used, remain = int(data[0]), int(data[1])
    except (TypeError, ValueError):
        return None
    rest = list(data[2:])
    details = rest[0] if len(rest) == 1 and isinstance(rest[0], (list, tuple)) else rest
    codes = {str(item.get("code")) for item in details
             if isinstance(item, dict) and item.get("code")}
    return used, remain, codes


def fetch_daily_rows(qc, code, start, end, ret_ok=None, sleep=None):
    """確定日足 [[日付, 始値, 高値, 安値, 終値, 出来高], ...] と、失敗時の理由の記号。"""
    ret_ok = RET_OK if ret_ok is None else ret_ok
    sleep = time.sleep if sleep is None else sleep
    try:
        from moomoo import KLType, AuType
        ktype, autype = KLType.K_DAY, AuType.QFQ
    except Exception:
        ktype, autype = "K_DAY", "qfq"
    rows, page = [], None
    for page_number in range(KLINE_MAX_PAGES):
        try:
            ret, df, page = qc.request_history_kline(
                code, start=start, end=end, ktype=ktype, autype=autype,
                max_count=1000, page_req_key=page)
        except Exception:
            return None, "api_exception"
        if ret != ret_ok:
            text = str(df).lower()
            return None, ("permission" if "permission" in text
                          else "quota" if "quota" in text
                          else "api_error")
        for _, r in df.iterrows():
            day = str(r.get("time_key") or "")[:10]
            rows.append([day, _finite_number(r.get("open")), _finite_number(r.get("high")),
                         _finite_number(r.get("low")), _finite_number(r.get("close")),
                         _finite_number(r.get("volume"))])
        if not page:
            break
        sleep(KLINE_PAUSE_SEC)
    return rows, None


# ── 2026-10-23: VWAP 用の当日の5分足(通常取引だけ) ─────────────────────────
# サーバーが取引中だけ us-universe?scope=reference の vwap に銘柄を出す。ブリッジは
# 30分ごとに当日の5分足を取って送り、サーバーが VWAP を計算する。取得枠は日足と同じ。
VWAP_CHECK_SEC = max(600, int(os.environ.get("ARGUS_VWAP_CHECK_SEC", "1800")))


def fetch_intraday_rows(qc, code, session_date, ret_ok=None):
    """当日の5分足 [[時刻, 高値, 安値, 終値, 出来高], ...] と、失敗時の理由の記号。
    request_history_kline の extended_time は既定で False(通常取引だけ)。"""
    ret_ok = RET_OK if ret_ok is None else ret_ok
    try:
        from moomoo import KLType, AuType
        ktype, autype = KLType.K_5M, AuType.NONE
    except Exception:
        ktype, autype = "K_5M", "None"
    try:
        ret, df, _page = qc.request_history_kline(
            code, start=session_date, end=session_date, ktype=ktype, autype=autype,
            max_count=200)
    except Exception:
        return None, "api_exception"
    if ret != ret_ok:
        text = str(df).lower()
        return None, ("permission" if "permission" in text
                      else "quota" if "quota" in text else "api_error")
    rows = []
    for _, r in df.iterrows():
        key = str(r.get("time_key") or "")
        if key[:10] != session_date:
            continue
        rows.append([key[:19], _finite_number(r.get("high")), _finite_number(r.get("low")),
                     _finite_number(r.get("close")), _finite_number(r.get("volume"))])
    return rows, None


def run_vwap_job(qc, plan, state=None):
    """依頼された銘柄の当日の5分足を、取得枠の範囲で取り、1銘柄ずつ送る。送った数を返す。"""
    import datetime as _dt
    state = STATE if state is None else state
    session_date = (plan or {}).get("vwapSessionDate")
    codes = [code for code in (plan or {}).get("vwap") or [] if _valid_us_code(code)]
    state["vwapCheckedAt"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not codes or not isinstance(session_date, str):
        state["vwapStatus"] = "not_requested"
        return 0
    quota = read_kline_quota(qc)
    if quota is None:
        state["vwapStatus"] = "quota_unknown"
        return 0
    used, remain, pulled = quota
    sent = skipped = failed = 0
    for code in codes:
        is_new = code not in pulled
        if is_new and remain - KLINE_QUOTA_RESERVE <= 0:
            skipped += 1
            continue
        rows, error = fetch_intraday_rows(qc, code, session_date)
        if is_new and error != "permission":
            remain, used = remain - 1, used + 1
            pulled.add(code)
        if not rows:
            failed += 1
            continue
        try:
            if _post_reference({"kind": "intraday5m", "symbol": code.split(".", 1)[1],
                                "sessionDate": session_date, "bars": rows}):
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        time.sleep(KLINE_PAUSE_SEC)
    state["vwapStatus"] = "ok" if sent else ("quota_reserve" if skipped else "no_bars")
    state["vwapSent"], state["vwapSkipped"], state["vwapFailed"] = sent, skipped, failed
    state["dailyKlineQuotaRemain"] = remain
    return sent


def vwap_job_due(clock, last_at):
    """VWAP 用の5分足は取引中だけ取る。"""
    return clock - last_at >= VWAP_CHECK_SEC and us_quote_session() == "REGULAR"


SYMBOL_LIST_PART_ROWS = 5000


def fetch_us_symbol_rows(qc, ret_ok=None):
    """米国の株式・ETFの一覧 [[記号, 名前, 種類, 取引所], ...]。上場廃止は除く。
    片方でも取れなければ None(半端な一覧で差し替えない)。"""
    ret_ok = RET_OK if ret_ok is None else ret_ok
    try:
        from moomoo import Market, SecurityType
        market, kinds = Market.US, ((SecurityType.STOCK, "stock"), (SecurityType.ETF, "etf"))
    except Exception:
        market, kinds = "US", (("STOCK", "stock"), ("ETF", "etf"))
    rows = []
    for security_type, kind in kinds:
        try:
            ret, df = qc.get_stock_basicinfo(market, security_type)
        except Exception:
            return None
        if ret != ret_ok:
            return None
        for _, r in df.iterrows():
            code = str(r.get("code") or "")
            prefix, _, symbol = code.partition(".")
            if prefix.upper() != "US" or not symbol:
                continue
            if str(r.get("delisting")).strip().lower() in ("true", "1"):
                continue
            exchange = str(_first_present(r.get("exchange_type")) or "").upper()[:24]
            rows.append([symbol.upper(), str(_first_present(r.get("name")) or "")[:120],
                         kind, exchange])
    return rows


def send_us_symbol_list(rows, post=None):
    """分けて送る。全部送れた時だけ True。"""
    post = _post_reference if post is None else post
    run_id = secrets.token_hex(8)
    parts = max(1, (len(rows) + SYMBOL_LIST_PART_ROWS - 1) // SYMBOL_LIST_PART_ROWS)
    for part in range(parts):
        chunk = rows[part * SYMBOL_LIST_PART_ROWS:(part + 1) * SYMBOL_LIST_PART_ROWS]
        if not post({"kind": "symbolList", "runId": run_id, "part": part,
                     "parts": parts, "rows": chunk}):
            return False
    return True


def run_symbol_list_job(qc, state=None):
    import datetime as _dt
    state = STATE if state is None else state
    state["symbolListCheckedAt"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = fetch_us_symbol_rows(qc)
    if rows is None:
        state["symbolListStatus"] = "provider_error"
        return 0
    try:
        sent = send_us_symbol_list(rows)
    except Exception as exc:
        print(time.strftime("%H:%M:%S"), "symbol list post error:", type(exc).__name__)
        sent = False
    state["symbolListStatus"] = "ok" if sent else "post_error"
    state["symbolListCount"] = len(rows)
    return len(rows) if sent else 0


def _post_reference(payload):
    response = _post_signed("/api/argus/us-reference-push", payload, timeout=60)
    return response.ok


def run_daily_reference_job(qc, plan, state=None, sleep=None):
    """依頼された日足を取得枠の範囲で取り、1銘柄ずつ送る。送った数を返す。"""
    import datetime as _dt
    state = STATE if state is None else state
    sleep = time.sleep if sleep is None else sleep
    items = [item for item in (plan or {}).get("daily") or []
             if isinstance(item, dict) and _valid_us_code(item.get("code"))]
    state["dailyKlineCheckedAt"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["dailyKlineRequested"] = len(items)
    if not items:
        state["dailyKlineStatus"] = "up_to_date"
        return 0
    quota = read_kline_quota(qc)
    if quota is None:
        # 残りが分からない時は取りに行かない(枠を超えない側に倒す)。
        state["dailyKlineStatus"] = "quota_unknown"
        return 0
    used, remain, pulled = quota
    sent = new = skipped = failed = 0
    for item in items:
        code = item["code"]
        is_new = code not in pulled
        if is_new and (remain - KLINE_QUOTA_RESERVE <= 0 or new >= KLINE_MAX_NEW_PER_RUN):
            skipped += 1
            continue
        rows, error = fetch_daily_rows(qc, code, str(item.get("start")), str(item.get("end")),
                                       sleep=sleep)
        if is_new and error != "permission":
            remain, used, new = remain - 1, used + 1, new + 1
            pulled.add(code)
        symbol = code.split(".", 1)[1]
        try:
            if rows is None:
                failed += 1
                _post_reference({"kind": "dailyBars", "symbol": symbol, "error": error})
            elif _post_reference({"kind": "dailyBars", "symbol": symbol,
                                  "full": item.get("full") is True, "rows": rows}):
                sent += 1
        except Exception as exc:
            failed += 1
            print(time.strftime("%H:%M:%S"), "daily bars post error:", type(exc).__name__)
        sleep(KLINE_PAUSE_SEC)
    state.update({"dailyKlineQuotaUsed": used, "dailyKlineQuotaRemain": remain,
                  "dailyKlineSent": sent, "dailyKlineSkippedQuota": skipped,
                  "dailyKlineFailed": failed,
                  "dailyKlineStatus": ("quota_reserve_reached" if skipped else
                                       "partial" if failed else "ok")})
    return sent


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


def _fetch_jp_watchlist_codes():
    """JP names the owner's watchlist needs pushed REALTIME (Layer-2B ∪ recently-
    requested frontend symbols). Merged into the 15s push so a newly-added name
    (e.g. JP.6965) goes realtime without editing the CODES env. Best-effort."""
    try:
        r = requests.get(f"{BACKEND}/api/argus/jp-watchlist-codes",
                         headers={"X-ARGUS-ADMIN-TOKEN": TOKEN}, timeout=20)
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


def shared_session_open(now=None):
    """Reuse the repository calendar, including holidays and early closes."""
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from argus_market_clock import market_session, US_EQUITY
    return market_session(US_EQUITY, now)['session'] == 'REGULAR'


def registered_us_codes():
    """One private list read per quote cycle; errors fall back to shared ETFs.

    No saved stale owner set: removing a registration takes effect on the next
    successful read, and an unavailable read cannot authorize old targets.
    """
    try:
        response = requests.get(f"{BACKEND}/api/argus/us-universe",
            params={"scope": "registered"}, headers={"X-ARGUS-ADMIN-TOKEN": TOKEN}, timeout=8)
        if not response.ok:
            return list(_REGIME_ETF_CODES)
        body = response.json()
        if body.get("scope") != "registered":
            return list(_REGIME_ETF_CODES)
        import re
        codes = [code for code in body.get("codes", []) if isinstance(code, str)
                 and re.fullmatch(r"US\.[A-Z][A-Z0-9.\-]{0,5}", code)]
        return list(dict.fromkeys(_REGIME_ETF_CODES + codes))[:32]
    except Exception:
        return list(_REGIME_ETF_CODES)


def shared_quote_cycle(qc, now=None):
    """Prices only: shared ETFs plus confirmed registered US names.

    取引中は通常の価格、時間外(PRE/POST/OVERNIGHT)は時間外の価格を送る。"""
    session = us_quote_session(now)
    if session is None:
        return 0
    codes = registered_us_codes()
    if session == "REGULAR":
        stocks, _ = fetch_market_quotes(qc, {'JP': [], 'US': codes}, disable_jp=True)
    else:
        stocks = fetch_us_extended_quotes(qc, codes, session, now=now)
    allowed = set(codes)
    stocks = [s for s in stocks if s.get('market', '') + '.' + s.get('symbol', '') in allowed]
    if not stocks:
        return 0
    resp = _push_quotes(stocks)
    if not resp.ok:
        return 0
    accepted = resp.json().get('accepted')
    if accepted:
        record_push_result(stocks, accepted)
    return accepted or 0


def reference_job_due(clock, last_at):
    """参照データ(日足など)の依頼を読みに行くか。取引中は読まない。"""
    return clock - last_at >= REFERENCE_CHECK_SEC and us_quote_session() != "REGULAR"


def main():
    if OpenQuoteContext is None:
        print("moomoo-api is not installed: pip3 install moomoo-api", file=sys.stderr)
        sys.exit(1)
    if not TOKEN:
        print("ARGUS_ADMIN_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    print(f"argus-bridge v{BRIDGE_VERSION}: 共有ETFと登録米国株の価格(取引中と時間外); interval={INTERVAL}s")
    # OpenD initialization can wait indefinitely in the SDK. Only one bounded-
    # cadence worker may own that wait; health reporting never waits for it.
    worker = None
    reference_worker = None
    vwap_worker = None
    last_quote_at = last_hb_at = last_reference_at = last_vwap_at = float('-inf')
    while True:
        clock = time.monotonic()
        if clock - last_hb_at >= HEARTBEAT_INTERVAL:
            last_hb_at = clock
            status = send_heartbeat(disable_jp=True)
            if status != 200:
                print('bridge heartbeat unavailable:', status, flush=True)
        if (clock - last_quote_at >= INTERVAL and quote_session_active()
                and (worker is None or not worker.is_alive())):
            last_quote_at = clock
            worker = Thread(target=_shared_quote_worker, daemon=True,
                            name='shared-market-quotes')
            worker.start()
        if (reference_job_due(clock, last_reference_at)
                and (reference_worker is None or not reference_worker.is_alive())):
            last_reference_at = clock
            reference_worker = Thread(target=_reference_worker, daemon=True,
                                      name='us-reference-data')
            reference_worker.start()
        if (vwap_job_due(clock, last_vwap_at)
                and (vwap_worker is None or not vwap_worker.is_alive())):
            last_vwap_at = clock
            vwap_worker = Thread(target=_vwap_worker, daemon=True, name='us-vwap-bars')
            vwap_worker.start()
        time.sleep(min(30, HEARTBEAT_INTERVAL))


def _reference_worker():
    """依頼が無ければ OpenD に接続しない。"""
    qc = None
    try:
        plan = fetch_reference_plan()
        if not plan or not (plan.get("daily") or plan.get("symbolListNeeded") is True):
            if plan is not None:
                STATE["dailyKlineStatus"] = "up_to_date"
            return
        qc = OpenQuoteContext(host=HOST, port=PORT)
        if plan.get("daily"):
            run_daily_reference_job(qc, plan)
        else:
            STATE["dailyKlineStatus"] = "up_to_date"
        if plan.get("symbolListNeeded") is True:
            run_symbol_list_job(qc)
    except Exception as exc:
        print('us reference data unavailable:', type(exc).__name__, flush=True)
    finally:
        if qc is not None:
            qc.close()


def _vwap_worker():
    """依頼が無ければ OpenD に接続しない。"""
    qc = None
    try:
        plan = fetch_reference_plan()
        if not plan or not plan.get("vwap"):
            STATE["vwapStatus"] = "not_requested"
            return
        qc = OpenQuoteContext(host=HOST, port=PORT)
        run_vwap_job(qc, plan)
    except Exception as exc:
        print('us vwap bars unavailable:', type(exc).__name__, flush=True)
    finally:
        if qc is not None:
            qc.close()


def _shared_quote_worker():
    qc = None
    try:
        qc = OpenQuoteContext(host=HOST, port=PORT)
        shared_quote_cycle(qc)
    except Exception as exc:
        print('shared market quote unavailable:', type(exc).__name__, flush=True)
    finally:
        if qc is not None:
            qc.close()


if __name__ == "__main__":
    main()

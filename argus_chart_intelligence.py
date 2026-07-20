# -*- coding: utf-8 -*-
"""Deterministic Chart Intelligence / SHO Method Phase 2.

Pure stdlib calculations only.  The module never performs network I/O, never
calls an LLM, and never places an order.  Inputs are chronological or unordered
OHLCV observations; outputs are public-safe derived facts with explicit data
quality and deterministic IDs.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "argus-chart-intelligence-v1"
STATE_SCHEMA_VERSION = "argus-chart-intelligence-ledger-v1"
METHOD_VERSION = "chart-intelligence-phase2-v1"
MA_WINDOWS = (5, 25, 75, 100, 200)


def _hash(value: Any, length: int = 24) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:length]


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_bars(rows: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Validate/dedupe/sort OHLCV oldest-first without inventing missing data."""
    by_date: Dict[str, Dict[str, Any]] = {}
    reasons: List[str] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            reasons.append("invalid_row")
            continue
        date = str(raw.get("date") or raw.get("periodEnd") or "")[:10]
        close = _finite(raw.get("close"))
        if len(date) != 10 or close is None or close <= 0:
            reasons.append("missing_date_or_close")
            continue
        open_ = _finite(raw.get("open"))
        high = _finite(raw.get("high"))
        low = _finite(raw.get("low"))
        volume = _finite(raw.get("volume"))
        if open_ is None:
            open_ = close
            reasons.append("open_missing_close_used_for_display")
        if high is None or low is None:
            reasons.append("high_low_missing")
            high = max(open_, close) if high is None else high
            low = min(open_, close) if low is None else low
        if min(open_, high, low, close) <= 0 or high < max(open_, close) or low > min(open_, close):
            reasons.append("invalid_ohlc")
            continue
        row = {
            "date": date, "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
            "adjusted": bool(raw.get("adjusted", False)),
            "sourceId": str(raw.get("id") or raw.get("sourceId") or date),
            "availableFrom": str(raw.get("availableFrom") or date),
        }
        if date in by_date:
            reasons.append("duplicate_date_latest_kept")
        by_date[date] = row
    return [by_date[key] for key in sorted(by_date)], sorted(set(reasons))


def _sma(values: Sequence[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    total = 0.0
    for idx, value in enumerate(values):
        total += value
        if idx >= window:
            total -= values[idx - window]
        if idx + 1 >= window:
            out[idx] = total / window
    return out


def _ema(values: Sequence[float], window: int) -> List[Optional[float]]:
    if not values:
        return []
    alpha = 2.0 / (window + 1.0)
    out: List[Optional[float]] = []
    current = values[0]
    for value in values:
        current = value * alpha + current * (1.0 - alpha)
        out.append(current)
    return out


def _rsi(values: Sequence[float], window: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) <= window:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    def score(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)
    out[window] = score(avg_gain, avg_loss)
    for idx in range(window + 1, len(values)):
        avg_gain = (avg_gain * (window - 1) + gains[idx - 1]) / window
        avg_loss = (avg_loss * (window - 1) + losses[idx - 1]) / window
        out[idx] = score(avg_gain, avg_loss)
    return out


def _atr(bars: Sequence[Dict[str, Any]], window: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(bars)
    if not bars:
        return out
    tr: List[float] = []
    for idx, bar in enumerate(bars):
        prev = bars[idx - 1]["close"] if idx else bar["close"]
        tr.append(max(bar["high"] - bar["low"], abs(bar["high"] - prev),
                      abs(bar["low"] - prev)))
    if len(tr) < window:
        return out
    current = sum(tr[:window]) / window
    out[window - 1] = current
    for idx in range(window, len(tr)):
        current = (current * (window - 1) + tr[idx]) / window
        out[idx] = current
    return out


def _parabolic_sar(bars: Sequence[Dict[str, Any]]) -> List[Optional[float]]:
    if len(bars) < 2:
        return [None] * len(bars)
    out: List[Optional[float]] = [None] * len(bars)
    up, af = bars[1]["close"] >= bars[0]["close"], 0.02
    ep = bars[0]["high"] if up else bars[0]["low"]
    sar = bars[0]["low"] if up else bars[0]["high"]
    for idx in range(1, len(bars)):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, bars[idx - 1]["low"], bars[max(0, idx - 2)]["low"])
            if bars[idx]["low"] < sar:
                up, sar, ep, af = False, ep, bars[idx]["low"], 0.02
            elif bars[idx]["high"] > ep:
                ep, af = bars[idx]["high"], min(0.2, af + 0.02)
        else:
            sar = max(sar, bars[idx - 1]["high"], bars[max(0, idx - 2)]["high"])
            if bars[idx]["high"] > sar:
                up, sar, ep, af = True, ep, bars[idx]["high"], 0.02
            elif bars[idx]["low"] < ep:
                ep, af = bars[idx]["low"], min(0.2, af + 0.02)
        out[idx] = sar
    return out


def calculate_indicators(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    bars, reasons = normalize_bars(rows)
    closes = [bar["close"] for bar in bars]
    result: Dict[str, Any] = {
        "bars": [], "status": "live" if len(bars) >= 25 else "insufficient_data",
        "missingReasons": reasons, "methodVersion": METHOD_VERSION,
    }
    if not bars:
        result["status"] = "missing"
        result["missingReasons"] = sorted(set(reasons + ["ohlcv_unavailable"]))
        return result
    mas = {window: _sma(closes, window) for window in MA_WINDOWS}
    ma20 = _sma(closes, 20)
    rsi = _rsi(closes)
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    macd = [a - b if a is not None and b is not None else None
            for a, b in zip(ema12, ema26)]
    signal = _ema([float(x or 0.0) for x in macd], 9)
    atr = _atr(bars)
    sar = _parabolic_sar(bars)
    for idx, bar in enumerate(bars):
        seg20 = closes[max(0, idx - 19):idx + 1]
        sd = statistics.pstdev(seg20) if len(seg20) == 20 else None
        conversion_seg = bars[max(0, idx - 8):idx + 1]
        base_seg = bars[max(0, idx - 25):idx + 1]
        span_b_seg = bars[max(0, idx - 51):idx + 1]
        conv = ((max(x["high"] for x in conversion_seg) + min(x["low"] for x in conversion_seg)) / 2
                if len(conversion_seg) == 9 else None)
        base = ((max(x["high"] for x in base_seg) + min(x["low"] for x in base_seg)) / 2
                if len(base_seg) == 26 else None)
        span_a = (conv + base) / 2 if conv is not None and base is not None else None
        span_b = ((max(x["high"] for x in span_b_seg) + min(x["low"] for x in span_b_seg)) / 2
                  if len(span_b_seg) == 52 else None)
        result["bars"].append({
            **bar,
            "ma": {str(w): round(mas[w][idx], 6) if mas[w][idx] is not None else None
                   for w in MA_WINDOWS},
            "bollinger": ({"middle": round(ma20[idx], 6),
                           "upper2": round(ma20[idx] + 2 * sd, 6),
                           "lower2": round(ma20[idx] - 2 * sd, 6),
                           "upper3": round(ma20[idx] + 3 * sd, 6),
                           "lower3": round(ma20[idx] - 3 * sd, 6),
                           "lower4": round(ma20[idx] - 4 * sd, 6)}
                          if ma20[idx] is not None and sd is not None else None),
            "rsi14": round(rsi[idx], 4) if rsi[idx] is not None else None,
            "macd": ({"line": round(macd[idx], 6), "signal": round(signal[idx], 6),
                      "histogram": round(macd[idx] - signal[idx], 6)}
                     if macd[idx] is not None and signal[idx] is not None else None),
            "atr14": round(atr[idx], 6) if atr[idx] is not None else None,
            "sar": round(sar[idx], 6) if sar[idx] is not None else None,
            "ichimoku": {"conversion": conv, "base": base, "spanA": span_a,
                          "spanB": span_b},
            "volumeRatio20": (round(bar["volume"] / (sum(
                float(x["volume"] or 0) for x in bars[max(0, idx - 19):idx + 1]) / 20), 3)
                              if idx >= 19 and bar["volume"] is not None and
                              all(x["volume"] is not None for x in bars[idx - 19:idx + 1]) and
                              sum(float(x["volume"] or 0) for x in bars[idx - 19:idx + 1]) > 0 else None),
        })
    swings = swing_points(result["bars"])
    highs = [x for x in swings if x["kind"] == "swing_high"]
    lows = [x for x in swings if x["kind"] == "swing_low"]
    result["priceStructure"] = {
        "high": ("higher_high" if highs[-1]["price"] > highs[-2]["price"] else
                 "lower_high" if highs[-1]["price"] < highs[-2]["price"] else "equal_high")
                if len(highs) >= 2 else "unconfirmed",
        "low": ("higher_low" if lows[-1]["price"] > lows[-2]["price"] else
                "lower_low" if lows[-1]["price"] < lows[-2]["price"] else "equal_low")
               if len(lows) >= 2 else "unconfirmed",
        "inputIds": ([highs[-2]["sourceId"], highs[-1]["sourceId"]]
                     if len(highs) >= 2 else []) +
                    ([lows[-2]["sourceId"], lows[-1]["sourceId"]]
                     if len(lows) >= 2 else []),
        "status": "live" if len(highs) >= 2 and len(lows) >= 2 else "insufficient_data",
        "methodVersion": METHOD_VERSION,
    }
    return result


def swing_points(bars: Sequence[Dict[str, Any]], radius: int = 2) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    for idx in range(radius, len(bars) - radius):
        window = bars[idx - radius:idx + radius + 1]
        if bars[idx]["high"] == max(x["high"] for x in window):
            points.append({"date": bars[idx]["date"], "price": bars[idx]["high"],
                           "kind": "swing_high", "sourceId": bars[idx]["sourceId"]})
        if bars[idx]["low"] == min(x["low"] for x in window):
            points.append({"date": bars[idx]["date"], "price": bars[idx]["low"],
                           "kind": "swing_low", "sourceId": bars[idx]["sourceId"]})
    return points


def detect_gaps(bars: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    for prev, cur in zip(bars, bars[1:]):
        if cur["low"] > prev["high"]:
            lower, upper, direction = prev["high"], cur["low"], "up"
        elif cur["high"] < prev["low"]:
            lower, upper, direction = cur["high"], prev["low"], "down"
        else:
            continue
        body = {"date": cur["date"], "direction": direction, "lower": lower,
                "upper": upper, "filled": False,
                "inputIds": [prev["sourceId"], cur["sourceId"]]}
        body["id"] = "gap-" + _hash(body)
        gaps.append(body)
    return gaps


def support_resistance_zones(indicators: Dict[str, Any]) -> List[Dict[str, Any]]:
    bars = indicators.get("bars") or []
    if len(bars) < 20:
        return []
    points = swing_points(bars)
    latest = bars[-1]
    atr = latest.get("atr14") or max(latest["close"] * 0.01, 1e-9)
    candidates = list(points)
    for window in (25, 75, 200):
        value = (latest.get("ma") or {}).get(str(window))
        if value is not None:
            candidates.append({"date": latest["date"], "price": value,
                               "kind": f"ma{window}", "sourceId": latest["sourceId"]})
    cloud = latest.get("ichimoku") or {}
    for key in ("spanA", "spanB"):
        if cloud.get(key) is not None:
            candidates.append({"date": latest["date"], "price": cloud[key],
                               "kind": f"ichimoku_{key}", "sourceId": latest["sourceId"]})
    clusters: List[List[Dict[str, Any]]] = []
    for point in sorted(candidates, key=lambda x: x["price"]):
        if not clusters or abs(point["price"] - statistics.mean(x["price"] for x in clusters[-1])) > atr:
            clusters.append([point])
        else:
            clusters[-1].append(point)
    zones: List[Dict[str, Any]] = []
    for cluster in clusters:
        center = statistics.mean(x["price"] for x in cluster)
        lower, upper = center - atr * 0.5, center + atr * 0.5
        tests = [bar for bar in bars if bar["low"] <= upper and bar["high"] >= lower]
        breaks = [bar for bar in bars if bar["close"] < lower or bar["close"] > upper]
        last_test = tests[-1]["date"] if tests else max(x["date"] for x in cluster)
        recent = bars[-3:]
        if latest["close"] < lower and any(x["close"] >= lower for x in recent[:-1]):
            status = "broken"
        elif latest["close"] > upper and any(x["close"] <= upper for x in recent[:-1]):
            status = "reclaimed"
        elif len(tests) >= 2 or any(not x["kind"].startswith("swing") for x in cluster):
            status = "active"
        else:
            status = "unconfirmed"
        body = {
            "lower": round(lower, 6), "upper": round(upper, 6),
            "center": round(center, 6),
            "firstObservedAt": min(x["date"] for x in cluster),
            "lastTestedAt": last_test, "testCount": len(tests),
            "breakCount": len(breaks),
            "sourceTypes": sorted(set(x["kind"] for x in cluster)),
            "inputIds": sorted(set(x["sourceId"] for x in cluster)),
            "strength": "strong" if len(tests) >= 4 and len(cluster) >= 2 else
                        "medium" if len(tests) >= 2 else "weak",
            "status": status, "methodVersion": METHOD_VERSION,
            "source": "ohlcv_derived", "periodEnd": last_test,
            "publishedAt": None, "availableFrom": last_test,
            "calculatedAt": latest["date"], "missingReason": None,
        }
        body["id"] = "zone-" + _hash({k: body[k] for k in
                                        ("center", "firstObservedAt", "sourceTypes")})
        zones.append(body)
    return zones


def _turn(rule: str, effective: str, inputs: Sequence[str], status: str,
          facts: Sequence[str], direction: str, classification: str = "derived",
          detection_mode: str = "live", severity: str = "watch") -> Dict[str, Any]:
    base = {"ruleId": rule, "ruleVersion": "v1", "effectiveFrom": effective,
            "availableFrom": effective, "inputIds": sorted(set(inputs)),
            "status": status, "facts": list(facts), "direction": direction,
            "classification": classification, "detectionMode": detection_mode,
            "severity": severity, "methodVersion": METHOD_VERSION}
    base.update({"source": "ohlcv_derived", "periodEnd": effective,
                 "publishedAt": None, "calculatedAt": effective,
                 "missingReason": None})
    base["id"] = "ctp-" + _hash(base)
    return base


def technical_turning_points(indicators: Dict[str, Any], zones: Sequence[Dict[str, Any]],
                             *, detected_at: Optional[str] = None) -> List[Dict[str, Any]]:
    bars = indicators.get("bars") or []
    if len(bars) < 26:
        return []
    out: List[Dict[str, Any]] = []
    swings = swing_points(bars)
    swing_lows = [x for x in swings if x["kind"] == "swing_low"]
    swing_highs = [x for x in swings if x["kind"] == "swing_high"]
    for idx in range(25, len(bars)):
        cur, prev = bars[idx], bars[idx - 1]
        ma25 = (cur.get("ma") or {}).get("25")
        prev_ma25 = (prev.get("ma") or {}).get("25")
        if ma25 is None or prev_ma25 is None:
            continue
        inputs = [prev["sourceId"], cur["sourceId"]]
        mode = "live" if not detected_at or cur["availableFrom"] >= detected_at[:10] else "retrospective"
        below = cur["close"] < ma25
        prev_below = prev["close"] < prev_ma25
        if below and not prev_below:
            out.append(_turn("TREND_STRUCTURE_BREAK", cur["date"], inputs,
                             "candidate", ["終値が25日線を下回った"], "down",
                             detection_mode=mode))
        if below and prev_below:
            slope_down = ma25 < ((bars[idx - 5].get("ma") or {}).get("25") or ma25)
            ma5 = (cur.get("ma") or {}).get("5")
            recent_low = max([x["price"] for x in swing_lows if x["date"] < cur["date"]][-3:] or [-math.inf])
            structural = (ma5 is not None and ma5 < ma25) or slope_down or cur["close"] < recent_low
            if structural:
                out.append(_turn("TREND_STRUCTURE_BREAK", cur["date"], inputs,
                                 "confirmed", ["終値が25日線を2営業日連続で下回った",
                                               "短期構造または25日線傾斜も悪化"],
                                 "down", detection_mode=mode, severity="warning"))
        if cur["close"] >= ma25 and prev_below:
            out.append(_turn("TREND_STRUCTURE_RECLAIM", cur["date"], inputs,
                             "confirmed", ["終値が25日線を回復"], "up",
                             detection_mode=mode))
            out.append(_turn("TREND_STRUCTURE_BREAK", cur["date"], inputs,
                             "invalidated", ["25日線を回復し下抜け候補を無効化"], "up",
                             detection_mode=mode, severity="info"))
    # RSI divergence uses completed swing pairs only; confirmation is separate.
    for kind, direction in (("swing_high", "bearish"), ("swing_low", "bullish")):
        pts = [x for x in swings if x["kind"] == kind]
        if len(pts) < 2:
            continue
        first, second = pts[-2], pts[-1]
        index = {x["date"]: x for x in bars}
        a, b = index[first["date"]], index[second["date"]]
        if a.get("rsi14") is None or b.get("rsi14") is None:
            continue
        diverged = ((b["close"] > a["close"] and b["rsi14"] < a["rsi14"])
                    if direction == "bearish" else
                    (b["close"] < a["close"] and b["rsi14"] > a["rsi14"]))
        if diverged:
            divergence_mode = ("live" if not detected_at or
                               b.get("availableFrom", b["date"]) >= detected_at[:10]
                               else "retrospective")
            out.append(_turn("RSI_DIVERGENCE", b["date"],
                             [first["sourceId"], second["sourceId"]], "candidate",
                             ["価格とRSIの方向に不一致を検出", "支持抵抗による確認は未完了"],
                             direction, classification="experimental",
                             detection_mode=divergence_mode))
            last = bars[-1]
            confirmed = (last["close"] < b["low"] if direction == "bearish"
                         else last["close"] > b["high"])
            if confirmed:
                out.append(_turn("RSI_DIVERGENCE", last["date"],
                                 [b["sourceId"], last["sourceId"]], "confirmed",
                                 ["RSI不一致後に価格構造でも確認"], direction,
                                 classification="experimental", severity="warning",
                                 detection_mode=("live" if not detected_at or
                                                 last.get("availableFrom", last["date"]) >= detected_at[:10]
                                                 else "retrospective")))
    last = bars[-1]
    bb = last.get("bollinger") or {}
    atr = last.get("atr14")
    if bb and atr and (last["close"] <= bb.get("lower3", -math.inf)
                       or abs(last["close"] - (last.get("ma") or {}).get("25", last["close"])) >= 3 * atr):
        out.append(_turn("EXTREME_DEVIATION", last["date"], [last["sourceId"]],
                         "confirmed", ["極端な下方乖離", "反発を保証するシグナルではない"],
                         "down", classification="experimental", severity="watch"))
    near_resistance = [z for z in zones if z["lower"] <= last["high"] + (atr or 0)
                       and z["center"] >= last["close"]]
    if len(near_resistance) >= 2 and last["close"] < last["open"] and \
            (last.get("volumeRatio20") is None or last["volumeRatio20"] < 1.0):
        out.append(_turn("RESISTANCE_CLUSTER_REJECTION", last["date"],
                         [last["sourceId"]] + [z["id"] for z in near_resistance],
                         "candidate", ["抵抗帯クラスターで反落", "参考分類：壁ドン"],
                         "down", classification="experimental"))
    return sorted({x["id"]: x for x in out}.values(),
                  key=lambda x: (x["effectiveFrom"], x["ruleId"], x["status"]))


def _align_series(left: Iterable[Dict[str, Any]], right: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lrows, _ = normalize_bars(left)
    rrows, _ = normalize_bars(right)
    rhs = {x["date"]: x for x in rrows}
    return [{"date": x["date"], "left": x["close"], "right": rhs[x["date"]]["close"],
             "inputIds": [x["sourceId"], rhs[x["date"]]["sourceId"]]}
            for x in lrows if x["date"] in rhs and rhs[x["date"]]["close"] > 0]


def relative_strength(series_id: str, left: Iterable[Dict[str, Any]],
                      right: Iterable[Dict[str, Any]], *, classification: str = "derived") -> Dict[str, Any]:
    joined = _align_series(left, right)
    history = [{"date": x["date"], "value": x["left"] / x["right"],
                "inputIds": x["inputIds"]} for x in joined]
    values = [x["value"] for x in history]
    def change(days: int) -> Optional[float]:
        return (round((values[-1] / values[-1 - days] - 1) * 100, 4)
                if len(values) > days and values[-1 - days] else None)
    ma5 = sum(values[-5:]) / 5 if len(values) >= 5 else None
    ma20 = sum(values[-20:]) / 20 if len(values) >= 20 else None
    slope20 = ((values[-1] - values[-20]) / 19 if len(values) >= 20 else None)
    turn = None
    if len(values) >= 22:
        prev5 = sum(values[-6:-1]) / 5
        prev20 = sum(values[-21:-1]) / 20
        if ma5 is not None and ma20 is not None:
            turn = "improving" if ma5 > ma20 and prev5 <= prev20 else \
                   "deteriorating" if ma5 < ma20 and prev5 >= prev20 else None
    latest = values[-1] if values else None
    percentile = (round(100 * sum(1 for x in values if x <= latest) / len(values), 1)
                  if latest is not None else None)
    body = {"seriesId": series_id, "latestValue": latest, "change5Pct": change(5),
            "change20Pct": change(20), "slope20": slope20,
            "shortMA": ma5, "mediumMA": ma20, "directionTurn": turn,
            "historicalPercentile": percentile, "classification": classification,
            "status": "live" if len(values) >= 20 else "insufficient_data",
            "history": history[-1300:], "methodVersion": METHOD_VERSION}
    body.update({"source": "price_ratio_derived",
                 "periodEnd": history[-1]["date"] if history else None,
                 "publishedAt": None,
                 "availableFrom": history[-1]["date"] if history else None,
                 "calculatedAt": history[-1]["date"] if history else None,
                 "inputIds": history[-1]["inputIds"] if history else [],
                 "missingReason": None if history else "missing_series"})
    body["id"] = "rs-" + _hash({"seriesId": series_id,
                                  "lastDate": history[-1]["date"] if history else None,
                                  "latest": latest})
    return body


def relative_strength_turning_points(
        rows: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert only observed short/medium crossovers into append-only points."""
    out: List[Dict[str, Any]] = []
    for series_id, row in sorted((rows or {}).items()):
        direction = row.get("directionTurn")
        effective = row.get("periodEnd")
        if direction not in {"improving", "deteriorating"} or not effective:
            continue
        fact = (f"{series_id}が相対優位方向へ転換" if direction == "improving"
                else f"{series_id}が相対劣位方向へ転換")
        body = {
            "ruleId": "RELATIVE_STRENGTH_TURN", "ruleVersion": "v1",
            "seriesId": series_id, "effectiveFrom": effective,
            "availableFrom": row.get("availableFrom") or effective,
            "inputIds": list(row.get("inputIds") or []), "status": "confirmed",
            "facts": [fact], "direction": direction,
            "classification": row.get("classification") or "derived",
            "detectionMode": "live", "severity": "watch",
            "methodVersion": METHOD_VERSION, "source": "price_ratio_derived",
            "periodEnd": effective, "publishedAt": None,
            "calculatedAt": row.get("calculatedAt") or effective,
            "missingReason": None,
        }
        body["id"] = "ctp-" + _hash(body)
        out.append(body)
    return out


def rotation_map(series: Dict[str, Iterable[Dict[str, Any]]], benchmark: str = "TOPIX") -> List[Dict[str, Any]]:
    base = list(series.get(benchmark) or [])
    out = []
    for label, rows in series.items():
        if label == benchmark:
            continue
        rs = relative_strength(f"rotation.{label.lower()}", rows, base)
        c5, c20 = rs["change5Pct"], rs["change20Pct"]
        state = "missing" if c5 is None or c20 is None else \
                "improving" if c5 > 0 and c20 > 0 else \
                "deteriorating" if c5 < 0 and c20 < 0 else "mixed"
        out.append({"label": label, "relative5Pct": c5, "relative20Pct": c20,
                    "state": state, "status": rs["status"], "seriesId": rs["seriesId"]})
    return sorted(out, key=lambda x: (x["relative20Pct"] is None,
                                      -(x["relative20Pct"] or -999)))


def reaction_anomalies(events: Iterable[Dict[str, Any]], bars_input: Iterable[Dict[str, Any]],
                       sector_input: Optional[Iterable[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    bars, _ = normalize_bars(bars_input)
    by_date = {x["date"]: i for i, x in enumerate(bars)}
    sector, _ = normalize_bars(sector_input or [])
    sector_by_date = {x["date"]: x for x in sector}
    out = []
    for event in events or []:
        date = str(event.get("availableFrom") or event.get("date") or "")[:10]
        idx = by_date.get(date)
        if idx is None or idx == 0 or idx + 1 >= len(bars):
            continue
        before, day, after = bars[idx - 1], bars[idx], bars[idx + 1]
        event_class = str(event.get("classification") or event.get("kind") or "unconfirmed")
        good = event_class in {"earnings_beat", "upward_revision", "good_news"}
        bad = event_class in {"earnings_miss", "downward_revision", "bad_news"}
        avg_vol = statistics.mean(float(x["volume"] or 0) for x in bars[max(0, idx - 20):idx])
        high_volume = day["volume"] is not None and avg_vol > 0 and day["volume"] > avg_vol
        gap_up_red = day["open"] > before["close"] and day["close"] < day["open"]
        weak_close = day["close"] <= day["low"] + (day["high"] - day["low"]) * 0.25
        support_held = day["low"] >= before["low"] * 0.99 and after["low"] >= before["low"] * 0.99
        return_pct = (after["close"] / before["close"] - 1) * 100
        sector_row = sector_by_date.get(after["date"])
        sector_return = ((sector_row["close"] / sector_by_date[before["date"]]["close"] - 1) * 100
                         if sector_row and before["date"] in sector_by_date else None)
        rule = None
        facts: List[str] = []
        support_broken = day["low"] < before["low"] or after["low"] < before["low"]
        sector_underperformed = sector_return is None or return_pct < sector_return
        sector_outperformed = sector_return is None or return_pct > sector_return
        if (good and return_pct < 0 and high_volume and sector_underperformed
                and (gap_up_red or weak_close or support_broken)):
            rule = "GOOD_NEWS_BAD_REACTION"
            facts = ["好材料後に価格が下落", "20日平均超の出来高",
                     "ギャップアップ後の陰線または安値圏引け"]
            if support_broken:
                facts.append("発表前安値を下回った")
            if sector_return is not None:
                facts.append("セクター比で劣後")
        elif bad and return_pct >= 0 and high_volume and support_held and sector_outperformed:
            rule = "BAD_NEWS_RESILIENT_REACTION"
            facts = ["悪材料後も価格が下落せず", "出来高を伴い支持を維持"]
            if sector_return is not None:
                facts.append("セクター比で優位")
        if not rule:
            continue
        if sector_return is None:
            facts.append("セクター比較は未確認")
        body = {"ruleId": rule, "ruleVersion": "v1", "eventId": event.get("id"),
                "effectiveFrom": after["date"], "availableFrom": date,
                "inputIds": [before["sourceId"], day["sourceId"], after["sourceId"]],
                "facts": facts, "causeStatus": "原因未確認",
                "priceReactionStatus": "価格反応のみ確認",
                "classification": "derived", "methodVersion": METHOD_VERSION}
        body.update({"source": "event_and_ohlcv_derived", "periodEnd": after["date"],
                     "publishedAt": event.get("publishedAt"), "calculatedAt": after["date"],
                     "missingReason": "sector_comparison_missing" if sector_return is None else None})
        body["id"] = "reaction-" + _hash(body)
        out.append(body)
    return out


def relationship_breaks(*, ledger_summary: Optional[Dict[str, Any]] = None,
                        relative: Optional[Dict[str, Dict[str, Any]]] = None,
                        eps_change: Optional[float] = None,
                        per_change: Optional[float] = None) -> List[Dict[str, Any]]:
    ledger_summary = ledger_summary or {}
    relative = relative or {}
    candidates: List[Tuple[str, List[str]]] = []
    dollar_nikkei = relative.get("dollar_nikkei") or {}
    if ledger_summary.get("foreignFlow") == "INFLOW" and (dollar_nikkei.get("change5Pct") or 0) < 0:
        candidates.append(("foreign_flow_vs_dollar_nikkei",
                           ["海外投資家買い越しに対しドル建て日経平均が下落"]))
    breadth = ledger_summary.get("breadth")
    nikkei = relative.get("nikkei_sp500") or {}
    if (nikkei.get("change5Pct") or 0) > 0 and breadth in {"OVERSOLD_CANDIDATE", "DETERIORATING"}:
        candidates.append(("index_vs_breadth", ["指数優位に対し市場の広がりが悪化"]))
    if eps_change is not None and per_change is not None and eps_change > 0 and per_change < 0:
        candidates.append(("eps_vs_per", ["EPS上昇に対し日経平均PERが縮小"]))
    out = []
    for relation, facts in candidates:
        body = {"ruleId": "RELATIONSHIP_BREAK", "relationId": relation,
                "facts": facts + ["通常関係との不一致を検出", "理由は未確認"],
                "status": "candidate", "classification": "experimental",
                "methodVersion": METHOD_VERSION}
        body.update({"source": "ledger_and_relative_strength", "periodEnd": None,
                     "publishedAt": None, "availableFrom": None,
                     "calculatedAt": None, "inputIds": [], "missingReason": None})
        body["id"] = "relationship-" + _hash(body)
        out.append(body)
    return out


def technical_critique(report: Dict[str, Any]) -> List[Dict[str, str]]:
    bars = (report.get("indicators") or {}).get("bars") or []
    points = report.get("turningPoints") or []
    zones = report.get("zones") or []
    lines: List[Dict[str, str]] = []
    latest = bars[-1] if bars else None
    confirmed = next((x for x in reversed(points) if x.get("status") == "confirmed"), None)
    lines.append({"label": "構造", "text": (" / ".join(confirmed.get("facts") or [])
                                                if confirmed else "構造変化は未確認")})
    if latest and latest.get("rsi14") is not None:
        macd = latest.get("macd") or {}
        lines.append({"label": "勢い", "text":
                      f"RSI14は{latest['rsi14']:.1f}。MACDヒストグラムは"
                      f"{macd.get('histogram'):.2f}。" if macd.get("histogram") is not None
                      else f"RSI14は{latest['rsi14']:.1f}。MACDは未確認。"})
    else:
        lines.append({"label": "勢い", "text": "未確認"})
    active = [z for z in zones if z.get("status") in {"active", "reclaimed"}]
    lines.append({"label": "需給", "text":
                  f"支持抵抗帯を{len(active)}帯確認。" if active else "支持抵抗帯は未確認"})
    valuation = report.get("valuationLevels") or []
    lines.append({"label": "評価", "text":
                  f"利用可能なEPSからPER評価水準を{len(valuation)}本算出。" if valuation
                  else "評価水準は未確認"})
    if latest:
        ma25 = (latest.get("ma") or {}).get("25")
        volume_ratio = latest.get("volumeRatio20")
        if ma25 is None:
            change = "25日線の算出後に判断変更条件を確認。"
        elif latest["close"] < ma25:
            change = f"25日線{ma25:.2f}を終値で回復した場合に構造を再確認。"
        elif volume_ratio is not None and volume_ratio >= 1.0:
            change = f"25日線{ma25:.2f}を維持し、主要抵抗帯を出来高増で回復できるか確認。"
        else:
            change = f"25日線{ma25:.2f}の維持と出来高増を確認。"
    else:
        change = "価格データ取得後に再判定。"
    lines.append({"label": "判断変更", "text": change})
    # Labels are unique and lines are capped by construction.
    return lines[:5]


def conditional_scenarios(report: Dict[str, Any]) -> List[Dict[str, str]]:
    bars = (report.get("indicators") or {}).get("bars") or []
    zones = report.get("zones") or []
    latest = bars[-1] if bars else None
    resistance = min([z["center"] for z in zones if latest and z["center"] > latest["close"]] or [None])
    support = max([z["center"] for z in zones if latest and z["center"] < latest["close"]] or [None])
    return [
        {"label": "強気条件", "text": (f"主要抵抗帯{resistance:.2f}を出来高増で回復。"
                                           if resistance is not None else "抵抗帯確認後に判定。")},
        {"label": "基本条件", "text": "支持帯と抵抗帯の間では方向を断定せず持ち合いとして監視。"},
        {"label": "弱気条件", "text": (f"主要支持帯{support:.2f}を終値で割り、相対強弱も悪化。"
                                           if support is not None else "支持帯確認後に判定。")},
    ]


def valuation_levels(market_ledger: Optional[Dict[str, Any]], as_of: str) -> List[Dict[str, Any]]:
    if not isinstance(market_ledger, dict):
        return []
    history = [x for x in (market_ledger.get("valuationHistory") or [])
               if x.get("value") is not None and
               str(x.get("availableFrom") or x.get("asOf") or "") <= as_of[:10]]
    if not history:
        metrics = market_ledger.get("derivedMetrics") or []
        history = [x for x in metrics if x.get("metricId") == "valuation.eps"
                   and str(x.get("asOf") or "") <= as_of[:10] and x.get("value") is not None]
    history.sort(key=lambda x: str(x.get("asOf") or ""))
    if not history:
        return []
    out = []
    for multiple in range(16, 22):
        points = [{"date": x.get("asOf"), "availableFrom": x.get("availableFrom") or x.get("asOf"),
                   "value": round(float(x["value"]) * multiple, 2),
                   "inputIds": x.get("inputObservationIds") or x.get("inputIds") or []}
                  for x in history]
        latest = points[-1]
        out.append({"multiple": multiple, "value": latest["value"],
                    "asOf": latest["date"], "availableFrom": latest["availableFrom"],
                    "inputIds": latest["inputIds"], "history": points[-1300:],
                    "labelJa": ("低評価帯" if multiple == 17 else "基準評価帯" if multiple == 18
                                else "高評価帯" if multiple in (19, 20)
                                else "SHO参考上限／高評価帯" if multiple == 21 else "評価水準"),
                    "classification": "sho_heuristic" if multiple == 21 else "derived"})
    return out


def analyze(symbol: str, market: str, rows: Iterable[Dict[str, Any]], *,
            now_iso: str, market_ledger: Optional[Dict[str, Any]] = None,
            events: Optional[Iterable[Dict[str, Any]]] = None,
            sector_rows: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    indicators = calculate_indicators(rows)
    zones = support_resistance_zones(indicators)
    turns = technical_turning_points(indicators, zones, detected_at=now_iso)
    reactions = reaction_anomalies(events or [], rows, sector_rows)
    report: Dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION, "methodVersion": METHOD_VERSION,
        "asOf": now_iso, "symbol": symbol, "market": market,
        "source": "existing_market_data_cache", "periodEnd":
            ((indicators.get("bars") or [{}])[-1].get("date") if indicators.get("bars") else None),
        "publishedAt": None, "availableFrom":
            ((indicators.get("bars") or [{}])[-1].get("availableFrom") if indicators.get("bars") else None),
        "calculatedAt": now_iso, "status": indicators.get("status"),
        "missingReasons": indicators.get("missingReasons") or [],
        "indicators": indicators, "zones": zones, "turningPoints": turns,
        "reactionAnomalies": reactions,
        "valuationLevels": valuation_levels(market_ledger, now_iso),
        "relationshipBreaks": [],
        "noteJa": "決定論的な判断支援であり、未来予測・売買指示・自動売買ではありません。",
    }
    # A stale last bar may still be displayed, but it cannot produce a
    # confirmed current-state claim.  Eight calendar days tolerates long
    # weekends and common holiday sequences without treating old caches live.
    try:
        last_date = datetime.strptime(str(report["periodEnd"]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now_date = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        if (now_date - last_date).days > 8:
            report["status"] = "stale"
            report["missingReasons"] = sorted(set(report["missingReasons"] + ["stale_price"] ))
            for point in report["turningPoints"]:
                if point.get("status") == "confirmed":
                    point["status"] = "candidate"
                    point["facts"] = list(point.get("facts") or []) + ["価格が古いため確認保留"]
    except (TypeError, ValueError):
        pass
    report["critique"] = technical_critique(report)
    report["scenarios"] = conditional_scenarios(report)
    report["reportId"] = "chart-" + _hash({"symbol": symbol, "market": market,
                                             "periodEnd": report["periodEnd"],
                                             "methodVersion": METHOD_VERSION})
    return report


def empty_state() -> Dict[str, Any]:
    return {"schemaVersion": STATE_SCHEMA_VERSION, "snapshots": [], "zones": [], "turningPoints": [],
            "reactionAnomalies": [], "relationshipBreaks": [], "invalidations": [],
            "lastUpdatedAt": None, "methodVersion": METHOD_VERSION}


def normalize_state(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    state = empty_state()
    for key in ("snapshots", "zones", "turningPoints", "reactionAnomalies",
                "relationshipBreaks", "invalidations"):
        state[key] = [x for x in source.get(key, []) if isinstance(x, dict)]
    state["lastUpdatedAt"] = source.get("lastUpdatedAt")
    return state


def merge_report(state: Dict[str, Any], report: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    out = normalize_state(state)
    snapshot = {"id": report.get("reportId"), "symbol": report.get("symbol"),
                "market": report.get("market"), "periodEnd": report.get("periodEnd"),
                "calculatedAt": report.get("calculatedAt"),
                "methodVersion": report.get("methodVersion"), "status": report.get("status"),
                "zoneIds": [x.get("id") for x in report.get("zones", [])],
                "inputIds": [x.get("sourceId") for x in
                             (report.get("indicators", {}).get("bars") or [])[-260:]]}
    if snapshot["id"] and snapshot["id"] not in {x.get("id") for x in out["snapshots"]}:
        out["snapshots"].append(snapshot)
    symbol, market = report.get("symbol"), report.get("market")
    def scoped(record: Dict[str, Any]) -> Tuple[Any, Any, Any]:
        return record.get("symbol"), record.get("market"), record.get("id")
    seen_zones = {scoped(x) for x in out["zones"]}
    out["zones"].extend({**x, "symbol": symbol, "market": market}
                        for x in report.get("zones", [])
                        if (symbol, market, x.get("id")) not in seen_zones)
    for key in ("turningPoints", "reactionAnomalies", "relationshipBreaks"):
        seen = {scoped(x) for x in out[key]}
        out[key].extend({**x, "symbol": symbol, "market": market}
                        for x in report.get(key, [])
                        if (symbol, market, x.get("id")) not in seen)
    for point in report.get("turningPoints", []):
        invalidation_key = (symbol, market, point.get("id"))
        if point.get("status") == "invalidated" and invalidation_key not in {
                (x.get("symbol"), x.get("market"), x.get("turningPointId"))
                for x in out["invalidations"]}:
            out["invalidations"].append({"turningPointId": point.get("id"),
                                         "symbol": symbol, "market": market,
                                         "invalidatedAt": point.get("effectiveFrom"),
                                         "methodVersion": METHOD_VERSION})
    out["lastUpdatedAt"] = now_iso
    return out


def state_hash(state: Dict[str, Any]) -> str:
    normalized = normalize_state(state)
    return _hash({key: normalized[key] for key in
                  ("snapshots", "zones", "turningPoints", "reactionAnomalies",
                   "relationshipBreaks", "invalidations")}, 32)


def read_back_verified(local: Dict[str, Any], remote: Dict[str, Any]) -> bool:
    return state_hash(local) == state_hash(remote)

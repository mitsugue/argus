"""ARGUS V11.5 — official macro-result parsers (pure, deterministic, fixture-tested).

The scanner owns the HTTP fetch (admin/cron only, within existing BLS/FRED budget);
this module holds the PURE parsers that turn a provider's already-parsed JSON into a
normalized result dict. Unit tests feed fixtures — never live web.

Discipline: never fabricate a metric. A missing series/value yields available=False
(or partial) with an honest limitation — NOT a guessed number. The ARGUS pre
scenario is never called "consensus"; consensus is never fabricated here either.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import date, timedelta
import math
import re
import hashlib
import json

SCHEMA_VERSION = "macro-result-v1"

# status vocabulary every adapter returns
STATUSES = ("live", "partial", "not_implemented", "unavailable", "parse_error",
            "source_unreachable")

# eventCode → provider (for the result-status endpoint + dispatch)
PROVIDER = {
    "NFP": "BLS", "CPI": "BLS", "PPI": "BLS", "JOLTS": "BLS",
    "PCE": "FRED", "GDP": "FRED", "FOMC": "FRED",
    "BOJ": "BOJ", "TREASURY_AUCTION": "TreasuryDirect", "AUCTION": "TreasuryDirect",
}

_SOURCE_URL = {
    "CPI": "https://www.bls.gov/news.release/cpi.nr0.htm",
    "PPI": "https://www.bls.gov/news.release/ppi.nr0.htm",
    "JOLTS": "https://www.bls.gov/news.release/jolts.nr0.htm",
    "PCE": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
    "GDP": "https://www.bea.gov/data/gdp/gross-domestic-product",
    "FOMC": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "BOJ": "https://www.boj.or.jp/en/mopo/mpmdeci/index.htm",
}


def _empty(status: str, limitations: List[str], source: Optional[str] = None) -> Dict[str, Any]:
    return {"available": False, "status": status, "source": source, "releasedAt": None,
            "headline": None, "metrics": {}, "limitationsJa": limitations}


# ── BLS index helpers ────────────────────────────────────────────────────────
def _bls_series(raw: Any, series_id: str) -> List[Dict[str, Any]]:
    """Return a BLS series' data rows sorted newest-first."""
    try:
        series = {s.get("seriesID"): (s.get("data") or [])
                  for s in (((raw or {}).get("Results") or {}).get("series") or [])}
        rows = series.get(series_id) or []
        return sorted(rows, key=lambda d: (str(d.get("year")), str(d.get("period"))), reverse=True)
    except Exception:
        return []


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def _monthly_values(rows):
    """Monthly observations only; annual averages and conflicting duplicates are missing."""
    values, conflicts = {}, set()
    for row in rows:
        year, period = str(row.get("year") or ""), str(row.get("period") or "")
        if not re.fullmatch(r"[0-9]{4}", year) or not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
            continue
        key, value = year + "-" + period[1:], _num(row.get("value"))
        if key in values and values[key] != value:
            conflicts.add(key)
        values[key] = value if value is not None and value > 0 else None
    for key in conflicts:
        values[key] = None
    return values


def _month_shift(month, shift):
    y, m = map(int, month.split("-"))
    y, m = divmod(y * 12 + m - 1 + shift, 12)
    return f"{y:04d}-{m + 1:02d}"


def _change(values, month, lag):
    before_month = _month_shift(month, -lag)
    current, before = values.get(month), values.get(before_month)
    value = round((current / before - 1) * 100, 2) if current and before else None
    return value, {"currentMonth": month, "currentIndex": current,
                   "comparisonMonth": before_month, "comparisonIndex": before}


def _mom_yoy(rows: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    values = _monthly_values(rows)
    if not values:
        return None, None, None
    month = max(values)
    return _change(values, month, 1)[0], _change(values, month, 12)[0], month


# ── CPI / PPI (BLS index levels) ─────────────────────────────────────────────
def parse_cpi(raw: Any, event: Dict[str, Any], now_iso: str,
              headline_series="CUSR0000SA0", core_series="CUSR0000SA0L1E") -> Dict[str, Any]:
    # BLS headline convention: SA month/month; NSA year/year. Never substitute SA YoY.
    series = {"headlineCpiMoM": (headline_series, 1, "SA", "ALL_ITEMS"),
              "coreCpiMoM": (core_series, 1, "SA", "LESS_FOOD_ENERGY"),
              "headlineCpiYoY": ("CUUR0000SA0", 12, "NSA", "ALL_ITEMS"),
              "coreCpiYoY": ("CUUR0000SA0L1E", 12, "NSA", "LESS_FOOD_ENERGY")}
    values = {key: _monthly_values(_bls_series(raw, spec[0])) for key, spec in series.items()}
    reference = event.get("referenceMonth")
    if not isinstance(reference, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", reference):
        try:
            event_date = date.fromisoformat(str(event.get("eventDate") or event.get("eventTimeUtc") or "")[:10])
            reference = (event_date.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        except ValueError:
            reference = None
    matched = reference is not None
    if not reference:
        reference = max(values["headlineCpiMoM"], default=None)
    if reference is None or not values["headlineCpiMoM"].get(reference):
        result = _empty("partial", ["今回の対象月のCPI公式系列は未取得"], "BLS")
        result.update(receivedAt=now_iso, expectedReferenceMonth=reference)
        return result
    metrics, definitions, inputs = {"referenceMonth": reference}, {}, {}
    for key, (sid, lag, adjustment, component) in series.items():
        metrics[key], inputs[key] = _change(values[key], reference, lag)
        definitions[key] = {"seriesId": sid, "component": component, "unit": "PERCENT_CHANGE",
                            "comparison": "MoM" if lag == 1 else "YoY", "seasonalAdjustment": adjustment,
                            "referenceMonth": reference, "method": "DERIVED_FROM_PUBLISHED_INDEX"}
    h_mom = metrics["headlineCpiMoM"]
    if h_mom is None:
        result = _empty("partial", ["対象月とその前月のCPI指数が揃わず前月比は未算出"], "BLS")
        result.update(receivedAt=now_iso, expectedReferenceMonth=reference)
        return result
    parts = [f"総合CPI 前月比（季節調整済み）{h_mom:+.1f}%"]
    if metrics["headlineCpiYoY"] is not None:
        parts.append(f"前年比（季節調整なし）{metrics['headlineCpiYoY']:+.1f}%")
    if metrics["coreCpiMoM"] is not None:
        parts.append(f"コア前月比（季節調整済み）{metrics['coreCpiMoM']:+.1f}%")
    missing = [k for k in series if metrics[k] is None]
    limitations = ["公式指数から算出。公表文の丸め済み変化率そのものではありません。",
                   "公表日時は系列応答から確認できず、取得日時以降のみ利用可能。"]
    if missing:
        limitations.append("不足系列の変化率は未算出。季節調整済み系列で前年比を代用しません。")
    if not matched:
        limitations.append("対象イベントの月との照合は未確認。")
    return {"available": True, "status": "partial" if missing or not matched else "live",
            "source": "BLS", "releasedAt": None, "receivedAt": now_iso,
            "availableFrom": now_iso, "referenceMatched": matched,
            "schemaVersion": "macro-cpi-result-v2", "headline": "消費者物価指数 " + " / ".join(parts),
            "metrics": metrics, "metricDefinitions": definitions, "metricInputs": inputs,
            "previousReferenceMonth": _month_shift(reference, -1),
            "previousMetrics": {key: _change(values[key], _month_shift(reference, -1), spec[1])[0]
                                for key, spec in series.items()},
            "sourceResponseSha256": hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
            "sourceUrl": _SOURCE_URL["CPI"], "limitationsJa": limitations}


def parse_ppi(raw: Any, event: Dict[str, Any], now_iso: str,
              headline_series="WPSFD4", core_series="WPSFD49104") -> Dict[str, Any]:
    head = _bls_series(raw, headline_series)
    if not head:
        return _empty("partial", ["PPI系列が空"], "BLS")
    h_mom, h_yoy, ref = _mom_yoy(head)
    core = _bls_series(raw, core_series)
    c_mom, _, _ = _mom_yoy(core)
    if h_mom is None:
        return _empty("partial", ["PPIの前月比を計算できるデータが不足"], "BLS")
    metrics = {"headlinePpiMoM": h_mom, "headlinePpiYoY": h_yoy,
               "corePpiMoM": c_mom, "referenceMonth": ref}
    head_txt = f"生産者物価指数 前月比{h_mom:+.1f}%"
    if h_yoy is not None:
        head_txt += f"・前年比{h_yoy:+.1f}%"
    return {"available": True, "status": "live" if h_yoy is not None else "partial",
            "source": "BLS", "releasedAt": now_iso, "headline": head_txt, "metrics": metrics,
            "sourceUrl": _SOURCE_URL["PPI"],
            "limitationsJa": [] if h_yoy is not None else ["前年比は未算出"]}


def parse_jolts(raw: Any, event: Dict[str, Any], now_iso: str,
                openings_series="JTS000000000000000JOL") -> Dict[str, Any]:
    rows = _bls_series(raw, openings_series)
    if not rows:
        return _empty("partial", ["JOLTS系列が空"], "BLS")
    openings = _num(rows[0].get("value"))
    if openings is None:
        return _empty("partial", ["求人件数を取得できず"], "BLS")
    ref = f"{rows[0].get('year')}-{str(rows[0].get('period') or '').replace('M', '')}"
    return {"available": True, "status": "live", "source": "BLS", "releasedAt": now_iso,
            "headline": f"求人件数 {openings:,.0f}千件", "metrics": {"jobOpeningsK": openings,
            "referenceMonth": ref}, "sourceUrl": _SOURCE_URL["JOLTS"], "limitationsJa": []}


# ── PCE / GDP (FRED) ─────────────────────────────────────────────────────────
def _fred_rows(raw: Any) -> List[Dict[str, Any]]:
    """FRED observations newest-first, missing ('.') dropped."""
    obs = [o for o in ((raw or {}).get("observations") or [])
           if o.get("value") not in (None, ".", "")]
    return sorted(obs, key=lambda o: str(o.get("date")), reverse=True)


def _fred_mom_yoy(raw: Any) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    rows = _fred_rows(raw)
    if len(rows) < 2:
        return None, None, None
    latest, prev = _num(rows[0].get("value")), _num(rows[1].get("value"))
    mom = round((latest / prev - 1) * 100, 2) if (latest and prev) else None
    yoy = None
    if len(rows) >= 13:
        yago = _num(rows[12].get("value"))
        if latest and yago:
            yoy = round((latest / yago - 1) * 100, 2)
    return mom, yoy, (rows[0].get("date") if rows else None)


def parse_pce(raw_headline: Any, raw_core: Any, event: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    h_mom, h_yoy, ref = _fred_mom_yoy(raw_headline)
    c_mom, c_yoy, _ = _fred_mom_yoy(raw_core)
    if h_mom is None:
        return _empty("partial", ["PCE系列のデータが不足"], "FRED/BEA")
    metrics = {"headlinePceMoM": h_mom, "headlinePceYoY": h_yoy,
               "corePceMoM": c_mom, "corePceYoY": c_yoy, "referenceDate": ref}
    txt = f"PCE物価指数 前月比{h_mom:+.1f}%"
    if c_mom is not None:
        txt += f"・コア前月比{c_mom:+.1f}%"
    return {"available": True, "status": "live" if h_yoy is not None else "partial",
            "source": "FRED/BEA", "releasedAt": now_iso, "headline": txt, "metrics": metrics,
            "sourceUrl": _SOURCE_URL["PCE"], "limitationsJa": [] if h_yoy is not None else ["前年比は未算出"]}


def parse_gdp(raw: Any, event: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    # A191RL1Q225SBEA is ALREADY the annualized q/q % change — take the latest value.
    rows = _fred_rows(raw)
    if not rows:
        return _empty("partial", ["GDP系列が空"], "FRED/BEA")
    val = _num(rows[0].get("value"))
    if val is None:
        return _empty("partial", ["実質GDP成長率を取得できず"], "FRED/BEA")
    return {"available": True, "status": "live", "source": "FRED/BEA", "releasedAt": now_iso,
            "headline": f"実質GDP 年率換算 前期比{val:+.1f}%",
            "metrics": {"realGdpQoQAnnualized": val, "referenceDate": rows[0].get("date")},
            "sourceUrl": _SOURCE_URL["GDP"], "limitationsJa": []}


def parse_fomc(raw_upper: Any, raw_lower: Any, event: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """Decision from the fed-funds TARGET RANGE (FRED DFEDTARU/DFEDTARL). We compare
    the latest range to the most recent DIFFERENT prior range — a clean data signal,
    no statement parsing. SEP/dot-plot is NOT fabricated when unavailable."""
    up = _fred_rows(raw_upper)
    lo = _fred_rows(raw_lower)
    if len(up) < 2 or not lo:
        return _empty("partial", ["FOMCの目標レンジ系列が不足（決定は捏造しない）"], "FRED/Fed")
    u_now, l_now = _num(up[0].get("value")), _num(lo[0].get("value"))
    # DFEDTAR* is a DAILY series that only changes on a decision day. Compare the
    # latest value to the IMMEDIATELY PRECEDING day: equal → hold (the common case),
    # different → the rate moved that day. Scanning for the "most recent different"
    # value across the whole window would wrongly read a hold as the LAST change.
    u_prev = _num(up[1].get("value"))
    decision = "unknown"
    if u_now is not None and u_prev is not None:
        decision = "hike" if u_now > u_prev else ("cut" if u_now < u_prev else "hold")
    dj = {"hike": "利上げ", "cut": "利下げ", "hold": "据え置き", "unknown": "不明"}[decision]
    head = f"FOMC 政策金利 {dj}（目標レンジ {l_now:.2f}〜{u_now:.2f}%）"
    return {"available": True, "status": "live", "source": "FRED/Fed", "releasedAt": now_iso,
            "headline": head, "metrics": {"decision": decision, "targetRangeLower": l_now,
            "targetRangeUpper": u_now, "referenceDate": up[0].get("date")},
            "sourceUrl": _SOURCE_URL["FOMC"],
            "limitationsJa": ["ドットプロット/SEPは本アダプタでは未取得（捏造しない）"]}


def boj_partial(event: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """BOJ has no reliable free numeric API for the decision; we return partial with
    the official statement URL only — never a fabricated rate/decision."""
    return {"available": False, "status": "partial", "source": "BOJ", "releasedAt": None,
            "headline": None, "metrics": {}, "sourceUrl": _SOURCE_URL["BOJ"],
            "limitationsJa": ["日銀の政策決定は信頼できる無料数値APIが無く未実装（結果は捏造しない）。公式声明URLのみ提供。"]}


def not_implemented(event_code: str, now_iso: str) -> Dict[str, Any]:
    return {"available": False, "status": "not_implemented", "source": PROVIDER.get(event_code),
            "releasedAt": None, "headline": None, "metrics": {},
            "limitationsJa": [f"{event_code}の公式結果アダプタは未実装（結果は捏造しない）"]}


def metrics_available(result: Dict[str, Any]) -> List[str]:
    """The metric keys actually present (for the result-status endpoint)."""
    return [k for k, v in (result.get("metrics") or {}).items()
            if v is not None and not str(k).startswith("reference")]

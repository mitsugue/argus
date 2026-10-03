"""Measured reaction to a scheduled release, from a pre-release baseline.

Owner finding 2026-10-03 (US jobs report, 2026-10-02 21:30 JST): ARGUS wrote
"US10Y +10bp" because its baseline was the first observation AFTER the release
and the yield came from a different provider than the "after" value. The
reading investors actually made ("a weak report takes an additional hike off
the table") lives in the policy-rate future, which ARGUS did not read at all.

This module is pure. The scanner captures the baseline between fifteen and one
minutes before the release and the same symbols at +5, +30 and +60 minutes,
all from one provider, and this module turns the two value maps into moves and
one deterministic reading. The reading describes what the market did; it is
not a forecast and carries no record of its own.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Mapping, Optional

SCHEMA = "macro-release-reaction-v1"
BASELINE_FROM = timedelta(minutes=15)
BASELINE_UNTIL = timedelta(minutes=1)
WINDOWS = (("+5m", timedelta(minutes=5)), ("+30m", timedelta(minutes=30)), ("+60m", timedelta(minutes=60)))
WINDOW_GRACE = timedelta(minutes=4)      # a window is still captured this long after its minute
PROVIDER = "Yahoo Finance (delayed)"

# One provider for every symbol so before and after are comparable.
SYMBOLS: Dict[str, Dict[str, str]] = {
    "ZQ=F": {"key": "ffFutures", "labelJa": "政策金利の予想(FF金利先物)", "kind": "rate_price"},
    "ZT=F": {"key": "us2yFutures", "labelJa": "米2年債先物", "kind": "bond_price"},
    "ZN=F": {"key": "us10yFutures", "labelJa": "米10年債先物", "kind": "bond_price"},
    "NQ=F": {"key": "nasdaqFutures", "labelJa": "ナスダック先物", "kind": "equity"},
    "ES=F": {"key": "spFutures", "labelJa": "S&P500先物", "kind": "equity"},
    "NKD=F": {"key": "nikkeiFutures", "labelJa": "日経平均先物(CME)", "kind": "equity"},
    "JPY=X": {"key": "usdJpy", "labelJa": "ドル円", "kind": "fx"},
    "^VIX": {"key": "vix", "labelJa": "VIX", "kind": "vix"},
}


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _instant(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_quote(payload: Any, *, received_epoch: float) -> Optional[Dict[str, Any]]:
    """{price, tradedAt, receivedAt} from one Yahoo chart response; None when unusable."""
    try:
        meta = (((payload or {}).get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
    except (AttributeError, IndexError, TypeError):
        return None
    price = _finite(meta.get("regularMarketPrice"))
    traded = meta.get("regularMarketTime")
    if price is None or price <= 0 or isinstance(traded, bool) or not isinstance(traded, (int, float)) or traded <= 0:
        return None
    return {"price": price, "tradedAt": _iso(datetime.fromtimestamp(float(traded), timezone.utc)),
            "receivedAt": _iso(datetime.fromtimestamp(received_epoch, timezone.utc))}


def capture(get: Callable[..., Any], *, received_epoch: float, symbols: Mapping[str, Mapping[str, str]] = SYMBOLS) -> Dict[str, Any]:
    """Read every symbol once from the one provider; failures are listed, never invented."""
    values: Dict[str, Dict[str, Any]] = {}
    missing = []
    for symbol in symbols:
        try:
            response = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                           params={"interval": "1m", "range": "1d"},
                           headers={"User-Agent": "Mozilla/5.0 (argus)"}, timeout=8)
            quote = parse_quote(response.json(), received_epoch=received_epoch) \
                if getattr(response, "status_code", 200) == 200 else None
        except Exception:
            quote = None
        if quote is None:
            missing.append(symbol)
        else:
            values[symbol] = quote
    return {"capturedAt": _iso(datetime.fromtimestamp(received_epoch, timezone.utc)),
            "source": PROVIDER, "values": values, "missing": missing}


def baseline_due(event_time: datetime, now: datetime) -> bool:
    """Inside the pre-release window: the last capture before the release wins."""
    return event_time - BASELINE_FROM <= now < event_time - BASELINE_UNTIL


def window_due(event_time: datetime, now: datetime, captured: Mapping[str, Any]) -> Optional[str]:
    """The first post-release window whose minute has passed and is not yet captured."""
    for name, offset in WINDOWS:
        if name in captured:
            continue
        at = event_time + offset
        if at <= now <= at + WINDOW_GRACE:
            return name
    return None


def _pct(before: Optional[float], after: Optional[float]) -> Optional[float]:
    if before is None or after is None or before == 0:
        return None
    return round((after / before - 1) * 100, 2)


def moves(before: Mapping[str, Any], after: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    """Per-symbol moves between two captures. FF futures become a policy-rate move in bp."""
    out: Dict[str, Optional[float]] = {}
    bv, av = before.get("values") or {}, after.get("values") or {}
    for symbol, spec in SYMBOLS.items():
        b = _finite((bv.get(symbol) or {}).get("price")); a = _finite((av.get(symbol) or {}).get("price"))
        if spec["kind"] == "rate_price":
            # Price = 100 - implied rate: a higher price means a lower expected rate.
            out["ffImpliedRateMoveBp"] = None if b is None or a is None else round((b - a) * 100, 1)
            out["ffImpliedRateBeforePct"] = None if b is None else round(100 - b, 3)
            out["ffImpliedRateAfterPct"] = None if a is None else round(100 - a, 3)
        else:
            out[spec["key"] + "MovePct"] = _pct(b, a)
    return out


READINGS = {
    "RATE_RELIEF_RISK_ON": ("利上げ観測の後退を安心材料に株高", "弱い数字でも、利上げが遠のいたことの方が重く受け止められた形。"),
    "GROWTH_SCARE": ("利上げ観測は後退したが景気不安で株安", "弱い数字を景気悪化の兆しとして受け止めた形。"),
    "HAWKISH_RISK_OFF": ("利上げ観測が強まり株安", "強い数字で利上げが近づいたと受け止められた形。"),
    "HAWKISH_RISK_ON": ("利上げ観測は強まったが株高", "強い数字を景気の強さとして好感した形。"),
    "RISK_ON": ("利上げ観測は動かず株高", "政策金利の予想は変わらず、株だけが買われた形。"),
    "RISK_OFF": ("利上げ観測は動かず株安", "政策金利の予想は変わらず、株だけが売られた形。"),
    "FLAT": ("方向感なし", "政策金利の予想も株も、はっきり動いていない。"),
    "UNMEASURED": ("反応を測れていない", "基準値か発表後の値が取れていない。"),
}
POLICY_BP = 1.5
EQUITY_PCT = 0.3


def reading(move: Mapping[str, Optional[float]]) -> Dict[str, str]:
    """One deterministic description of what the market did; never a forecast."""
    policy = move.get("ffImpliedRateMoveBp")
    equity = move.get("nasdaqFuturesMovePct")
    if equity is None:
        equity = move.get("spFuturesMovePct")
    if policy is None and equity is None:
        code = "UNMEASURED"
    else:
        p = "down" if policy is not None and policy <= -POLICY_BP else "up" if policy is not None and policy >= POLICY_BP else "flat"
        e = "up" if equity is not None and equity >= EQUITY_PCT else "down" if equity is not None and equity <= -EQUITY_PCT else "flat"
        code = {("down", "up"): "RATE_RELIEF_RISK_ON", ("down", "down"): "GROWTH_SCARE",
                ("up", "down"): "HAWKISH_RISK_OFF", ("up", "up"): "HAWKISH_RISK_ON",
                ("flat", "up"): "RISK_ON", ("flat", "down"): "RISK_OFF"}.get((p, e), "FLAT")
    label, meaning = READINGS[code]
    return {"code": code, "labelJa": label, "meaningJa": meaning}


def _fmt(value: Optional[float], unit: str) -> str:
    if value is None:
        return "未取得"
    return f"{value:+.1f}{unit}" if unit == "bp" else f"{value:+.2f}{unit}"


def window_summary_ja(name: str, move: Mapping[str, Optional[float]], read: Mapping[str, str]) -> str:
    bits = []
    if move.get("ffImpliedRateMoveBp") is not None:
        bits.append(f"政策金利の予想{_fmt(move['ffImpliedRateMoveBp'], 'bp')}"
                    f"({move['ffImpliedRateBeforePct']:.3f}%→{move['ffImpliedRateAfterPct']:.3f}%)")
    for key, label in (("nasdaqFuturesMovePct", "ナスダック先物"), ("spFuturesMovePct", "S&P先物"),
                       ("nikkeiFuturesMovePct", "日経先物"), ("vixMovePct", "VIX"), ("usdJpyMovePct", "ドル円"),
                       ("us2yFuturesMovePct", "2年債先物"), ("us10yFuturesMovePct", "10年債先物")):
        if move.get(key) is not None:
            bits.append(f"{label}{_fmt(move[key], '%')}")
    return f"発表{name}(発表直前比): " + "・".join(bits) + f"。市場の読み: {read['labelJa']}。"


def build(event_id: str, event_time_utc: str, baseline: Optional[Mapping[str, Any]],
          windows: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """The stored record: baseline, every captured window with its moves and reading."""
    out: Dict[str, Any] = {"schemaVersion": SCHEMA, "eventId": event_id, "eventTimeUtc": event_time_utc,
                           "basis": "PRE_RELEASE_BASELINE", "source": PROVIDER,
                           "baseline": dict(baseline) if baseline else None, "windows": {},
                           "limitationsJa": [], "actionAuthority": False, "automaticAiCalls": 0}
    if not baseline:
        out["limitationsJa"].append("発表直前の基準値が取れていない")
    for name, _ in WINDOWS:
        after = windows.get(name)
        if not after:
            continue
        move = moves(baseline or {}, after) if baseline else {}
        read = reading(move)
        out["windows"][name] = {"observedAt": after.get("capturedAt"), "values": after.get("values"),
                                "missing": after.get("missing") or [], "moves": move, "reading": read,
                                "summaryJa": window_summary_ja(name, move, read)}
    latest = next((out["windows"][n] for n, _ in reversed(WINDOWS) if n in out["windows"]), None)
    out["latestWindow"] = next((n for n, _ in reversed(WINDOWS) if n in out["windows"]), None)
    out["readingJa"] = latest["reading"]["labelJa"] if latest else READINGS["UNMEASURED"][0]
    out["summaryJa"] = latest["summaryJa"] if latest else ""
    if baseline and baseline.get("missing"):
        out["limitationsJa"].append("基準値の未取得: " + ",".join(baseline["missing"]))
    return out


def prompt_text_ja(record: Optional[Mapping[str, Any]], *, next_fomc: Optional[str] = None) -> str:
    """What the post-release analysis is allowed to say about the reaction."""
    if not record or not record.get("windows"):
        return ""
    lines = ["実測の反応(発表直前の基準値と同じ取得元で測定。反応の数字はここにあるものだけを使い、他の数字を作らない):"]
    base = (record.get("baseline") or {}).get("values") or {}
    ff = base.get("ZQ=F")
    if ff and _finite(ff.get("price")) is not None:
        lines.append(f"発表前の織り込み: FF金利先物の示す政策金利の予想 {100 - ff['price']:.3f}%"
                     + (f"(次回FOMC {next_fomc})" if next_fomc else ""))
    for name, _ in WINDOWS:
        w = record["windows"].get(name)
        if w:
            lines.append(w["summaryJa"] + " " + w["reading"]["meaningJa"])
    lines.append("読みの判定は上の『市場の読み』を基本にし、弱い/強いという数字だけで景気の良し悪しを断定しない。")
    return "\n".join(lines)

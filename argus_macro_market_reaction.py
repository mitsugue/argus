"""ARGUS V11.5 — macro market-reaction quantification (pure, deterministic).

Computes reaction windows for a released macro event from cached before/after
market values the scanner supplies (rates, index ETFs, USDJPY, VIX, gold, BTC).
Never fetches, never calls an LLM. If a before/after pair is missing, the field is
null with an honest limitation — no fake numbers. Reaction ALONE is never a cause;
it only supports the impact comment / answer-check.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "macro-market-reaction-v1"

_ASSET_KEYS = ("us10yMoveBp", "usdJpyMovePct", "spyMovePct", "qqqMovePct",
               "iwmMovePct", "vixMovePct", "goldMovePct", "btcMovePct")


def _f(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


def _pct(before: Any, after: Any) -> Optional[float]:
    b, a = _f(before), _f(after)
    if b is None or a is None or b == 0:
        return None
    return round((a / b - 1) * 100, 2)


def _bp(before: Any, after: Any) -> Optional[float]:
    """Yield move in basis points (values are percent, e.g. 4.25 → bp = ×100)."""
    b, a = _f(before), _f(after)
    if b is None or a is None:
        return None
    return round((a - b) * 100, 1)


def _risk_tone(w: Dict[str, Any]) -> str:
    """Coarse deterministic tone from the computed moves. unknown when too sparse."""
    spy, vix = w.get("spyMovePct"), w.get("vixMovePct")
    us10y = w.get("us10yMoveBp")
    signals = 0
    risk_on = risk_off = 0
    if isinstance(spy, (int, float)):
        signals += 1
        if spy > 0.15:
            risk_on += 1
        elif spy < -0.15:
            risk_off += 1
    if isinstance(vix, (int, float)):
        signals += 1
        if vix < -1:
            risk_on += 1
        elif vix > 1:
            risk_off += 1
    if signals == 0:
        # rates-only read
        if isinstance(us10y, (int, float)):
            return "rates_up" if us10y > 2 else "rates_down" if us10y < -2 else "unknown"
        return "unknown"
    if risk_on > risk_off:
        return "risk_on"
    if risk_off > risk_on:
        return "risk_off"
    if isinstance(us10y, (int, float)) and abs(us10y) >= 3:
        return "rates_up" if us10y > 0 else "rates_down"
    return "mixed"


def build_window(window: str, before: Dict[str, Any], after: Dict[str, Any],
                 now_iso: str) -> Dict[str, Any]:
    """before/after are {us10y, usdJpy, spy, qqq, iwm, vix, gold, btc} value maps."""
    w: Dict[str, Any] = {"window": window, "observedAt": now_iso}
    w["us10yMoveBp"] = _bp(before.get("us10y"), after.get("us10y"))
    w["usdJpyMovePct"] = _pct(before.get("usdJpy"), after.get("usdJpy"))
    w["spyMovePct"] = _pct(before.get("spy"), after.get("spy"))
    w["qqqMovePct"] = _pct(before.get("qqq"), after.get("qqq"))
    w["iwmMovePct"] = _pct(before.get("iwm"), after.get("iwm"))
    w["vixMovePct"] = _pct(before.get("vix"), after.get("vix"))
    w["goldMovePct"] = _pct(before.get("gold"), after.get("gold"))
    w["btcMovePct"] = _pct(before.get("btc"), after.get("btc"))
    have = [k for k in _ASSET_KEYS if w.get(k) is not None]
    w["marketConfirmed"] = len(have) >= 2
    w["riskTone"] = _risk_tone(w) if have else "unknown"
    lims = []
    if not have:
        lims.append("市場反応データ未取得")
    else:
        missing = [k for k in _ASSET_KEYS if w.get(k) is None]
        if missing:
            lims.append(f"一部の反応データ未取得（{len(missing)}項目）")
    w["limitationsJa"] = lims
    return w


def _summary(windows: List[Dict[str, Any]]) -> str:
    """Deterministic JA summary from the best-populated window."""
    good = [w for w in windows if any(w.get(k) is not None for k in _ASSET_KEYS)]
    if not good:
        return ""
    w = good[0]
    bits = []
    if w.get("us10yMoveBp") is not None:
        bits.append(f"米10年金利{w['us10yMoveBp']:+.0f}bp")
    if w.get("usdJpyMovePct") is not None:
        bits.append(f"ドル円{w['usdJpyMovePct']:+.1f}%")
    if w.get("spyMovePct") is not None:
        bits.append(f"SPY{w['spyMovePct']:+.1f}%")
    if w.get("qqqMovePct") is not None:
        bits.append(f"QQQ{w['qqqMovePct']:+.1f}%")
    if w.get("vixMovePct") is not None:
        bits.append(f"VIX{w['vixMovePct']:+.1f}%")
    tone = {"risk_on": "リスクオン", "risk_off": "リスクオフ", "rates_up": "金利上昇",
            "rates_down": "金利低下", "mixed": "まちまち", "unknown": "方向感不明"}.get(w.get("riskTone"), "")
    return f"{w['window']}反応: " + "・".join(bits) + (f"（{tone}）" if tone else "")


def build_reaction(*, event_id: str, event_code: str, windows_io: List[Dict[str, Any]],
                   now_iso: str) -> Dict[str, Any]:
    """windows_io: [{"window","before","after"}]. Returns the full reaction doc."""
    windows = [build_window(w["window"], w.get("before") or {}, w.get("after") or {}, now_iso)
               for w in windows_io]
    populated = [w for w in windows if any(w.get(k) is not None for k in _ASSET_KEYS)]
    conf = round(min(0.8, 0.2 * len(populated)), 2)
    lims = [] if populated else ["市場反応データ未取得（推測値は表示しない）"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "eventId": event_id, "eventCode": event_code, "asOf": now_iso,
        "windows": windows,
        "summaryJa": _summary(windows),
        "confidence": conf,
        "limitationsJa": lims,
    }


def compact_for_store(reaction: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten the best window into the macro record's `marketReaction` stub keys so
    the existing dashboard model keeps working, plus keep windows + summary."""
    windows = (reaction or {}).get("windows") or []
    best = next((w for w in windows if any(w.get(k) is not None for k in _ASSET_KEYS)),
                windows[0] if windows else {})
    return {
        "us10yMoveBp": best.get("us10yMoveBp"), "usdJpyMovePct": best.get("usdJpyMovePct"),
        "spyMovePct": best.get("spyMovePct"), "qqqMovePct": best.get("qqqMovePct"),
        "iwmMovePct": best.get("iwmMovePct"), "vixMovePct": best.get("vixMovePct"),
        "goldMovePct": best.get("goldMovePct"), "btcMovePct": best.get("btcMovePct"),
        "window": best.get("window"), "riskTone": best.get("riskTone"),
        "marketConfirmed": best.get("marketConfirmed", False),
        "summaryJa": reaction.get("summaryJa", ""),
        "windows": windows,
        "limitationsJa": reaction.get("limitationsJa", []),
    }


# ── event-type impact fallbacks (deterministic; used only when actual available) ──
def impact_fallback(event_code: str, metrics: Dict[str, Any],
                    reaction: Optional[Dict[str, Any]] = None) -> str:
    """Deterministic, metric-aware impact comment by event type. NOT a trade
    instruction, NOT consensus. Only produced when the official result is available."""
    code = (event_code or "").upper()
    m = metrics or {}
    tail = "判断は市場反応の確認待ち。"
    if reaction and not (reaction.get("summaryJa")):
        tail = "市場反応データが未取得のため、初動は要確認。"

    if code in ("CPI", "PPI", "PCE"):
        mom = next((m[k] for k in ("headlineCpiMoM", "headlinePpiMoM", "headlinePceMoM")
                    if isinstance(m.get(k), (int, float))), None)
        if isinstance(mom, (int, float)):
            if mom >= 0.4:
                return ("インフレは強め（前月比高め）で、金利上昇・ドル高方向、高PER成長株には逆風になりやすい。" + tail)
            if mom <= 0.1:
                return ("インフレは鈍化方向で、金利低下・ドル安方向、成長株には支援的になりやすい。" + tail)
            return ("インフレはおおむね想定内で、金利・ドルへの一方向の圧力は限定的。" + tail)
        return ("物価指標の結果を踏まえ、金利・ドル・株式の初動を確認する局面。" + tail)

    if code == "FOMC":
        dec = m.get("decision")
        if dec == "cut":
            return ("利下げは金利低下・株式に支援的だが、声明・ドットプロットがタカ派なら反転もあり得る。" + tail)
        if dec == "hike":
            return ("利上げは金利上昇・成長株に逆風。景気・声明のトーン次第で反応が変わる。" + tail)
        if dec == "hold":
            return ("据え置き。声明・ドットプロットのトーンが焦点（本アダプタでは未取得）。" + tail)
        return ("FOMCの結果を踏まえ、金利・株式の初動を確認する局面。" + tail)

    if code == "BOJ":
        return ("日銀の政策スタンス次第。引き締めなら円高・日本金利上昇・輸出株に逆風、緩和維持なら円安・株式支援が基本。"
                "（本アダプタは数値未取得のため公式声明を要確認）" + tail)

    if code == "GDP":
        g = m.get("realGdpQoQAnnualized")
        if isinstance(g, (int, float)):
            if g >= 2.5:
                return ("成長は強めでリスクオンだが、金利上昇圧力にも注意。" + tail)
            if g <= 0.5:
                return ("成長は弱めで景気減速懸念だが、金利は低下しやすい。" + tail)
        return ("GDPの結果を踏まえ、景気と金利の綱引きを確認する局面。" + tail)

    if code in ("JOLTS",):
        return ("労働需給の指標。求人が強ければ金利上昇方向、弱ければ利下げ期待が強まりやすい。" + tail)

    if code in ("TREASURY_AUCTION", "AUCTION"):
        return ("入札が弱ければ金利上昇・デュレーションに逆風、強ければ金利低下・リスク資産に支援的。" + tail)

    return ("公式結果を踏まえ、金利・ドル・株式の初動を確認する局面。" + tail)

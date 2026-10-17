"""ARGUS V11.3.4 — Market Confirmation v1.5 (pure, existing data only).

Quantifies whether a mover's price action is REAL and stock-specific using data
ARGUS already has: cached quotes, moomoo push history (intraday points), J-Quants
daily bars, the index proxy, and the theme-peer basket. This is NOT L2/tape/
borrow — true order-book confirmation needs future paid data (Databento is a
later PoC, not enabled). Honest nulls + limitationsJa when inputs are missing.

Discipline:
- market confirmation alone can NEVER create confirmed_cause (the ladder still
  requires an official/multi-source catalyst with timing consistency)
- a stale confirmation (computed long before "now") must not confirm
- nothing here fetches — the scanner passes cached inputs only
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "market-confirmation-v1.5"

STALE_AFTER_SEC = 45 * 60          # a confirmation older than 45min cannot confirm


def _f(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


def _epoch(iso: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def compute(mover: Dict[str, Any], inputs: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """inputs (all optional, cached-only, collected by the scanner):
    - changePct: today's move %
    - indexMovePct: JP index proxy (1306/1321) or US SPY move %
    - indexName: label for limitations
    - peerMoves: [pct, ...] theme-peer moves (excl. self)
    - todayVolume / avgVolume: today's cumulative vs ~20d average daily volume
    - pushPoints: [{ts(epoch), price, volume(cumulative)}] intraday push history
    - gapPct: open-vs-prev-close if known
    """
    chg = _f(mover.get("changePct"))
    lims: List[str] = []

    # relative to index
    idx = _f(inputs.get("indexMovePct"))
    rel = round(chg - idx, 2) if (chg is not None and idx is not None) else None
    if rel is None:
        lims.append("指数相対は未計算(指数プロキシ未取得)")

    # peer basket
    peers = [p for p in (inputs.get("peerMoves") or []) if isinstance(p, (int, float))]
    peer_avg = round(sum(peers) / len(peers), 2) if len(peers) >= 2 else None
    if peer_avg is None:
        lims.append("同業バスケットは未計算(同業の実測が2銘柄未満)")

    # volume ratio
    tv, av = _f(inputs.get("todayVolume")), _f(inputs.get("avgVolume"))
    vol_ratio = round(tv / av, 2) if (tv and av and av > 0) else None
    if vol_ratio is None:
        lims.append("出来高比は未計算(平均出来高または当日出来高が未取得)")

    # intraday windows + crude VWAP from cumulative-volume push points
    move_15m = move_1h = vwap_dist = None
    vwap_reclaim = None
    pts = [p for p in (inputs.get("pushPoints") or [])
           if isinstance(p, dict) and _f(p.get("price")) and _f(p.get("ts"))]
    if len(pts) >= 3:
        pts.sort(key=lambda p: p["ts"])
        last = pts[-1]
        for target_sec, key in ((900, "15m"), (3600, "1h")):
            ref = next((p for p in reversed(pts) if last["ts"] - p["ts"] >= target_sec), None)
            if ref and ref["price"]:
                mv = round((last["price"] / ref["price"] - 1) * 100, 2)
                if key == "15m":
                    move_15m = mv
                else:
                    move_1h = mv
        # VWAP ≈ Σ(price·Δvolume)/ΣΔvolume over the pushed points (crude — the
        # bridge pushes cumulative session volume; not tick-accurate)
        num = den = 0.0
        for a, b in zip(pts, pts[1:]):
            dv = (_f(b.get("volume")) or 0) - (_f(a.get("volume")) or 0)
            if dv > 0:
                num += b["price"] * dv
                den += dv
        if den > 0:
            vwap = num / den
            vwap_dist = round((last["price"] / vwap - 1) * 100, 2)
            vwap_reclaim = bool(last["price"] >= vwap)
        else:
            lims.append("VWAPは未計算(プッシュ履歴に出来高がなく加重できない)")
    else:
        lims.append("日中バー/VWAPは未計算(ブリッジの当日プッシュ履歴が不足)")

    window = "15m" if move_15m is not None else ("1h" if move_1h is not None else "same_day")

    # status ladder (deterministic; confirmation ≠ cause — it only says the move
    # is real, significant and index/peer-distinguishable)
    if chg is None:
        status = "missing"
        lims.append("当日変化率が未取得")
    elif abs(chg) < 2.0:
        status = "not_applicable"
    elif rel is not None and abs(rel) >= 1.5 and rel * chg > 0:
        # SAME-DIRECTION index-relative outperformance = stock-specific move.
        # Opposite sign means the move is index-driven (e.g. +2% on a +3.6% index
        # day) — that must never read as "confirmed".
        status = "confirmed"
    elif rel is not None or vol_ratio is not None or peer_avg is not None:
        status = "partial"
        if rel is not None and abs(rel) >= 1.5 and rel * chg <= 0:
            lims.append("指数相対が逆方向(指数主導の可能性)")
    else:
        status = "missing"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "stale": False,                       # re-evaluated at read time via is_stale()
        "computedAt": now_iso,
        "priceMovePct": (round(chg, 2) if chg is not None else None),
        "move15mPct": move_15m, "move1hPct": move_1h,
        "volumeRatio": vol_ratio,
        "relativeToIndexPct": rel,
        "indexName": str(inputs.get("indexName") or "")[:24] or None,
        "peerBasketMovePct": peer_avg,
        "peerCount": len(peers),
        "vwapDistancePct": vwap_dist,
        "vwapReclaim": vwap_reclaim,
        "gapPct": _f(inputs.get("gapPct")),
        "window": window,
        "limitationsJa": lims[:5],
    }


def is_stale(mc: Dict[str, Any], now_iso: str) -> bool:
    ts = _epoch((mc or {}).get("computedAt"))
    now = _epoch(now_iso)
    return bool(ts and now and (now - ts) > STALE_AFTER_SEC)


def annotate(mc: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """Read-time staleness stamp — a stale confirmation must not confirm."""
    if not isinstance(mc, dict):
        return mc
    if is_stale(mc, now_iso):
        mc["stale"] = True
        lims = list(mc.get("limitationsJa") or [])
        note = "市場確認が45分以上前の計算(確定には使わない)"
        if note not in lims:
            lims.append(note)
        mc["limitationsJa"] = lims[:6]
    return mc

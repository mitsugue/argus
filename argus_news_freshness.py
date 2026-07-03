"""ARGUS V11.5.3 — News Freshness Gate (pure, deterministic, stdlib-only).

The owner's complaint that triggered this module: a June-19 article surfaced as a
CURRENT lead for a July move. Old news must never be presented as the present-day
material. This module classifies a news timestamp's age and decides what role the
item may play:

    fresh   <= 6h    → may be a primary lead
    recent  <= 24h   → may be a candidate lead
    stale   <= 72h   → background only (過去材料寄り) — not a primary lead
    old     >  72h   → historical (過去材料) — never a current lead
    unknown_time     → cannot be a primary lead (no time = no timing integrity)

The mover-cause engine applies this to demote/exclude, and the UI shows old items
as 過去材料. Pure: caller passes now_iso; no clocks, no I/O.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# thresholds (hours)
FRESH_H = 6
RECENT_H = 24
STALE_H = 72

FRESHNESS_JA = {
    "fresh": "6時間以内", "recent": "24時間以内", "stale": "24〜72時間前",
    "old": "72時間超前(過去材料)", "unknown_time": "発表時刻不明",
}


def _epoch(v: Any, naive_utc_offset_hours: float = 0.0) -> Optional[float]:
    """Timestamp → epoch (same semantics as argus_mover_cause: naive stamps are
    UTC+offset — JP feeds pass 9)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = str(v).strip()
    if not s:
        return None
    from datetime import datetime, timezone
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass
    if dt is None:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(s)
        except Exception:
            dt = None
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s[:len(fmt) + 2], fmt)
                break
            except Exception:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() - naive_utc_offset_hours * 3600.0
    return dt.timestamp()


def age_hours(published_at: Any, now_iso: str,
              naive_utc_offset_hours: float = 0.0) -> Optional[float]:
    pub = _epoch(published_at, naive_utc_offset_hours)
    now = _epoch(now_iso)
    if pub is None or now is None:
        return None
    return max(0.0, (now - pub) / 3600.0)


def classify(published_at: Any, now_iso: str,
             naive_utc_offset_hours: float = 0.0) -> Dict[str, Any]:
    """Age → freshness class + role + primary-lead eligibility. Deterministic."""
    age = age_hours(published_at, now_iso, naive_utc_offset_hours)
    if age is None:
        return {"ageHours": None, "freshness": "unknown_time",
                "eligibleAsPrimaryLead": False, "role": "candidate",
                "staleReasonJa": "発表時刻が不明のため現在材料と断定できない。"}
    if age <= FRESH_H:
        return {"ageHours": round(age, 1), "freshness": "fresh",
                "eligibleAsPrimaryLead": True, "role": "primary_lead", "staleReasonJa": ""}
    if age <= RECENT_H:
        return {"ageHours": round(age, 1), "freshness": "recent",
                "eligibleAsPrimaryLead": True, "role": "candidate", "staleReasonJa": ""}
    if age <= STALE_H:
        return {"ageHours": round(age, 1), "freshness": "stale",
                "eligibleAsPrimaryLead": False, "role": "background",
                "staleReasonJa": f"材料が約{int(age)}時間前(24時間超)のため現在の主因にしない。"}
    days = int(age // 24)
    return {"ageHours": round(age, 1), "freshness": "old",
            "eligibleAsPrimaryLead": False, "role": "historical",
            "staleReasonJa": f"過去材料(約{days}日前)。現在の値動きの主因として扱わない。"}


def decorate_news_item(item: Dict[str, Any], now_iso: str, *,
                       time_keys=("publishedAt", "datetime", "time"),
                       naive_utc_offset_hours: float = 0.0) -> Dict[str, Any]:
    """Attach newsFreshness fields to a news dict (copy)."""
    if not isinstance(item, dict):
        return item
    ts = next((item[k] for k in time_keys if item.get(k) is not None), None)
    out = dict(item)
    out["newsFreshness"] = classify(ts, now_iso, naive_utc_offset_hours)
    return out


def is_current_material(published_at: Any, now_iso: str,
                        naive_utc_offset_hours: float = 0.0) -> bool:
    """True when the item may ground a CURRENT-move lead (fresh/recent only)."""
    return classify(published_at, now_iso, naive_utc_offset_hours)["eligibleAsPrimaryLead"]


def label_ja(freshness: str, age_h: Optional[float] = None) -> str:
    """UI chip text. old/stale → 過去材料 with age; fresh/recent → age only."""
    if freshness == "old":
        return f"過去材料({int(age_h // 24)}日前)" if isinstance(age_h, (int, float)) else "過去材料"
    if freshness == "stale":
        return f"過去材料寄り({int(age_h)}時間前)" if isinstance(age_h, (int, float)) else "過去材料寄り"
    if freshness == "unknown_time":
        return "時刻不明"
    if isinstance(age_h, (int, float)):
        return f"{int(age_h)}時間前" if age_h >= 1 else "1時間以内"
    return ""

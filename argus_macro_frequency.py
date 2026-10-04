"""Past frequencies of macro conditions, as material for the integrated
explanation (2026-10-04).

Two claims often heard about the US market were measured by ARGUS:

* US CPI above 3.5 %: over 1950-2026 month ends, a 20 % S&P 500 fall within
  twelve months followed 15.7 % of the months with CPI above 3.5 %, 23.0 %
  when CPI was also higher than three months before, against 11.8 % for all
  months. Peaks were not "all" preceded by high inflation (4 of 11 with the
  CPI published at the time).
* VIX at 25 or above: one year later the S&P 500 was higher 93.5 % of such
  days since 2009 against 87.0 % for all days, but 73.3 % against 75.2 %
  since 2000. The "since 2009" start makes it look certain; it is not.

These are past frequencies with their base rates, never probabilities and
never a direction for the market. The re-check of these figures by a second
reviewer is not finished, and the text says so. Pure: no network, no clock.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence

TABLE_VERSION = "macro-frequency-2026-10"
CPI_THRESHOLD_PCT = 3.5
CPI_PUBLICATION_LAG_DAYS = 20      # the month's CPI is known about 20 days after the month ends
VIX_THRESHOLD = 25.0
SOURCE_LABEL_JA = "ARGUSの検証(過去の頻度・第二の点検は未了)"
CPI_TABLE = {"allMonths": 11.8, "above": 15.7, "aboveAndRising": 23.0, "atOrBelow": 9.4}
VIX_TABLE = {"since2009": {"high": 93.5, "base": 87.0}, "since2000": {"high": 73.3, "base": 75.2}}


def _month_end(month: str) -> date:
    first = date.fromisoformat(month[:7] + "-01")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def cpi_state(rows: Sequence[Mapping[str, Any]], *, today: str) -> Optional[Dict[str, Any]]:
    """Latest published year-over-year CPI and whether it is above its value
    three months earlier. rows: monthly index levels {date: YYYY-MM-01, value}.
    A month counts as published CPI_PUBLICATION_LAG_DAYS after it ends."""
    levels = {str(r.get("date"))[:7]: float(r["value"]) for r in rows or ()
              if isinstance(r, Mapping) and isinstance(r.get("value"), (int, float)) and r.get("date")}
    published = sorted(m for m in levels
                       if (_month_end(m) + timedelta(days=CPI_PUBLICATION_LAG_DAYS)).isoformat() <= today)

    def yoy(month: str) -> Optional[float]:
        year_ago = f"{int(month[:4]) - 1}{month[4:7]}"
        return (levels[month] / levels[year_ago] - 1) * 100 if year_ago in levels and levels[year_ago] else None

    for month in reversed(published):
        now = yoy(month)
        if now is None:
            continue
        index = published.index(month)
        earlier = yoy(published[index - 3]) if index >= 3 else None
        return {"month": month, "yoyPct": round(now, 2),
                "yoyThreeMonthsEarlierPct": round(earlier, 2) if earlier is not None else None,
                "rising": (now > earlier) if earlier is not None else None,
                "knownFrom": (_month_end(month) + timedelta(days=CPI_PUBLICATION_LAG_DAYS)).isoformat()}
    return None


def _fact(text: str, key: str, as_of: Optional[str]) -> Dict[str, Any]:
    return {"text": text[:300], "priority": "P2", "source": "macro_frequency", "verification": "CORROBORATED",
            "provenance": {"scope": "published_metadata_snapshot", "revision": None, "sourceLabel": SOURCE_LABEL_JA,
                           "publishedAt": None, "receivedAt": as_of, "observedAt": None, "url": None,
                           "eventId": f"macro-frequency-{key}", "asOf": as_of, "sourceLabelJa": SOURCE_LABEL_JA,
                           "sourceRowSha256": hashlib.sha256(json.dumps(
                               [TABLE_VERSION, key, text], ensure_ascii=False).encode()).hexdigest(),
                           "tableVersion": TABLE_VERSION}}


def explanation_facts(cpi: Optional[Mapping[str, Any]], vix_level: Optional[float]) -> List[Dict[str, Any]]:
    facts = []
    if cpi and cpi.get("yoyPct") is not None:
        month = cpi["month"]
        label = f"{int(month[:4])}年{int(month[5:7])}月分"
        trend = ("3か月前より上昇中" if cpi.get("rising") else "3か月前より低下中" if cpi.get("rising") is False
                 else "3か月前との比較なし")
        if cpi["yoyPct"] > CPI_THRESHOLD_PCT:
            frequency = (f"この形(3.5%超かつ上昇中)の月は、1年以内にS&P500が20%下落した過去の頻度が"
                         f"{CPI_TABLE['aboveAndRising']}%" if cpi.get("rising") else
                         f"3.5%超の月全体では、1年以内にS&P500が20%下落した過去の頻度が{CPI_TABLE['above']}%")
        else:
            frequency = f"3.5%以下の月は、1年以内にS&P500が20%下落した過去の頻度が{CPI_TABLE['atOrBelow']}%"
        facts.append(_fact(
            f"米CPI(前年比)は{label}で{cpi['yoyPct']:.1f}%、{trend}。{frequency}"
            f"(全月の基準は{CPI_TABLE['allMonths']}%、1950年以降)。過去の頻度であり確率ではありません。",
            "us-cpi", cpi.get("knownFrom")))
    if isinstance(vix_level, (int, float)) and vix_level >= VIX_THRESHOLD:
        high09, base09 = VIX_TABLE["since2009"]["high"], VIX_TABLE["since2009"]["base"]
        high00, base00 = VIX_TABLE["since2000"]["high"], VIX_TABLE["since2000"]["base"]
        facts.append(_fact(
            f"VIXは{vix_level:.1f}で25以上。25以上の日にS&P500が1年後に上がっていた過去の頻度は、"
            f"2009年以降{high09}%(全日{base09}%)、2000年以降{high00}%(全日{base00}%)。"
            "期間で逆転し、日経平均には当てはまりません。過去の頻度であり確率ではありません。",
            "vix-band", None))
    return facts

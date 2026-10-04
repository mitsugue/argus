"""FUTURE MAP: a list of external views of the Nikkei's coming weeks (2026-10-04).

The research side writes one document (future_map.v1) to the existing
private store; the app validates it and shows it. It is not ARGUS's judgment:
no probability, no trading decision, BUY stays disabled. The sources are
neutral symbols and are not served. Rows whose end passed more than two
weeks ago are dropped from display. Pure: no network, no clock.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Optional

SCHEMA = "future_map.v1"
PUBLIC_SCHEMA = "argus-future-map-public-v1"
REMOTE_PATH = "market-analysis/v1/future-map/current.json"
TAGS = ("売り時", "急落", "下落", "戻り", "注意", "底", "大底", "―")
TAG_TONE = {"売り時": "red", "急落": "red", "下落": "red", "戻り": "amber", "注意": "amber",
            "底": "green", "大底": "green", "―": "grey"}
MAX_ROWS = 40
MAX_TEXT = 40
KEEP_PAST_DAYS = 14


class FutureMapError(ValueError):
    pass


def _day(value: Any, field: str) -> str:
    text = str(value or "")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise FutureMapError(f"{field}_date_invalid") from None
    return text


def _text(value: Any, field: str, *, required: bool = False) -> Optional[str]:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise FutureMapError(f"{field}_text_invalid")
    return value.strip()


def validate(doc: Mapping[str, Any]) -> Dict[str, Any]:
    """The public form of a future_map.v1 document (sources removed), or FutureMapError."""
    if not isinstance(doc, Mapping) or doc.get("schema") != SCHEMA:
        raise FutureMapError("schema_invalid")
    rows = doc.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise FutureMapError("rows_invalid")
    status = doc.get("status") or {}
    out_rows, seen = [], set()
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), str) or row["id"] in seen:
            raise FutureMapError("row_id_invalid")
        seen.add(row["id"])
        tag = row.get("tag")
        if tag not in TAGS:
            raise FutureMapError("tag_invalid")
        start, end = _day(row.get("start"), "start"), _day(row.get("end"), "end")
        if end < start:
            raise FutureMapError("period_invalid")
        level = row.get("level")
        if level is not None:
            if not isinstance(level, Mapping) or not all(isinstance(level.get(k), (int, float)) and level.get(k) > 0
                                                         for k in ("low", "high")) or level["low"] > level["high"]:
                raise FutureMapError("level_invalid")
            level = {"low": float(level["low"]), "high": float(level["high"])}
        agree = row.get("agree")
        if isinstance(agree, bool) or not isinstance(agree, int) or not 0 <= agree <= 9:
            raise FutureMapError("agree_invalid")
        result = row.get("result")
        if result not in (None, "reached", "missed"):
            raise FutureMapError("result_invalid")
        out_rows.append({
            "id": row["id"], "periodLabel": _text(row.get("periodLabel"), "periodLabel", required=True),
            "start": start, "end": end, "view": _text(row.get("view"), "view", required=True),
            "reason": _text(row.get("reason"), "reason"), "alt": _text(row.get("alt"), "alt"),
            "level": level, "tag": tag, "tone": TAG_TONE[tag], "agree": agree,
            "emphasis": bool(row.get("emphasis")), "changed": row.get("changed") is not None,
            "result": result})
    next_alert, next_bottom = status.get("nextAlert") or {}, status.get("nextBottom") or {}
    record = doc.get("record") or {}
    scored, reached = record.get("scored", 0), record.get("reached", 0)
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (scored, reached)) or reached > scored:
        raise FutureMapError("record_invalid")
    return {
        "schemaVersion": PUBLIC_SCHEMA, "updatedAt": str(doc.get("updatedAt") or "")[:40],
        "status": {
            "position": _text(status.get("position"), "position", required=True),
            "nextAlert": {"date": _day(next_alert.get("date"), "nextAlert"),
                          "label": _text(next_alert.get("label"), "nextAlertLabel", required=True)},
            "nextBottom": {"date": _day(next_bottom.get("date"), "nextBottom"),
                           "label": _text(next_bottom.get("label"), "nextBottomLabel", required=True)}},
        "rows": sorted(out_rows, key=lambda r: (r["start"], r["end"])),
        "record": {"scored": scored, "reached": reached},
        "externalViewsOnly": True, "argusValidated": False, "actionAuthority": False}


def for_display(public: Mapping[str, Any], today: str) -> Dict[str, Any]:
    """Rows still to show on `today`, with the current row marked."""
    cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_PAST_DAYS)).isoformat()
    rows = [dict(r) for r in public.get("rows") or [] if r["end"] >= cutoff]
    current = next((r for r in rows if r["start"] <= today <= r["end"]), None) \
        or next((r for r in rows if r["start"] > today), None)
    for row in rows:
        row["isNow"] = current is not None and row["id"] == current["id"]
        row["past"] = row["end"] < today
    return {**public, "rows": rows, "today": today}

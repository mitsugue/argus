"""Future lines: weekly pre-recorded paths of the Nikkei and their scores (2026-10-19).

The research side records, every week before the outcome, the path drawn in a
video commentary, two mechanical paths (a reference-year calendar with integer
PER levels, and recent swing intervals with the same levels) and one public
wave-count view (direction, target, invalidation). It scores all of them with
one fixed rule and writes one document (future_lines.v1) to the existing
private store. The app validates it and shows it. Not ARGUS's judgment: no
probability, no trading decision. The document carries no free text, so no
source name can enter it. Pure: no network, no clock.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, Mapping, Optional

SCHEMA = "future_lines.v1"
PUBLIC_SCHEMA = "argus-future-lines-public-v1"
REMOTE_PATH = "market-analysis/v1/future-lines/current.json"
LINE_IDS = ("commentator", "machine", "machine2")
MEASURES = ("strict", "standard", "loose", "timing")
REACH = ("reach", "stop", "expire", "pending", "n/a")
WAVE_RESULTS = ("reach", "stop", "expire", "pending")
MAX_POINTS = 8
MAX_HISTORY = 12


class FutureLinesError(ValueError):
    pass


def _day(value: Any, field: str) -> str:
    text = str(value or "")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise FutureLinesError(f"{field}_date_invalid") from None
    return text


def _instant(value: Any, field: str) -> str:
    text = str(value or "")
    if not (19 <= len(text) <= 32) or text[4] != "-" or "T" not in text:
        raise FutureLinesError(f"{field}_time_invalid")
    _day(text[:10], field)
    return text


def _price(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 1000 <= value <= 1_000_000:
        raise FutureLinesError(f"{field}_price_invalid")
    return round(float(value), 1)


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000:
        raise FutureLinesError(f"{field}_count_invalid")
    return value


def _line(row: Any, field: str) -> Dict[str, Any]:
    if not isinstance(row, Mapping):
        raise FutureLinesError(f"{field}_invalid")
    points = row.get("points")
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        raise FutureLinesError(f"{field}_points_invalid")
    rec = _day(row.get("rec"), f"{field}_rec")
    out = []
    for i, p in enumerate(points):
        if not isinstance(p, Mapping) or p.get("kind") not in ("H", "L"):
            raise FutureLinesError(f"{field}_point_kind_invalid")
        day = _day(p.get("date"), f"{field}_point")
        if day <= rec or (out and day <= out[-1]["date"]):
            raise FutureLinesError(f"{field}_point_order_invalid")
        out.append({"kind": p["kind"], "date": day, "price": _price(p.get("price"), f"{field}_point")})
    eps = row.get("eps")
    if eps is not None and (isinstance(eps, bool) or not isinstance(eps, (int, float)) or not math.isfinite(eps) or not 100 <= eps <= 100_000):
        raise FutureLinesError(f"{field}_eps_invalid")
    return {"rec": rec, "recordedAt": _instant(row.get("recordedAt"), f"{field}_recorded"),
            "eps": None if eps is None else round(float(eps), 3), "points": out}


def _record(row: Any, field: str) -> Dict[str, Any]:
    if not isinstance(row, Mapping):
        raise FutureLinesError(f"{field}_record_invalid")
    out: Dict[str, Any] = {"records": _count(row.get("records", 0), f"{field}_records")}
    for m in MEASURES:
        v = row.get(m)
        if v is None:
            out[m] = None
            continue
        if not isinstance(v, Mapping):
            raise FutureLinesError(f"{field}_{m}_invalid")
        hit, n, pending = (_count(v.get(k), f"{field}_{m}") for k in ("hit", "n", "pending"))
        if hit > n:
            raise FutureLinesError(f"{field}_{m}_hit_invalid")
        rm = v.get("randomMean")
        if rm is not None and (isinstance(rm, bool) or not isinstance(rm, (int, float)) or not 0 <= rm <= n):
            raise FutureLinesError(f"{field}_{m}_random_invalid")
        out[m] = {"hit": hit, "n": n, "pending": pending, "randomMean": None if rm is None else round(float(rm), 2)}
    reach = row.get("reach") or {}
    if not isinstance(reach, Mapping):
        raise FutureLinesError(f"{field}_reach_invalid")
    out["reach"] = {k: _count(reach.get(k, 0), f"{field}_reach") for k in REACH}
    return out


def validate(doc: Mapping[str, Any]) -> Dict[str, Any]:
    """The public form of a future_lines.v1 document, or FutureLinesError."""
    if not isinstance(doc, Mapping) or doc.get("schema") != SCHEMA:
        raise FutureLinesError("schema_invalid")
    allowed = {"schema", "updatedAt", "dataEnd", "lines", "history", "wave", "record", "retroRecord"}
    if set(doc) - allowed:
        raise FutureLinesError("unexpected_field")
    lines = doc.get("lines") or {}
    if not isinstance(lines, Mapping) or set(lines) - set(LINE_IDS):
        raise FutureLinesError("lines_invalid")
    out_lines = {k: (_line(v, k) if v is not None else None) for k, v in lines.items()}
    history = doc.get("history") or {}
    if not isinstance(history, Mapping) or set(history) - set(LINE_IDS):
        raise FutureLinesError("history_invalid")
    out_history = {}
    for k, rows in history.items():
        if not isinstance(rows, list) or len(rows) > MAX_HISTORY:
            raise FutureLinesError("history_rows_invalid")
        out_history[k] = [_line(r, f"history_{k}") for r in rows]
    wave = doc.get("wave")
    out_wave: Optional[Dict[str, Any]] = None
    if wave is not None:
        if not isinstance(wave, Mapping) or wave.get("dir") not in ("up", "down") or wave.get("result") not in WAVE_RESULTS:
            raise FutureLinesError("wave_invalid")
        target, stop = _price(wave.get("target"), "wave_target"), _price(wave.get("stop"), "wave_stop")
        if (target <= stop) if wave["dir"] == "up" else (target >= stop):
            raise FutureLinesError("wave_levels_invalid")
        out_wave = {"pub": _day(wave.get("pub"), "wave_pub"), "recordedAt": _instant(wave.get("recordedAt"), "wave_recorded"),
                    "dir": wave["dir"], "target": target, "stop": stop, "result": wave["result"],
                    "settledBeforeRecord": bool(wave.get("settledBeforeRecord"))}
    record = doc.get("record") or {}
    if not isinstance(record, Mapping) or set(record) - set(LINE_IDS + ("wave",)):
        raise FutureLinesError("record_invalid")
    out_record: Dict[str, Any] = {}
    for k, v in record.items():
        if k == "wave":
            if not isinstance(v, Mapping):
                raise FutureLinesError("wave_record_invalid")
            n = _count(v.get("n"), "wave_n")
            hit = _count(v.get("reach"), "wave_reach")
            if hit > n:
                raise FutureLinesError("wave_record_invalid")
            out_record[k] = {"records": _count(v.get("records", 0), "wave_records"), "reach": hit, "n": n,
                             "pending": _count(v.get("pending", 0), "wave_pending")}
        else:
            out_record[k] = _record(v, k)
    retro = doc.get("retroRecord") or {}
    if not isinstance(retro, Mapping) or set(retro) - set(LINE_IDS):
        raise FutureLinesError("retro_invalid")
    return {"schemaVersion": PUBLIC_SCHEMA, "updatedAt": _instant(doc.get("updatedAt"), "updated"),
            "dataEnd": _day(doc.get("dataEnd"), "data_end"), "lines": out_lines, "history": out_history,
            "wave": out_wave, "record": out_record, "retroRecord": {k: _record(v, f"retro_{k}") for k, v in retro.items()},
            "argusValidated": False, "actionAuthority": False, "predictiveProbabilities": None}

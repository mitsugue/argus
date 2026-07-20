# -*- coding: utf-8 -*-
"""Deterministic helpers for the final v12 foundation data jobs.

The module is deliberately provider-agnostic.  It classifies historical
J-Quants master/bars responses, creates append-only Market Ledger candidates,
and maintains resumable/cancellable job metadata.  Network I/O and secrets stay
inside the admin-gated runtime adapter in ``scanner.py``.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_VERSION = "argus-foundation-jobs-v1"
METHOD_VERSION = "jquants-breadth-adjusted-close-v1"
JOB_TYPES = {
    "JQUANTS_BREADTH_BACKFILL",
    "JQUANTS_BREADTH_INCREMENTAL",
    "JQUANTS_REQUEST_MATRIX",
    "GEMINI_PREFLIGHT",
    "RESEARCH_BENCHMARK",
    "JOURNAL_REVERIFY",
}
TERMINAL_STATES = {"completed", "failed", "cancelled"}
UNIVERSES = {
    "tse_prime_domestic_common": {
        "name": "TSE Prime Domestic Common Stocks",
        "segments": {"prime"},
    },
    "tse_all_domestic_common": {
        "name": "TSE All Domestic Common Stocks",
        "segments": {"prime", "standard", "growth"},
    },
}


_JQUANTS_DATE_KEYS = {"date", "from", "to"}


def normalize_jquants_query(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the official V2 query form without mutating the caller.

    J-Quants' official examples use compact ``YYYYMMDD`` values.  The official
    client accepts both representations, but the production V2 endpoint has
    rejected the hyphenated historical full-market request.  Normalizing at
    the transport boundary keeps all callers and checkpoints human-readable.
    """
    out: Dict[str, Any] = {}
    for key, value in dict(params or {}).items():
        if key in _JQUANTS_DATE_KEYS and value is not None:
            text = str(value)
            if not (len(text) == 8 and text.isdigit()):
                try:
                    text = datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y%m%d")
                except ValueError as exc:
                    raise ValueError(f"invalid_jquants_{key}") from exc
            out[key] = text
        else:
            out[key] = value
    return out


def classify_gemini_preflight(metadata: Dict[str, Any], *,
                              expected_text: str = "ARGUS_GEMINI_OK") -> str:
    """Classify a secret-free Gemini response without relying on ``.text``."""
    if metadata.get("errorClass"):
        error = str(metadata["errorClass"]).lower()
        if any(word in error for word in ("timeout", "server", "unavailable", "429")):
            return "transient_provider_error"
        return "malformed_request"
    prompt = metadata.get("promptFeedback") or {}
    if prompt.get("blockReason"):
        return "safety_block"
    candidates = metadata.get("candidates") or []
    if not candidates:
        return "no_candidate"
    reasons = {str(x.get("finishReason") or "").upper() for x in candidates}
    if reasons & {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
        return "safety_block"
    if "RECITATION" in reasons:
        return "recitation"
    if reasons & {"MAX_TOKENS", "MAX_OUTPUT_TOKENS"}:
        return "max_tokens"
    if not metadata.get("textPartExists"):
        return "no_text_part"
    if metadata.get("matchedExpectedText") is True:
        return "success"
    if metadata.get("textPartExists") and not metadata.get("nonEmptyTextPartExists"):
        return "preview_empty_output"
    return "parsing_error"


def select_latest_stable_gemini_pro(models: Iterable[Dict[str, Any]]) -> Optional[str]:
    """Select the highest explicit stable Pro model supporting generateContent."""
    ranked = []
    for row in models:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").removeprefix("models/")
        low = name.lower()
        actions = {str(x).lower() for x in (row.get("supportedActions") or [])}
        if ("gemini" not in low or "pro" not in low
                or any(tag in low for tag in ("preview", "experimental", "-exp", "latest"))
                or "generatecontent" not in actions):
            continue
        numbers = tuple(int(x) for x in re.findall(r"\d+", low)[:3])
        ranked.append((numbers, name))
    return max(ranked, default=((), None))[1]


def _digest(value: Any, length: int = 20) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:length]


def empty_state() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "jobs": [], "activeJobId": None,
            "lastUpdatedAt": None}


def normalize_state(value: Any) -> Dict[str, Any]:
    src = value if isinstance(value, dict) else {}
    out = empty_state()
    out["jobs"] = [deepcopy(x) for x in (src.get("jobs") or [])
                   if isinstance(x, dict) and x.get("jobId")][-30:]
    active = src.get("activeJobId")
    out["activeJobId"] = str(active) if active else None
    out["lastUpdatedAt"] = src.get("lastUpdatedAt")
    return out


def start_job(state: Dict[str, Any], *, job_type: str, now_iso: str,
              parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    st = normalize_state(state)
    if job_type not in JOB_TYPES:
        raise ValueError("unknown_job_type")
    active = next((x for x in st["jobs"] if x.get("jobId") == st["activeJobId"]), None)
    if active and active.get("status") not in TERMINAL_STATES:
        if active.get("jobType") == job_type:
            return {"created": False, "job": active, "state": st}
        raise ValueError("another_job_active")
    params = deepcopy(parameters or {})
    job_id = "fj-" + _digest({"jobType": job_type, "startedAt": now_iso,
                              "parameters": params})
    job = {
        "schemaVersion": SCHEMA_VERSION,
        "jobId": job_id,
        "jobType": job_type,
        "status": "queued",
        "startedAt": now_iso,
        "updatedAt": now_iso,
        "completedAt": None,
        "parameters": params,
        "progress": {"completedUnits": 0, "totalUnits": None, "percent": 0.0},
        "checkpoint": {},
        "result": None,
        "errorClass": None,
        "cancelRequested": False,
        "attempt": 1,
    }
    st["jobs"].append(job)
    st["activeJobId"] = job_id
    st["lastUpdatedAt"] = now_iso
    return {"created": True, "job": job, "state": st}


def update_job(state: Dict[str, Any], job_id: str, *, now_iso: str,
               status: Optional[str] = None, progress: Optional[Dict[str, Any]] = None,
               checkpoint: Optional[Dict[str, Any]] = None,
               result: Optional[Dict[str, Any]] = None,
               error_class: Optional[str] = None) -> Dict[str, Any]:
    st = normalize_state(state)
    job = next((x for x in st["jobs"] if x.get("jobId") == job_id), None)
    if not job:
        raise ValueError("unknown_job")
    if status:
        if status not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise ValueError("invalid_job_status")
        job["status"] = status
    if isinstance(progress, dict):
        job["progress"].update(deepcopy(progress))
    if isinstance(checkpoint, dict):
        job["checkpoint"].update(deepcopy(checkpoint))
    if result is not None:
        job["result"] = deepcopy(result)
    job["errorClass"] = str(error_class)[:100] if error_class else None
    job["updatedAt"] = now_iso
    if job["status"] in TERMINAL_STATES:
        job["completedAt"] = now_iso
        if st.get("activeJobId") == job_id:
            st["activeJobId"] = None
    st["lastUpdatedAt"] = now_iso
    return st


def request_cancel(state: Dict[str, Any], job_id: str, *, now_iso: str) -> Dict[str, Any]:
    st = normalize_state(state)
    job = next((x for x in st["jobs"] if x.get("jobId") == job_id), None)
    if not job:
        raise ValueError("unknown_job")
    if job.get("status") not in TERMINAL_STATES:
        job["cancelRequested"] = True
        job["updatedAt"] = now_iso
    st["lastUpdatedAt"] = now_iso
    return st


def public_status(state: Dict[str, Any], job_id: Optional[str] = None) -> Dict[str, Any]:
    st = normalize_state(state)
    jobs = st["jobs"]
    if job_id:
        jobs = [x for x in jobs if x.get("jobId") == job_id]
    safe = []
    for row in jobs[-20:]:
        safe.append({k: deepcopy(row.get(k)) for k in (
            "jobId", "jobType", "status", "startedAt", "updatedAt", "completedAt",
            "parameters", "progress", "checkpoint", "result", "errorClass",
            "cancelRequested", "attempt")})
    return {"schemaVersion": SCHEMA_VERSION, "activeJobId": st.get("activeJobId"),
            "jobs": safe, "lastUpdatedAt": st.get("lastUpdatedAt")}


def trading_dates(calendar_rows: Iterable[Dict[str, Any]], *, start: str,
                  end: str) -> List[str]:
    """Return provider-confirmed trading dates without guessing field spelling."""
    out = []
    for row in calendar_rows:
        if not isinstance(row, dict):
            continue
        date = str(row.get("Date") or row.get("date") or "")[:10]
        flag = row.get("HolDiv", row.get("HolidayDivision"))
        # J-Quants: HolDiv=1 is a business day.  Accept explicit booleans too.
        is_open = (str(flag) == "1" or row.get("IsTradingDay") is True
                   or row.get("isTradingDay") is True)
        if len(date) == 10 and start <= date <= end and is_open:
            out.append(date)
    return sorted(set(out))


def weekday_candidates(start: str, end: str) -> List[str]:
    """Candidate JP cash dates; actual trading is proven by non-empty daily bars."""
    cursor = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out = []
    while cursor <= last:
        if cursor.weekday() < 5:
            out.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return out


def _segment(row: Dict[str, Any]) -> Optional[str]:
    market = " ".join(str(row.get(k) or "") for k in
                      ("Mkt", "MktNm", "MarketCode", "MarketCodeName"))
    low = market.lower()
    if "prime" in low or "プライム" in market:
        return "prime"
    if "standard" in low or "スタンダード" in market:
        return "standard"
    if "growth" in low or "グロース" in market:
        return "growth"
    return None


def eligible_issue(row: Dict[str, Any], universe_id: str) -> bool:
    spec = UNIVERSES.get(universe_id)
    if not spec or not isinstance(row, dict):
        return False
    seg = _segment(row)
    if seg not in spec["segments"]:
        return False
    text = " ".join(str(row.get(k) or "") for k in (
        "CoName", "CoNameEn", "MktNm", "SecType", "SecurityType", "IssueType"))
    low = text.lower()
    exclusions = ("etf", "etn", "reit", "投資法人", "投資信託", "ファンド",
                  "preferred", "優先", "warrant", "新株予約権", "foreign", "外国",
                  "tokyo pro", "プロマーケット")
    if any(word in low for word in exclusions):
        return False
    code = str(row.get("Code") or row.get("code") or "")
    return len(code) >= 4 and code[0].isdigit()


def _adjusted_close(row: Dict[str, Any]) -> Optional[float]:
    value = row.get("AdjC", row.get("AdjustmentClose"))
    if value is None:
        return None
    try:
        number = float(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def calculate_daily(*, date: str, master_rows: Iterable[Dict[str, Any]],
                    bar_rows: Iterable[Dict[str, Any]],
                    previous_adjusted_closes: Dict[str, float]) -> Dict[str, Any]:
    master = {str(x.get("Code") or x.get("code") or ""): x
              for x in master_rows if isinstance(x, dict)}
    bars = {str(x.get("Code") or x.get("code") or ""): x
            for x in bar_rows if isinstance(x, dict)
            and str(x.get("Date") or x.get("date") or "")[:10] == date}
    results: Dict[str, Any] = {}
    # The comparison base for the next session is *this* session only.  Carrying
    # an older close across a missing/no-trade row would silently turn a two-day
    # move into a one-day advance/decline and could also bridge a delist/relist.
    next_closes: Dict[str, float] = {}
    for code, row in bars.items():
        close = _adjusted_close(row)
        if close is not None:
            next_closes[code] = close
    for universe_id, spec in UNIVERSES.items():
        codes = {code for code, row in master.items()
                 if eligible_issue(row, universe_id)}
        counts = {"advancers": 0, "decliners": 0, "unchanged": 0,
                  "unavailable": 0}
        source_ids = []
        for code in sorted(codes):
            current = _adjusted_close(bars.get(code, {}))
            previous = previous_adjusted_closes.get(code)
            if current is None or previous is None or previous <= 0:
                counts["unavailable"] += 1
                continue
            if current > previous:
                counts["advancers"] += 1
            elif current < previous:
                counts["decliners"] += 1
            else:
                counts["unchanged"] += 1
            source_ids.append(f"jq:{date}:{code}")
        eligible = counts["advancers"] + counts["decliners"] + counts["unchanged"]
        issue_count = len(codes)
        coverage = round(eligible / issue_count, 6) if issue_count else 0.0
        results[universe_id] = {
            "universeId": universe_id,
            "universeName": spec["name"],
            "methodVersion": METHOD_VERSION,
            "effectiveDate": date,
            "source": "J-Quants V2 equities/master + equities/bars/daily",
            "issueCount": issue_count,
            "eligibleCount": eligible,
            "coverageRatio": coverage,
            "counts": counts,
            "sourceObservationIds": source_ids,
            "inclusionRules": ["historical listed issue master", *sorted(spec["segments"]),
                               "domestic common stock"],
            "exclusionRules": ["ETF/ETN/REIT/fund/preferred/foreign/warrant",
                               "not listed on date", "missing adjusted close"],
        }
    return {"date": date, "universes": results,
            "nextAdjustedCloses": next_closes}


def ledger_candidates(daily: Dict[str, Any], *, calculated_at: str,
                      published_hour_jst: int = 17) -> List[Dict[str, Any]]:
    date = str(daily.get("date") or "")[:10]
    available = f"{date}T{published_hour_jst:02d}:00:00+09:00"
    out: List[Dict[str, Any]] = []
    for universe_id, row in (daily.get("universes") or {}).items():
        short = "prime" if universe_id == "tse_prime_domestic_common" else "all"
        meta = {k: deepcopy(row.get(k)) for k in (
            "universeId", "universeName", "methodVersion", "effectiveDate", "source",
            "issueCount", "eligibleCount", "coverageRatio", "inclusionRules",
            "exclusionRules")}
        # Raw J-Quants rows are never persisted; only aggregate counts and hashes.
        ids = row.get("sourceObservationIds") or []
        meta["sourceObservationCount"] = len(ids)
        meta["sourceObservationHash"] = _digest(ids, 32)
        meta["calculatedAt"] = calculated_at
        meta["availabilityPolicy"] = "same_day_17:00_JST_after_provider_16:30_update"
        for name in ("advancers", "decliners", "unchanged", "unavailable"):
            out.append({
                "seriesId": f"breadth.{short}.{name}",
                "periodEnd": date,
                "publishedAt": available,
                "availableFrom": available,
                "observedAt": calculated_at,
                "value": int((row.get("counts") or {}).get(name) or 0),
                "unit": "count",
                "source": "J-Quants V2 licensed aggregate",
                "sourceKind": "derived",
                "status": "live",
                "metadata": meta,
            })
    return out


def ratio_rows(daily_counts: Iterable[Dict[str, Any]], window: int) -> List[Dict[str, Any]]:
    rows = sorted([x for x in daily_counts if isinstance(x, dict)],
                  key=lambda x: str(x.get("asOfDate") or ""))
    out = []
    for end in range(window, len(rows) + 1):
        sample = rows[end - window:end]
        adv = sum(int(x.get("advancers") or 0) for x in sample)
        dec = sum(int(x.get("decliners") or 0) for x in sample)
        out.append({"asOfDate": sample[-1]["asOfDate"], "window": window,
                    "advancerSum": adv, "declinerSum": dec,
                    "ratio": None if dec == 0 else round(adv / dec * 100.0, 2),
                    "sourceObservationIds": [x.get("observationId") for x in sample
                                             if x.get("observationId")],
                    "methodVersion": METHOD_VERSION,
                    "completeness": "complete" if all(
                        x.get("complete") is True for x in sample) else "partial"})
    return out


def bounded_backoff_seconds(attempt: int, retry_after: Optional[str] = None,
                            seed: str = "") -> float:
    if retry_after:
        try:
            return max(0.0, min(300.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    base = min(60.0, 2.0 ** max(0, int(attempt) - 1))
    jitter = int(_digest(seed or str(attempt), 4), 16) % 1000 / 1000.0
    return round(base + jitter, 3)


def next_day(date_text: str) -> str:
    dt = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (dt + timedelta(days=1)).strftime("%Y-%m-%d")

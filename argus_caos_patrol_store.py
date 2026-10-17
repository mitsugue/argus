"""ARGUS V11.5.5 — C.A.O.S. Patrol Ledger (pure, deterministic, stdlib-only).

The owner's requirement is not "the button works" but "C.A.O.S. keeps working".
This module is the PROOF layer: a rolling 24h ledger of patrol runs, per-symbol
sweeps, and per-source success/failure, from which patrol health (healthy /
degraded / stale / error) is derived deterministically.

Durability rule: restore must MERGE, never wipe — a dyno restart must not erase
the day's history, and an old snapshot must never clobber newer runtime state.
Everything stored is public-safe: timestamps, counts, sourceIds, symbols. No
full text, no secrets, no prompts, no provider bodies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "caos-patrol-ledger-v1"
WINDOW_H = 24

_MAX_RUNS = 400          # 96/day cron + investigate clicks — generous bound
_MAX_SWEEPS = 600
_MAX_SRC_EVENTS = 200    # per source


def _epoch(ts: Any) -> Optional[float]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def new_ledger(now_iso: str = "") -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "asOf": now_iso, "window": "24h",
            "runs": [], "sweeps": [], "sources": {}}


def _prune(ledger: Dict[str, Any], now_iso: str) -> None:
    now = _epoch(now_iso) or 0.0
    cut = now - WINDOW_H * 3600
    ledger["runs"] = [r for r in ledger.get("runs", [])
                      if (_epoch(r.get("at")) or 0) >= cut][-_MAX_RUNS:]
    ledger["sweeps"] = [s for s in ledger.get("sweeps", [])
                        if (_epoch(s.get("at")) or 0) >= cut][-_MAX_SWEEPS:]
    for sid, src in (ledger.get("sources") or {}).items():
        src["events"] = [e for e in src.get("events", [])
                         if (_epoch(e.get("at")) or 0) >= cut][-_MAX_SRC_EVENTS:]


def record_run(ledger: Dict[str, Any], *, now_iso: str, ok: bool,
               deep_sweeps: int = 0, baseline_checked: bool = False,
               fresh_items: int = 0, new_items: int = 0,
               source_success: int = 0, source_errors: int = 0,
               active_movers: int = 0, note_ja: str = "") -> Dict[str, Any]:
    ledger.setdefault("runs", []).append({
        "at": now_iso, "ok": bool(ok), "deepSweeps": int(deep_sweeps),
        "baselineChecked": bool(baseline_checked),
        "freshItems": int(fresh_items), "newItems": int(new_items),
        "sourceSuccess": int(source_success), "sourceErrors": int(source_errors),
        "activeMovers": int(active_movers), "noteJa": str(note_ja)[:160]})
    ledger["asOf"] = now_iso
    _prune(ledger, now_iso)
    return ledger


def record_sweep(ledger: Dict[str, Any], *, now_iso: str, symbol: str, market: str,
                 kind: str, status: str, fresh: int = 0) -> Dict[str, Any]:
    """kind: deep (patrol) | investigate (owner button) | baseline."""
    ledger.setdefault("sweeps", []).append({
        "at": now_iso, "symbol": str(symbol).upper()[:16],
        "market": str(market).upper()[:4], "kind": str(kind)[:16],
        "status": str(status)[:16], "fresh": int(fresh)})
    ledger["asOf"] = now_iso
    _prune(ledger, now_iso)
    return ledger


def update_source(ledger: Dict[str, Any], source_id: str, *, now_iso: str,
                  ok: bool, newest_published_at: Optional[str] = None) -> Dict[str, Any]:
    src = ledger.setdefault("sources", {}).setdefault(str(source_id), {"events": []})
    src["events"].append({"at": now_iso, "ok": bool(ok)})
    if ok:
        src["lastSuccessAt"] = now_iso
    else:
        src["lastErrorAt"] = now_iso
    if newest_published_at:
        prev = _epoch(src.get("newestPublishedAt"))
        cur = _epoch(newest_published_at)
        if cur and (prev is None or cur > prev):
            src["newestPublishedAt"] = str(newest_published_at)
    return ledger


def merge(existing: Optional[Dict[str, Any]], incoming: Optional[Dict[str, Any]],
          now_iso: str) -> Dict[str, Any]:
    """Union of both ledgers (restore MERGES — an old snapshot never wipes newer
    runtime state, and runtime never loses pre-restart history)."""
    if not incoming:
        return existing or new_ledger(now_iso)
    if not existing:
        out = dict(new_ledger(now_iso))
        out.update({k: incoming.get(k, out.get(k)) for k in ("runs", "sweeps", "sources")})
        _prune(out, now_iso)
        return out
    out = new_ledger(now_iso)
    seen = set()
    for r in (existing.get("runs") or []) + (incoming.get("runs") or []):
        k = str(r.get("at"))
        if k in seen:
            continue
        seen.add(k)
        out["runs"].append(r)
    out["runs"].sort(key=lambda r: str(r.get("at")))
    seen = set()
    for s in (existing.get("sweeps") or []) + (incoming.get("sweeps") or []):
        k = f"{s.get('at')}|{s.get('symbol')}|{s.get('kind')}"
        if k in seen:
            continue
        seen.add(k)
        out["sweeps"].append(s)
    out["sweeps"].sort(key=lambda s: str(s.get("at")))
    for src_map in (existing.get("sources") or {}, incoming.get("sources") or {}):
        for sid, src in src_map.items():
            cur = out["sources"].setdefault(sid, {"events": []})
            have = {str(e.get("at")) for e in cur["events"]}
            for e in src.get("events", []):
                if str(e.get("at")) not in have:
                    cur["events"].append(e)
            cur["events"].sort(key=lambda e: str(e.get("at")))
            for k in ("lastSuccessAt", "lastErrorAt", "newestPublishedAt"):
                a, b = _epoch(cur.get(k)), _epoch(src.get(k))
                if b and (a is None or b > a):
                    cur[k] = src[k]
    _prune(out, now_iso)
    return out


def summarize(ledger: Dict[str, Any], now_iso: str,
              old_primary_violations: int = 0) -> Dict[str, Any]:
    _prune(ledger, now_iso)
    runs = ledger.get("runs", [])
    sweeps = ledger.get("sweeps", [])
    deep = [s for s in sweeps if s.get("kind") in ("deep", "investigate")]
    return {
        "targetsPlanned": None,       # filled by the caller from the live plan
        "runs24h": len(runs),
        "successfulRuns24h": sum(1 for r in runs if r.get("ok")),
        "failedRuns24h": sum(1 for r in runs if not r.get("ok")),
        "deepSweeps24h": len(deep),
        "baselineSweeps24h": sum(1 for r in runs if r.get("baselineChecked")),
        "freshItems24h": sum(int(r.get("freshItems") or 0) for r in runs)
        + sum(int(s.get("fresh") or 0) for s in sweeps if s.get("kind") == "investigate"),
        "newItems24h": sum(int(r.get("newItems") or 0) for r in runs),
        "sourceSuccess24h": sum(int(r.get("sourceSuccess") or 0) for r in runs),
        "sourceErrors24h": sum(int(r.get("sourceErrors") or 0) for r in runs),
        "emptyDeepSweepRuns24h": sum(1 for r in runs
                                     if r.get("ok") and not r.get("deepSweeps")
                                     and int(r.get("activeMovers") or 0) > 0),
        "oldPrimaryViolations": int(old_primary_violations),
    }


def source_health(ledger: Dict[str, Any], now_iso: str) -> List[Dict[str, Any]]:
    out = []
    now = _epoch(now_iso) or 0.0
    for sid, src in sorted((ledger.get("sources") or {}).items()):
        events = src.get("events", [])
        succ = sum(1 for e in events if e.get("ok"))
        errs = len(events) - succ
        last_ok = _epoch(src.get("lastSuccessAt"))
        newest = src.get("newestPublishedAt")
        newest_ep = _epoch(newest)
        age = round((now - newest_ep) / 3600, 1) if newest_ep else None
        if last_ok is None or (now - last_ok) > 24 * 3600:
            status = "stale"                       # no success today ≠ live
        elif errs and succ == 0:
            status = "error"
        elif errs:
            status = "partial"
        else:
            status = "live"
        out.append({"sourceId": sid, "status": status,
                    "lastSuccessAt": src.get("lastSuccessAt"),
                    "lastErrorAt": src.get("lastErrorAt"),
                    "successCount24h": succ, "errorCount24h": errs,
                    "newestPublishedAt": newest, "newestAgeHours": age,
                    "limitationsJa": []})
    return out


def derive_status(*, now_iso: str, last_patrol_at: Optional[str],
                  summary: Dict[str, Any], is_weekday: bool,
                  has_runs: bool) -> (str, List[Dict[str, str]]):
    """healthy | degraded | stale | error | not_ready + alerts. Deterministic."""
    alerts: List[Dict[str, str]] = []
    if summary.get("oldPrimaryViolations"):
        alerts.append({"level": "error",
                       "messageJa": "古いニュースがcurrent leadに使われている(即修正対象)。"})
        return "error", alerts
    if not has_runs:
        return "not_ready", [{"level": "warning",
                              "messageJa": "24時間以内の巡回記録がまだない(再起動直後/初回)。"}]
    now, last = _epoch(now_iso), _epoch(last_patrol_at)
    limit_min = 30 if is_weekday else 90
    if last is None or (now - last) > limit_min * 60:
        alerts.append({"level": "warning",
                       "messageJa": f"最終巡回から{limit_min}分以上経過 — ニュース監視に遅延。"})
        return "stale", alerts
    status = "healthy"
    if summary.get("baselineSweeps24h", 0) == 0:
        alerts.append({"level": "warning",
                       "messageJa": "24時間以内にbaseline巡回の記録がない。"})
        status = "degraded"
    if summary.get("emptyDeepSweepRuns24h", 0) > 0 and summary.get("deepSweeps24h", 0) == 0:
        alerts.append({"level": "warning",
                       "messageJa": "急変銘柄が存在したのにdeep sweepが24時間実行されていない。"})
        status = "degraded"
    if summary.get("failedRuns24h", 0) > summary.get("successfulRuns24h", 0):
        alerts.append({"level": "warning", "messageJa": "巡回の失敗が成功を上回っている。"})
        status = "degraded"
    return status, alerts

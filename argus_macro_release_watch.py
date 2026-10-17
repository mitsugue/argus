"""Fetch scheduled macro results from the server itself (owner report 2026-10-02).

The US employment report was released at 21:30 JST, but the app showed no
result until the scheduled GitHub workflow ran, and GitHub delays scheduled
runs by tens of minutes. This watcher runs inside the backend: from two
minutes after a scheduled release until forty-five minutes after it, it calls
the existing deterministic result refresh at most once every three minutes.
It never invents a value; the refresh reads the official sources it already
reads.

2026-10-03: the same watcher now drives the measured reaction. Between fifteen
and one minutes before the release it captures a baseline; at +5, +30 and +60
minutes and eight hours it captures the same symbols again; once the official
result and the +5 minute window exist it asks the scanner to run the post-release analysis,
which is single-flight and reads the measured reaction instead of a baseline
taken after the release.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

FIRST_DELAY = timedelta(minutes=2)
WINDOW = timedelta(minutes=45)
INTERVAL_SECONDS = 180
POLL_SECONDS = 60

_lock = threading.Lock()
_state: dict[str, Any] = {"thread": None, "lastRefreshAt": None, "lastEventId": None,
                          "lastError": None, "refreshCount": 0,
                          "baselines": {}, "windows": {}, "posted": {}, "reactionError": None}


def _instant(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def due_event(events: Iterable[Mapping[str, Any]], now: datetime, last_refresh: Optional[datetime]) -> Optional[str]:
    """The id of a release inside its watch window when a refresh is due, else None."""
    if last_refresh is not None and (now - last_refresh).total_seconds() < INTERVAL_SECONDS:
        return None
    for event in events:
        at = _instant(event.get("eventTimeUtc"))
        if at is not None and at + FIRST_DELAY <= now <= at + WINDOW:
            return str(event.get("id") or event.get("eventId") or "")
    return None


def reaction_tick(events: Iterable[Mapping[str, Any]], now: datetime, *,
                  baseline: Optional[Callable[[Mapping[str, Any]], Any]],
                  window: Optional[Callable[[Mapping[str, Any], str], Any]],
                  post: Optional[Callable[[Mapping[str, Any], str], bool]]) -> list:
    """Baseline, post-release windows and one post-analysis request per event."""
    import argus_macro_release_reaction as reaction
    done = []
    for event in events:
        at = reaction._instant(event.get("eventTimeUtc"))
        event_id = str(event.get("id") or event.get("eventId") or "")
        if at is None or not event_id or now < at - reaction.BASELINE_FROM or now > at + reaction.WATCH_UNTIL:
            continue
        with _lock:
            captured = dict(_state["windows"].get(event_id) or {})
            posted = _state["posted"].get(event_id)
        try:
            if baseline and reaction.baseline_due(at, now):
                result = baseline(event)   # the last usable capture before release wins
                if isinstance(result, Mapping) and result.get("schemaVersion") == reaction.SCHEMA:
                    if not result.get("baselineComparisonValues"):
                        raise ValueError("release_baseline_source_time_unavailable")
                with _lock:
                    _state["baselines"][event_id] = now
                done.append((event_id, "baseline"))
            name = reaction.window_due(at, now, captured) if window else None
            if name:
                result = window(event, name)
                if isinstance(result, Mapping) and result.get("schemaVersion") == reaction.SCHEMA:
                    measured = (result.get("windows") or {}).get(name) or {}
                    if not measured.get("comparisonValues"):
                        raise ValueError("release_window_source_time_unavailable")
                with _lock:
                    _state["windows"].setdefault(event_id, {})[name] = now
                done.append((event_id, name))
            have = captured if not name else {**captured, name: now}
            for ask in ("+5m", "+60m", "+8h"):   # first reading, the hour, the settled day
                if post and ask in have and ask not in (posted or {}):
                    if post(event, ask):    # False: result not there yet, ask again next tick
                        with _lock:
                            _state["posted"].setdefault(event_id, {})[ask] = now
                        done.append((event_id, "post" + ask))
                    break
            with _lock:
                _state["reactionError"] = None
        except Exception as exc:            # one failing capture must not stop the result refresh
            with _lock:
                _state["reactionError"] = type(exc).__name__
    return done


def tick(events_source: Callable[[], Iterable[Mapping[str, Any]]], refresh: Callable[[], Any],
         now: Optional[datetime] = None, *, baseline=None, window=None, post=None) -> Optional[str]:
    current = now or datetime.now(timezone.utc)
    with _lock:
        last = _state["lastRefreshAt"]
    try:
        events = list(events_source())
    except Exception as exc:
        with _lock:
            _state.update(lastError=type(exc).__name__)
        return None
    if baseline or window or post:
        reaction_tick(events, current, baseline=baseline, window=window, post=post)
    try:
        event_id = due_event(events, current, last)
        if event_id is None:
            return None
        refresh()
        with _lock:
            _state.update(lastRefreshAt=current, lastEventId=event_id, lastError=None,
                          refreshCount=_state["refreshCount"] + 1)
        return event_id
    except Exception as exc:   # a provider failure stays visible and is retried next window step
        with _lock:
            _state.update(lastRefreshAt=current, lastError=type(exc).__name__)
        return None


def _loop(events_source, refresh, sleep, callbacks=None):
    callbacks = callbacks or {}
    while True:
        tick(events_source, refresh, **callbacks)
        sleep(POLL_SECONDS)


def ensure_started(events_source: Callable[[], Iterable[Mapping[str, Any]]], refresh: Callable[[], Any],
                   sleep: Callable[[float], None] = time.sleep, *, baseline=None, window=None, post=None) -> str:
    with _lock:
        thread = _state["thread"]
        if thread is not None and thread.is_alive():
            return "RUNNING"
        thread = threading.Thread(target=_loop, args=(events_source, refresh, sleep,
                                  {"baseline": baseline, "window": window, "post": post}),
                                  name="argus-macro-release-watch", daemon=True)
        _state["thread"] = thread
        thread.start()
        return "STARTED"


def status() -> dict[str, Any]:
    with _lock:
        last = _state["lastRefreshAt"]
        return {"running": bool(_state["thread"] and _state["thread"].is_alive()),
                "lastRefreshAt": last.isoformat() if last else None, "lastEventId": _state["lastEventId"],
                "lastError": _state["lastError"], "refreshCount": _state["refreshCount"],
                "reaction": {"baselines": len(_state.get("baselines") or {}),
                             "windows": {k: sorted(v) for k, v in (_state.get("windows") or {}).items()},
                             "posted": {k: sorted(v) for k, v in (_state.get("posted") or {}).items()},
                             "lastError": _state.get("reactionError")}}

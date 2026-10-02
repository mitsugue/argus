"""Fetch scheduled macro results from the server itself (owner report 2026-10-02).

The US employment report was released at 21:30 JST, but the app showed no
result until the scheduled GitHub workflow ran, and GitHub delays scheduled
runs by tens of minutes. This watcher runs inside the backend: from two
minutes after a scheduled release until forty-five minutes after it, it calls
the existing deterministic result refresh at most once every three minutes.
It never calls AI and never invents a value; the refresh reads the official
sources it already reads.
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
                          "lastError": None, "refreshCount": 0}


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


def tick(events_source: Callable[[], Iterable[Mapping[str, Any]]], refresh: Callable[[], Any],
         now: Optional[datetime] = None) -> Optional[str]:
    current = now or datetime.now(timezone.utc)
    with _lock:
        last = _state["lastRefreshAt"]
    try:
        event_id = due_event(events_source(), current, last)
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


def _loop(events_source, refresh, sleep):
    while True:
        tick(events_source, refresh)
        sleep(POLL_SECONDS)


def ensure_started(events_source: Callable[[], Iterable[Mapping[str, Any]]], refresh: Callable[[], Any],
                   sleep: Callable[[float], None] = time.sleep) -> str:
    with _lock:
        thread = _state["thread"]
        if thread is not None and thread.is_alive():
            return "RUNNING"
        thread = threading.Thread(target=_loop, args=(events_source, refresh, sleep),
                                  name="argus-macro-release-watch", daemon=True)
        _state["thread"] = thread
        thread.start()
        return "STARTED"


def status() -> dict[str, Any]:
    with _lock:
        last = _state["lastRefreshAt"]
        return {"running": bool(_state["thread"] and _state["thread"].is_alive()),
                "lastRefreshAt": last.isoformat() if last else None, "lastEventId": _state["lastEventId"],
                "lastError": _state["lastError"], "refreshCount": _state["refreshCount"]}

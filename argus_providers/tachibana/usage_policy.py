"""Durable, value-free usage limits for the single designated read-only runner."""
from __future__ import annotations
import json
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo
from .models import ErrorClass, TachibanaError
from .singleton import ProcessSingletonLease
TOKYO = ZoneInfo("Asia/Tokyo")

def initialize_blocked_policy(path: Path, clock):
    """Explicit local bootstrap: unknown usage reserves the whole current day.

    Never replace a retained counter or imply that unknown usage was zero.
    This operation makes no provider request and cannot unblock today.
    """
    policy = UsagePolicy(path, clock)
    policy.lease.acquire()
    try:
        local = clock().astimezone(TOKYO)
        row = {'day': local.date().isoformat(), 'count': 6, 'blocked': True,
               'initialUsageUnknown': True}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(row, stream)
            stream.flush(); os.fsync(stream.fileno())
        return {'status': 'INITIALIZED_BLOCKED', 'day': row['day'],
                'networkCalls': 0, 'initialUsageUnknown': True}
    except (OSError, ValueError, TypeError):
        raise TachibanaError(ErrorClass.CONFIGURATION) from None
    finally:
        policy.lease.release()

class UsagePolicy:
    def __init__(self, path: Path, clock):
        if not path.is_absolute() or not path.parent.is_dir():
            raise TachibanaError(ErrorClass.CONFIGURATION)
        self.path, self.clock = path, clock
        self.lease = ProcessSingletonLease(Path("/tmp/argus-tachibana-price-session.lock"))
        self.day = None
        self.count = 0
        self.blocked = False
        self.acquired = False

    def acquire(self):
        self.lease.acquire()
        try:
            if self.path.is_symlink() or not self.path.is_file():
                raise ValueError("invalid_policy")
            if self.path.exists():
                if self.path.is_symlink() or self.path.stat().st_size > 1024:
                    raise ValueError("invalid_policy")
                row = json.loads(self.path.read_text())
                datetime.strptime(row["day"], "%Y-%m-%d")
                if type(row["count"]) is not int or not 0 <= row["count"] <= 6 or type(row["blocked"]) is not bool:
                    raise ValueError("invalid_policy")
                self.day, self.count, self.blocked = row["day"], row["count"], row["blocked"]
                if row.get('initialUsageUnknown') is True and (not self.blocked or self.count != 6):
                    raise ValueError('unknown_usage_must_be_blocked')
            self.acquired = True
        except Exception:
            self.lease.release()
            raise TachibanaError(ErrorClass.CONFIGURATION) from None

    def release(self):
        self.acquired = False
        self.lease.release()

    def before_send(self, *, login=False):
        local = self.clock().astimezone(TOKYO)
        if time(3) <= local.time() < time(6):
            raise TachibanaError(ErrorClass.MAINTENANCE)
        if not self.acquired:
            raise TachibanaError(ErrorClass.CONFIGURATION)
        day = local.date().isoformat()
        if self.day is not None and self.day > day:
            raise TachibanaError(ErrorClass.CLOCK_SKEW)
        if self.day != day:
            self.day, self.count, self.blocked = day, 0, False
        if self.blocked or login and self.count >= 6:
            raise TachibanaError(ErrorClass.DISABLED)
        if login:
            self.count += 1
            self._save()  # Persist before sending: a crash cannot reset the budget.

    def block(self):
        self.day = self.clock().astimezone(TOKYO).date().isoformat()
        self.blocked = True
        self._save()

    def _save(self):
        temporary = self.path.with_suffix(".new")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"day": self.day, "count": self.count, "blocked": self.blocked}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

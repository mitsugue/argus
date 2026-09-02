"""Fail-closed host singleton for the dedicated Tachibana EVENT process."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import stat


class SingletonLeaseError(RuntimeError):
    pass


class ProcessSingletonLease:
    """Hold an empty 0600 flock file for the complete sensor lifetime.

    The file contains no market data or credentials. It deliberately cannot
    live under ARGUS's Recovery-owned ``/var/data`` filesystem.
    """

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise SingletonLeaseError("singleton_path_invalid")
        normalized = Path(os.path.abspath(path))
        if normalized == Path("/var/data") or Path("/var/data") in normalized.parents:
            raise SingletonLeaseError("recovery_filesystem_forbidden")
        if len(str(normalized)) > 512 or not normalized.parent.is_dir():
            raise SingletonLeaseError("singleton_path_invalid")
        self.path = normalized
        self._descriptor: int | None = None

    @property
    def acquired(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> None:
        if self._descriptor is not None:
            raise SingletonLeaseError("singleton_already_acquired")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError:
            raise SingletonLeaseError("singleton_open_failed") from None
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            ):
                raise SingletonLeaseError("singleton_file_invalid")
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SingletonLeaseError("singleton_held") from None
            self._descriptor = descriptor
            descriptor = -1
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def release(self) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def __enter__(self) -> "ProcessSingletonLease":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


__all__ = ["ProcessSingletonLease", "SingletonLeaseError"]

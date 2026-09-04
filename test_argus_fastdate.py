"""argus_fastdate must be a lock-free drop-in for datetime.strptime."""
import threading
import time
from datetime import datetime

import pytest

import argus_fastdate as fd

FORMATS = [
    "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y.%m.%d-%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:00Z",
    "%Y-%m-%d %H:%M", "%Y%m%d", "%H:%M:%S", "%H%M%S", "%H:%M", "%H%M", "%Y/%m/%d %H:%M",
]
SAMPLES = [
    ("%Y-%m-%d", "2026-09-04"), ("%Y-%m-%d", "2026-9-4"), ("%Y-%m-%d", "2026-13-01"),
    ("%Y-%m-%d", "2026-02-30"), ("%Y-%m-%d", "2026-09-04T00"), ("%Y-%m-%d", ""),
    ("%Y-%m-%dT%H:%M:%SZ", "2026-09-04T00:39:14Z"), ("%Y-%m-%dT%H:%M:%SZ", "2026-09-04T24:00:00Z"),
    ("%Y-%m-%dT%H:%M:%SZ", "2026-09-04T00:39:14"), ("%Y-%m-%dT%H:%M:%S%z", "2026-09-04T00:39:14+0000"),
    ("%Y-%m-%dT%H:%M:%S%z", "2026-09-04T09:39:14+09:00"), ("%Y-%m-%dT%H:%M:%S%z", "2026-09-04T00:39:14Z"),
    ("%Y.%m.%d-%H:%M:%S.%f", "2026.09.04-09:30:15.123"), ("%Y.%m.%d-%H:%M:%S.%f", "2026.09.04-09:30:15.123456"),
    ("%Y.%m.%d-%H:%M:%S.%f", "2026.09.04-09:30:15"), ("%Y%m%d%H%M%S", "20260904093015"),
    ("%Y%m%d%H%M%S", "2026090409301"), ("%Y%m%d", "20260904"), ("%Y-%m-%d %H:%M:%S", "2026-09-04 09:30:15"),
    ("%Y-%m-%d %H:%M:%S", "2026-09-04  09:30:15"), ("%Y-%m-%d %H:%M", "2026-09-04 09:30"),
    ("%Y-%m-%dT%H:%M:00Z", "2026-09-04T09:30:00Z"), ("%Y-%m-%dT%H:%M:00Z", "2026-09-04T09:30:15Z"),
    ("%H:%M:%S", "09:30:15"), ("%H%M%S", "093015"), ("%H:%M", "09:30"), ("%H%M", "0930"),
    ("%Y/%m/%d %H:%M", "2026/09/04 09:30"), ("%Y-%m-%dT%H:%M:%S", "2026-09-04T09:30:61"),
    ("%Y-%m-%d", "2026-09-04 "), ("%Y-%m-%d", " 2026-09-04"),
]


@pytest.mark.parametrize("fmt,text", SAMPLES)
def test_matches_stdlib_result_or_error(fmt, text):
    try:
        expected = datetime.strptime(text, fmt)
    except ValueError:
        with pytest.raises(ValueError):
            fd.strptime(text, fmt)
        return
    assert fd.strptime(text, fmt) == expected
    assert fd.strptime(text, fmt).tzinfo == expected.tzinfo


@pytest.mark.parametrize("fmt", FORMATS)
def test_argus_formats_are_served_lock_free(fmt):
    assert fd.supported(fmt)


def test_unsupported_directive_falls_back_to_stdlib():
    assert not fd.supported("%d %b %Y")
    assert fd.strptime("04 Sep 2026", "%d %b %Y") == datetime(2026, 9, 4)


def test_parser_does_not_touch_the_strptime_module_lock(monkeypatch):
    import _strptime

    class Poison:
        def __enter__(self):
            raise AssertionError("_strptime._cache_lock acquired on the lock-free path")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(_strptime, "_cache_lock", Poison())
    assert fd.strptime("2026-09-04", "%Y-%m-%d") == datetime(2026, 9, 4)
    with pytest.raises(AssertionError):
        datetime.strptime("2026-09-04", "%Y-%m-%d")


def test_thread_safe_under_concurrent_first_use():
    errors = []

    def worker(k):
        try:
            for _ in range(200):
                assert fd.strptime("2026-09-04T00:39:14Z", "%Y-%m-%dT%H:%M:%SZ").year == 2026
                assert fd.strptime(f"2026-09-{k:02d}", "%Y-%m-%d").day == k
        except Exception as exc:  # pragma: no cover - failure detail
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(1, 9)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors

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


def test_no_silent_divergence_from_the_stdlib_parser():
    """The module promises it never diverges silently from datetime.strptime.
    A differential run found exactly one case where it did: the pattern is
    compiled with IGNORECASE, so a lowercase 'z' was accepted as UTC where the
    stdlib raises. Sweep the ARGUS format set — valid renderings plus hostile
    input — and require identical outcomes."""
    import random
    from datetime import datetime

    formats = ["%Y%m%d", "%Y%m%d%H%M%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S",
               "%Y-%m-%dT%H:%M:%SZ", "%Y.%m.%d-%H:%M:%S.%f", "%Y-%m-%d %H:%M",
               "%Y-%m-%dT%H:%M:%S%z", "%Y/%m/%d", "%d %m %Y"]
    hostile = ["", "2026", "2026-13-01", "2026-02-30", "20260904x", "x20260904",
               "2026-9-4", "2026-09-04T03:00:60", "2026-09-04T24:00:00",
               "2026-09-04T03:00:00Z", "2026-09-04T03:00:00+09:00",
               "2026-09-04T03:00:00z", "2026.09.04-03:00:00.1",
               "2026.09.04-03:00:00.1234567", "  2026-09-04  ",
               "2026-09-04T03:00:00.123", "2026-09-04T03:00:00+2400", "٢٠٢٦-٠٩-٠٤"]

    def outcome(parser, text, fmt):
        try:
            return ("ok", parser(text, fmt))
        except ValueError:
            return ("ValueError", None)
        except Exception as exc:                     # pragma: no cover
            return (type(exc).__name__, None)

    random.seed(7)
    cases = []
    for fmt in formats:
        for _ in range(120):
            moment = datetime(random.randint(1900, 2099), random.randint(1, 12),
                              random.randint(1, 28), random.randint(0, 23),
                              random.randint(0, 59), random.randint(0, 59),
                              random.choice([0, 1, 999999, 123456, 500]))
            cases.append((moment.strftime(fmt), fmt))
        cases.extend((text, fmt) for text in hostile)

    divergent = [(text, fmt) for text, fmt in cases
                 if outcome(fd.strptime, text, fmt) != outcome(datetime.strptime, text, fmt)]
    assert not divergent, divergent[:5]

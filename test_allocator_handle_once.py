"""2026-10-21: releasing allocator memory must not itself leave memory behind each cycle."""
import subprocess
import sys
import textwrap

import argus_checkpoint_v2 as v2


def test_the_c_library_handle_is_made_once():
    assert v2._allocator_library() is v2._allocator_library()


# Measured in a fresh interpreter: inside the whole suite other threads (imports,
# timers) allocate in the same window and the count drifted past the limit.
_MEASURE = textwrap.dedent("""
    import tracemalloc
    import argus_checkpoint_v2 as v2
    v2._release_unused_allocator_memory(64 * 1024 ** 2)
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for _ in range(200):
        v2._release_unused_allocator_memory(64 * 1024 ** 2)
        {extra}
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    print(sum(stat.size_diff for stat in after.compare_to(before, 'filename') if stat.size_diff > 0))
""")


def _kept_bytes(code):
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True)
    return int(done.stdout.strip().splitlines()[-1])


def test_repeated_release_keeps_almost_nothing():
    # Before: ctypes.CDLL(None) per call kept about 600 bytes a call (119 KB
    # after 200 calls), the few hundred bytes a cycle the 32-cycle proof saw.
    kept = _kept_bytes(_MEASURE.replace("{extra}", "pass"))
    assert kept < 8 * 1024, kept


def test_the_measure_still_sees_the_old_leak():
    # The same measure catches the old fault (a new C library handle every call).
    assert _kept_bytes(_MEASURE.replace("{extra}", "__import__('ctypes').CDLL(None)")) > 2 * 8 * 1024  # well past the 8 KiB limit

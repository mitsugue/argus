"""2026-10-21: releasing allocator memory must not itself leave memory behind each cycle."""
import tracemalloc

import argus_checkpoint_v2 as v2


def test_the_c_library_handle_is_made_once():
    assert v2._allocator_library() is v2._allocator_library()


def test_repeated_release_keeps_almost_nothing():
    # Before: ctypes.CDLL(None) per call kept about 600 bytes a call (119 KB
    # after 200 calls), the few hundred bytes a cycle the 32-cycle proof saw.
    v2._release_unused_allocator_memory(64 * 1024 ** 2)
    tracemalloc.start()
    try:
        before = tracemalloc.take_snapshot()
        for _ in range(200):
            v2._release_unused_allocator_memory(64 * 1024 ** 2)
        # Count only what the release path and ctypes allocate; other threads of
        # the whole suite (imports, timers) allocate meanwhile and are not this.
        scope = [tracemalloc.Filter(True, "*argus_checkpoint_v2.py"), tracemalloc.Filter(True, "*ctypes*")]
        kept = sum(stat.size_diff for stat in tracemalloc.take_snapshot().filter_traces(scope).compare_to(
                   before.filter_traces(scope), 'filename') if stat.size_diff > 0)
    finally:
        tracemalloc.stop()
    assert kept < 8 * 1024, kept

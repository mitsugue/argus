"""Bounded aggregate-sequence allocator acceptance."""
from __future__ import annotations

import pytest

import argus_remote_journal as journal


LIMIT = journal.OPS_SEQUENCE_BY_AGGREGATE_LIMIT
HIGH_WATER = journal.OPS_SEQUENCE_HIGH_WATER_FIELD


def _event(key: str, sequence: int):
    aggregate_type, aggregate_id = key.split(":", 1)
    return {
        "aggregateType": aggregate_type,
        "aggregateId": aggregate_id,
        "sequence": sequence,
    }


def test_exact_4096_allocator_state_is_a_fixed_point():
    sequences = {f"archive:item-{index:04d}": index + 1
                 for index in range(LIMIT)}
    meta = {"totalObserved": LIMIT, HIGH_WATER: LIMIT}

    bounded, bounded_meta = journal.bounded_sequence_allocator_state(
        sequences=sequences, events=[], meta=meta)
    repeated, repeated_meta = journal.bounded_sequence_allocator_state(
        sequences=bounded, events=[], meta=bounded_meta)

    assert bounded == sequences
    assert bounded_meta == meta
    assert repeated == bounded
    assert repeated_meta == bounded_meta


def test_4097th_entry_is_deterministic_and_live_aggregate_is_never_evicted():
    values = {f"archive:item-{index:04d}": index + 1
              for index in range(LIMIT + 1)}
    live_key = "archive:item-0000"
    events = [_event(live_key, 1)]

    first, first_meta = journal.bounded_sequence_allocator_state(
        sequences=values, events=events, meta={"totalObserved": LIMIT + 1})
    reversed_input, reversed_meta = journal.bounded_sequence_allocator_state(
        sequences=dict(reversed(list(values.items()))), events=events,
        meta={"totalObserved": LIMIT + 1})

    assert len(first) == LIMIT
    assert live_key in first
    assert "archive:item-0001" not in first
    assert first == reversed_input
    assert first_meta == reversed_meta
    assert first_meta[HIGH_WATER] == LIMIT + 1


def test_existing_high_water_survives_eviction_and_dominates_map_values():
    sequences = {f"archive:item-{index:04d}": index + 1
                 for index in range(LIMIT + 1)}
    high_water = LIMIT + 99

    bounded, meta = journal.bounded_sequence_allocator_state(
        sequences=sequences, events=[],
        meta={"totalObserved": LIMIT + 1, HIGH_WATER: high_water})

    assert len(bounded) == LIMIT
    assert meta[HIGH_WATER] == high_water
    assert max(bounded.values()) < high_water


@pytest.mark.parametrize("bad", [True, -1, "4096", None])
def test_invalid_high_water_is_rejected(bad):
    with pytest.raises(ValueError, match="ops_sequence_allocator_invalid"):
        journal.bounded_sequence_allocator_state(
            sequences={"mission:one": 1}, events=[],
            meta={HIGH_WATER: bad})


def test_more_than_4096_live_aggregates_fails_closed():
    events = [_event(f"mission:item-{index:04d}", 1)
              for index in range(LIMIT + 1)]

    with pytest.raises(
            ValueError, match="ops_sequence_allocator_live_set_oversized"):
        journal.bounded_sequence_allocator_state(
            sequences={}, events=events, meta={})


def test_4097th_aggregate_advances_high_water_and_remains_bounded():
    sequences = {f"archive:item-{index:04d}": index + 1
                 for index in range(LIMIT + 1)}
    bounded, meta = journal.bounded_sequence_allocator_state(
        sequences=sequences, events=[], meta={})
    evicted_key = "archive:item-0000"

    sequence = journal.next_bounded_ops_sequence(
        aggregate_key=evicted_key, sequences=bounded, meta=meta)
    bounded[evicted_key] = sequence
    meta[HIGH_WATER] = sequence
    bounded, meta = journal.bounded_sequence_allocator_state(
        sequences=bounded, events=[], meta=meta)

    assert sequence == LIMIT + 2
    assert len(bounded) == LIMIT
    assert bounded[evicted_key] == sequence
    assert meta[HIGH_WATER] == sequence


def test_reused_evicted_aggregate_after_restart_never_reuses_sequence():
    before_restart = {f"archive:item-{index:04d}": index + 1
                      for index in range(LIMIT + 1)}
    persisted, persisted_meta = journal.bounded_sequence_allocator_state(
        sequences=before_restart, events=[], meta={})
    reused_key = "archive:item-0000"
    assert reused_key not in persisted

    # Copies model the only allocator state available after cold restart.
    restored = dict(persisted)
    restored_meta = dict(persisted_meta)
    sequence = journal.next_bounded_ops_sequence(
        aggregate_key=reused_key, sequences=restored, meta=restored_meta)

    assert sequence == LIMIT + 2
    assert sequence > before_restart[reused_key]


def test_retained_aggregate_continues_its_own_sequence_not_global_high_water():
    sequence = journal.next_bounded_ops_sequence(
        aggregate_key="mission:retained",
        sequences={"mission:retained": 7},
        meta={HIGH_WATER: 100})

    assert sequence == 8


@pytest.mark.parametrize("bad", [True, -1, "100", None])
def test_next_sequence_rejects_invalid_high_water(bad):
    with pytest.raises(ValueError, match="ops_sequence_allocator_invalid"):
        journal.next_bounded_ops_sequence(
            aggregate_key="mission:one", sequences={},
            meta={HIGH_WATER: bad})

"""Shared finite byte budgets for encrypted Remote Recovery artifacts.

The standalone journal module owns the compact-readback derivation because the
ledger publisher copies it across a branch switch.  This module binds the
broader encrypted Recovery budgets to that same authority.
"""

import argus_remote_journal as journal


MIB = 1024 * 1024

MAX_RECOVERY_PLAINTEXT_BYTES = \
    journal.COMPACT_READBACK_RECOVERY_PLAINTEXT_BYTES
MAX_RECOVERY_ENCODED_BYTES = 6 * MIB
MAX_RECOVERY_SIDECAR_BYTES = 8 * MIB
COMPACT_READBACK_DUPLICATION_FACTOR = \
    journal.COMPACT_READBACK_DUPLICATION_FACTOR
RECOVERY_NON_READBACK_RESERVE_BYTES = \
    journal.COMPACT_READBACK_NON_DUPLICATED_RESERVE_BYTES
MAX_COMPACT_READBACK_BYTES = journal.MAX_COMPACT_READBACK_BYTES

assert MAX_COMPACT_READBACK_BYTES == 1_572_864
assert (
    MAX_COMPACT_READBACK_BYTES * COMPACT_READBACK_DUPLICATION_FACTOR
    + RECOVERY_NON_READBACK_RESERVE_BYTES
    == MAX_RECOVERY_PLAINTEXT_BYTES
)

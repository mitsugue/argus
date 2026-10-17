import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import unittest

from argus_ai_usage_receipt import make_receipt
from argus_ai_usage_store import initialize, append, read_page, read_summary


def receipt(identity, cost=0.01):
    return make_receipt(call_id=identity, provider="openai", feature="market_brief",
                        started_at="2026-09-12T01:00:00Z", completed_at="2026-09-12T01:00:01Z",
                        requested_model="gpt-6-astra", returned_model="gpt-6-astra",
                        outcome="success", provider_called=True, estimated_cost_usd=cost)


class DurableUsageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "usage.sqlite3"
        initialize(self.path)

    def test_concurrent_first_writes_never_see_partial_database(self):
        target = self.path.with_name("first-calls.sqlite3")
        barrier = threading.Barrier(8)
        def write(index):
            barrier.wait(timeout=5)
            initialize(target)
            return append(target, [receipt(str(index))])
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(write, range(8)))
        self.assertEqual(sum(row["inserted"] for row in results), 8)
        self.assertEqual(read_summary(target)["durableReceiptCount"], 8)
        self.assertEqual(list(target.parent.glob(".usage-init-*")), [])

    def test_failed_initialization_does_not_publish_empty_store(self):
        target = self.path.with_name("failed-init.sqlite3")
        with patch("argus_ai_usage_store.os.link", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError): initialize(target)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob(".usage-init-*")), [])
        initialize(target)
        self.assertEqual(read_summary(target)["durableReceiptCount"], 0)

    def test_reopen_preserves_identity_and_estimate(self):
        original = receipt("one")
        append(self.path, [original]); initialize(self.path)
        self.assertEqual(read_page(self.path)["rows"][0]["receipt"], original)
        self.assertEqual(append(self.path, [original])["inserted"], 0)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_summary_not_limited_by_latest_500(self):
        append(self.path, [receipt(str(index)) for index in range(650)])
        self.assertEqual(len(read_page(self.path)["rows"]), 500)
        summary = read_summary(self.path)
        self.assertEqual(summary["durableReceiptCount"], 650)
        self.assertEqual(sum(row["knownEstimatedCostUsd"] for row in summary["groups"]), 6.5)
        self.assertFalse(summary["displayWindowLimitApplied"])

    def test_conflicting_import_rolls_back_entire_batch(self):
        append(self.path, [receipt("old")])
        with self.assertRaisesRegex(ValueError, "conflicting_usage_call_id"):
            append(self.path, [receipt("new"), receipt("old", 0.25)])
        self.assertEqual(read_summary(self.path)["durableReceiptCount"], 1)
        self.assertEqual(read_page(self.path)["rows"][0]["receipt"]["estimatedCostUsd"], 0.01)

    def test_paged_export_restore_has_stable_watermark(self):
        originals = [receipt(str(i)) for i in range(7)]
        append(self.path, originals)
        first = read_page(self.path, limit=3)
        append(self.path, [receipt("later")])
        exported = first["rows"]
        page = first
        while page["hasMore"]:
            page = read_page(self.path, after_sequence=page["nextAfterSequence"],
                             through_sequence=first["throughSequence"], limit=3)
            exported += page["rows"]
        other = self.path.with_name("restored.sqlite3"); initialize(other)
        append(other, [row["receipt"] for row in exported])
        self.assertEqual([row["receipt"] for row in read_page(other)["rows"]], originals)

    def test_concurrent_duplicate_settlements_remain_one_call(self):
        row = receipt("same-call")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: append(self.path, [row]), range(12)))
        self.assertEqual(sum(x["inserted"] for x in results), 1)
        self.assertEqual(read_summary(self.path)["durableReceiptCount"], 1)

    def test_absent_or_corrupt_store_is_not_zero_usage(self):
        absent = self.path.with_name("missing.sqlite3")
        with self.assertRaises(FileNotFoundError): read_summary(absent)
        self.assertFalse(absent.exists())
        append(self.path, [receipt("one")])
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE usage_receipts SET digest='invalid'")
        with self.assertRaisesRegex(ValueError, "integrity_mismatch"): read_summary(self.path)

    def test_read_only_get_does_not_modify_file(self):
        append(self.path, [receipt("one")])
        content, mtime = self.path.read_bytes(), self.path.stat().st_mtime_ns
        read_page(self.path); read_summary(self.path)
        self.assertEqual(self.path.read_bytes(), content)
        self.assertEqual(self.path.stat().st_mtime_ns, mtime)

    def test_symlink_and_newer_schema_not_reset(self):
        link = self.path.with_name("link.sqlite3"); link.symlink_to(self.path)
        with self.assertRaises(ValueError): initialize(link)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError, "schema_mismatch"): initialize(self.path)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)


if __name__ == "__main__": unittest.main()

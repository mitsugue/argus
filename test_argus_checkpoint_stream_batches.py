"""Canonical bytes, bounded batches and fail-closed storage regressions."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import argus_persistent_storage as storage


class CheckpointStreamBatchTests(unittest.TestCase):
    def assert_canonical(self, value):
        chunks = list(storage._canonical_chunks(value))
        self.assertEqual(b"".join(chunks), storage._canonical(value))
        self.assertTrue(all(len(c) <= storage.JSON_STREAM_CHUNK_BYTES
                            for c in chunks))

    def test_prices_bars_unicode_and_mixed_boundaries(self):
        self.assert_canonical({"prices": [i / 3 for i in range(5000)]})
        self.assert_canonical({"bars": [
            {"date": str(i), "close": i / 3, "volume": i * 42,
             "label": "日本\n\"☃"} for i in range(2000)]})
        self.assert_canonical(list(range(1024)) + [
            {"nested": list(range(4000))}, "x" * 40000,
            (None, True, False, -0.0, float("inf"), float("nan"))
        ] + list(range(2050)))

    def test_bounded_encoding_calls_for_long_flat_list(self):
        calls = []
        encode = json.JSONEncoder.encode

        def observed(encoder, value):
            if type(value) is list:
                calls.append(len(value))
            return encode(encoder, value)

        with mock.patch.object(json.JSONEncoder, "encode", observed):
            result = b"".join(storage._canonical_chunks(list(range(10000))))
        self.assertEqual(result, storage._canonical(list(range(10000))))
        self.assertGreater(len(calls), 1)
        self.assertLessEqual(max(calls), 1024)
        self.assertLess(len(calls), 20)

    def test_shared_children_and_subclasses_keep_standard_json_behavior(self):
        class Numbers(list):
            pass

        shared = {"z": [1, 2], "a": "x"}
        self.assert_canonical([shared] * 1500 + [Numbers([3, 4])])

    def test_random_mixed_trees_preserve_canonical_hash(self):
        rng = random.Random(926)

        def tree(depth):
            if depth <= 0:
                return rng.choice([None, True, False, -0.0, 7, 0.125,
                                   "日本", "\t\"\\", "x" * 100])
            if rng.randrange(2):
                return [tree(depth - 1) for _ in range(rng.randrange(15))]
            return {str(i): tree(depth - 1)
                    for i in range(rng.randrange(12))}

        for _ in range(12):
            self.assert_canonical([tree(3) for _ in range(60)])

    def test_late_invalid_input_never_replaces_prior_checkpoint(self):
        cycle = []
        cycle.append(cycle)
        invalid_values = [
            (cycle, "checkpoint_json_cycle_detected"),
            ("x" * (storage.MAXIMUM_JSON_SCALAR_CHARS + 1),
             "checkpoint_json_scalar_too_large"),
        ]
        for bad, reason in invalid_values:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as root:
                target = Path(root) / "state.json"
                storage.write_checkpoint(str(target), {"schemaVersion": "argus-durable-v3", "keep": [1, 2, 3]},
                                         temp_directory=root)
                before = target.read_bytes()
                with self.assertRaisesRegex(storage.PersistentStorageError, reason):
                    list(storage._canonical_chunks(list(range(4000)) + [bad]))
                with self.assertRaisesRegex(storage.PersistentStorageError, reason):
                    storage.atomic_write_json(
                        str(target), list(range(4000)) + [bad],
                        temp_directory=root)
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(list(Path(root).glob("*.v1338-tmp")), [])

    def test_seal_and_tamper_detection_across_batch_boundary(self):
        sealed = storage.seal_checkpoint({"schemaVersion": "argus-durable-v3",
                                          "prices": list(range(5000))})
        self.assertTrue(storage.verify_checkpoint(sealed, require_seal=True))
        sealed["prices"][1024] += 1
        self.assertFalse(storage.verify_checkpoint(sealed, require_seal=True))


if __name__ == "__main__":
    unittest.main()

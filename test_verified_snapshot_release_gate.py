import os
import http.client
import tempfile
import unittest
from unittest import mock

import argus_verified_snapshot
from scripts import verified_snapshot_release_gate as gate


def _payload(symbol):
    bars = [
        {
            "date": "2026-07-22",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1000,
        },
        {
            "date": "2026-07-23",
            "open": 101.0,
            "high": 103.0,
            "low": 100.0,
            "close": 102.0,
            "volume": 1100,
        },
    ]
    contexts = {
        horizon: {
            "datasetHash": "dataset-1",
            "asOf": "2026-07-23T06:00:00Z",
        }
        for horizon in ("1", "5", "20")
    }
    return {
        "symbol": symbol,
        "instrumentMetadata": {"symbol": symbol},
        "status": "complete",
        "automaticAiCalls": 0,
        "indicators": {"status": "complete", "bars": bars},
        "marketReplay": {"cacheStatus": "updated", "contexts": contexts},
    }


def _snapshot(symbol, horizon):
    return argus_verified_snapshot.build_snapshot(
        payload=_payload(symbol),
        kind="market-chart",
        instrument=symbol,
        horizon=horizon,
        dataset_hash="dataset-1",
        method_version="method-1",
        as_of="2026-07-23T06:00:00Z",
        generated_at="2026-07-23T06:05:00Z",
        quality="live",
        source_status={"chart": "complete"},
    )


class VerifiedSnapshotReleaseGateTests(unittest.TestCase):
    def test_backend_wait_accepts_short_render_sha(self):
        responses = [
            (200, {}, {
                "status": "ok", "backendVersion": "13.2.2",
                "buildSha": "57b8c33",
            }),
            (200, {}, {
                "status": "ok", "backendVersion": "13.3.0",
                "buildSha": "abcdef0", "asOf": "2026-07-23T06:00:00Z",
            }),
        ]
        with mock.patch.object(gate, "_request", side_effect=responses), \
                mock.patch.object(gate.time, "sleep"):
            value = gate.wait_for_backend(
                "https://example.invalid", "13.3.0",
                "abcdef0123456789", 30, 1)
        self.assertEqual("abcdef0", value["buildSha"])

    def test_seed_fails_closed_without_admin_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                    gate.GateFailure, "ARGUS_ADMIN_TOKEN_missing"):
                gate.seed_snapshots(
                    "https://example.invalid", "abcdef0123456789")

    def test_seed_returns_only_redacted_operational_metadata(self):
        response = {
            "status": "completed",
            "chartIntelligence": {
                "status": "complete",
                "verifiedViewsStateHash": "hash-1",
                "viewPublications": [],
            },
            "remoteJournal": {
                "readBackVerified": False,
                "remoteCommitSha": "abc",
                "errorClass": "commit_receipt_stale",
            },
            "costPolicy": {"automaticAiExecutions": 0},
        }
        with mock.patch.dict(
                os.environ, {"ARGUS_ADMIN_TOKEN": "do-not-copy"}), \
                mock.patch.object(gate, "_request",
                                  return_value=(200, {}, response)) as request:
            value = gate.seed_snapshots(
                "https://example.invalid", "abcdef0123456789")
        self.assertNotIn("do-not-copy", str(value))
        headers = request.call_args.kwargs["headers"]
        self.assertEqual("do-not-copy", headers["X-ARGUS-ADMIN-TOKEN"])
        self.assertNotIn("do-not-copy", request.call_args.args)

    def test_seed_unconfirmed_response_defers_success_to_snapshot_readback(self):
        for exception in (
                http.client.RemoteDisconnected(), TimeoutError()):
            with self.subTest(exception=type(exception).__name__), \
                    mock.patch.dict(
                        os.environ, {"ARGUS_ADMIN_TOKEN": "do-not-copy"}), \
                    mock.patch.object(
                        gate, "_request", side_effect=exception):
                value = gate.seed_snapshots(
                    "https://example.invalid", "abcdef0123456789")
            self.assertTrue(value["responseUnconfirmed"])
            self.assertEqual(
                "response_unconfirmed_verify_readback",
                value["businessStatus"])
            self.assertEqual(
                type(exception).__name__,
                value["remoteJournal"]["errorClass"])
            self.assertNotIn("do-not-copy", str(value))

    def test_matrix_requires_all_12_snapshots_and_304(self):
        responses = []
        for instrument in gate.INSTRUMENTS:
            for horizon in gate.HORIZONS:
                snapshot = _snapshot(instrument, horizon)
                etag = f'"{snapshot["snapshotId"]}"'
                responses.extend([
                    (200, {
                        "etag": f"W/{etag}",
                        "x-argus-compute-mode": "read-only",
                    }, snapshot),
                    (304, {"etag": etag}, None),
                ])
        with mock.patch.object(gate, "_request",
                               side_effect=responses) as request:
            matrix = gate.verify_matrix("https://example.invalid")
        self.assertEqual(12, len(matrix))
        self.assertEqual(24, request.call_count)
        self.assertTrue(all(row["automaticAiCalls"] == 0 for row in matrix))
        self.assertTrue(all(row["notModifiedStatus"] == 304 for row in matrix))

    def test_matrix_fails_on_not_ready(self):
        with mock.patch.object(
                gate, "_request",
                return_value=(503, {}, {"status": "not_ready"})):
            with self.assertRaisesRegex(
                    gate.GateFailure, "snapshot_1321_1D_http_503"):
                gate.verify_matrix("https://example.invalid")

    def test_concurrent_reads_preserve_published_snapshot_identity(self):
        matrix = []
        snapshots = {}
        for instrument in gate.INSTRUMENTS:
            for horizon in gate.HORIZONS:
                snapshot = _snapshot(instrument, horizon)
                matrix.append({
                    "instrument": instrument,
                    "horizon": horizon,
                    "snapshotId": snapshot["snapshotId"],
                })
                snapshots[(instrument, horizon)] = snapshot

        def request(url, **_kwargs):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(url).query)
            key = (query["symbol"][0], query["horizon"][0])
            return (200, {"x-argus-compute-mode": "read-only"},
                    snapshots[key])

        with mock.patch.object(gate, "_request", side_effect=request):
            rows = gate.verify_concurrent_reads(
                "https://example.invalid", matrix)
        self.assertEqual(12, len(rows))
        self.assertTrue(all(row["computeMode"] == "read-only"
                            for row in rows))

    def test_artifact_is_metadata_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "gate.json")
            gate.write_artifact(path, {"status": "failure", "failures": []})
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        self.assertIn('"status": "failure"', text)
        self.assertNotIn("ARGUS_ADMIN_TOKEN", text)


if __name__ == "__main__":
    unittest.main()

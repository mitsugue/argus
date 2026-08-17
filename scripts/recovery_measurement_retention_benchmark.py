#!/usr/bin/env python3
"""Adversarial 13-14 MiB retention and max-state hot-path benchmark."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_recovery_measurement as measurement  # noqa: E402
import argus_recovery_registry as registry  # noqa: E402


UTC = dt.timezone.utc
MIB = 1024 * 1024


def _p95(values):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * .95) - 1)]


def _histogram(index: int, count: int):
    result = [0] * measurement.MAX_HISTOGRAM_BINS
    result[index] = count
    return result


def build_adversarial_artifact():
    start = dt.datetime(2026, 1, 1, tzinfo=UTC)
    end = start + dt.timedelta(
        minutes=measurement.BUCKET_MINUTES * (measurement.MAX_BUCKETS - 1))
    artifact = measurement.new_artifact(
        measurement_generation_id="retention-benchmark-generation",
        producer_build_sha="a" * 40,
        instrumentation_coverage_sha256="b" * 64,
        created_at=start)
    mutation_ids = sorted(registry.mutation_by_id())
    mutation_count = len(mutation_ids)
    estimated_per_mutation = 100
    bucket_estimated = mutation_count * estimated_per_mutation
    bucket_records = mutation_count
    bucket_candidate = bucket_estimated + bucket_records * \
        measurement.FUTURE_WAL_RECORD_FRAMING_ESTIMATE_BYTES
    artifact["intervalBuckets"] = [{
        "bucketStart": measurement.canonical_timestamp(
            start + dt.timedelta(minutes=measurement.BUCKET_MINUTES * index)),
        "mutationCount": mutation_count,
        "estimatedPlaintextBytes": bucket_estimated,
        "candidateWalPlaintextBytesEstimate": bucket_candidate,
        "recordCount": bucket_records,
        "latencyMicrosTotal": bucket_estimated,
        "successCount": mutation_count,
        "failureCount": 0,
        "maxSingleMutationPlaintextBytesEstimate": estimated_per_mutation,
        "byMutationClass": {mutation_id: 1 for mutation_id in mutation_ids},
        "plaintextBytesHistogram": _histogram(1, mutation_count),
        "latencyMicrosHistogram": _histogram(0, mutation_count),
    } for index in range(measurement.MAX_BUCKETS)]

    mutations_per_day = 24 * (60 // measurement.BUCKET_MINUTES)
    artifact["dailyDistributions"] = []
    for day_offset in range(measurement.RETENTION_DAYS):
        by_class = {}
        for mutation_id in mutation_ids:
            estimated = mutations_per_day * estimated_per_mutation
            records = mutations_per_day
            by_class[mutation_id] = {
                "mutationCount": mutations_per_day,
                "estimatedPlaintextBytes": estimated,
                "candidateWalPlaintextBytesEstimate": estimated + records *
                    measurement.FUTURE_WAL_RECORD_FRAMING_ESTIMATE_BYTES,
                "recordCount": records,
                "latencyMicrosTotal": estimated,
                "successCount": mutations_per_day,
                "failureCount": 0,
                "maxSingleMutationPlaintextBytesEstimate":
                    estimated_per_mutation,
                "plaintextBytesHistogram": _histogram(1, mutations_per_day),
                "latencyMicrosHistogram": _histogram(0, mutations_per_day),
            }
        artifact["dailyDistributions"].append({
            "day": (start + dt.timedelta(days=day_offset)).date().isoformat(),
            "byMutationClass": by_class,
        })

    mutation = registry.mutation_by_id()["core.batch_cursor"]
    artifact["recentMutations"] = [{
        "observedAt": measurement.canonical_timestamp(
            end - dt.timedelta(minutes=measurement.BUCKET_MINUTES *
                               (measurement.MAX_RECENT_MUTATIONS - 1 - index))),
        "mutationClassId": mutation.mutationId,
        "targetStateIds": list(mutation.targetStateIds),
        "estimatedPlaintextBytes": 100,
        "candidateWalPlaintextBytesEstimate": 100 +
            measurement.FUTURE_WAL_RECORD_FRAMING_ESTIMATE_BYTES,
        "recordCount": 1,
        "latencyMicros": 100,
        "success": True,
        "coverageClassification": "UNKNOWN",
        "currentWalCoverage": mutation.currentWalCoverage.value,
        "localSequence": index,
    } for index in range(measurement.MAX_RECENT_MUTATIONS)]

    section_keys = registry.registered_checkpoint_keys()
    observed_text = measurement.canonical_timestamp(end)
    artifact["checkpointSamples"] = [{
        "sampleId": f"sample-{index:08d}-" + "x" * 100,
        "observedAt": observed_text,
        "success": True,
        "detailed": True,
        "detailReason": "OWNER_AUTHORIZED",
        "checkpointSerializedBytes": 1_000,
        "sectionSerializedBytes": {key: 1 for key in section_keys},
        "serializationDurationMicros": 1,
        "sectionAccountingDurationMicros": 1,
        "writeSealDurationMicros": 1,
        "fsyncReadbackDurationMicros": 1,
        "peakRssBytes": 1,
        "localWalBytes": 1,
        "localWalRecords": 1,
        "localWalHighWater": 1,
        "legacyRemoteAckSequence": 1,
        "legacyRemoteAckAt": observed_text,
        "legacyRemoteAckIsExactWalDurability": False,
    } for index in range(measurement.MAX_CHECKPOINT_SAMPLES)]

    retained_mutations = measurement.MAX_BUCKETS * mutation_count
    artifact["updatedAt"] = observed_text
    artifact["coverage"].update({
        "latestObservedAuthoritativeMutationAt": observed_text,
        "legacyRemoteAckAt": observed_text,
        "instrumentedMutationClassIds": mutation_ids,
        "allExpectedMutationClassesObserved": True,
    })
    artifact["aggregateCounters"].update({
        "lifetimeMutationCount": retained_mutations,
        "lifetimeEstimatedPlaintextBytes": retained_mutations *
            estimated_per_mutation,
        "lifetimeRecordCount": retained_mutations,
        "lifetimeSuccessCount": retained_mutations,
        "retainedMutationCount": retained_mutations,
        "retainedEstimatedPlaintextBytes": retained_mutations *
            estimated_per_mutation,
        "retainedRecordCount": retained_mutations,
        "retainedBucketCount": measurement.MAX_BUCKETS,
        "retainedRecentMutationCount": measurement.MAX_RECENT_MUTATIONS,
        "retainedCheckpointSampleCount": measurement.MAX_CHECKPOINT_SAMPLES,
    })
    validation = measurement.validate_artifact(artifact)
    if not validation.valid:
        raise RuntimeError(validation.code)
    return artifact, end


def run(samples: int, hot_samples: int):
    artifact, now = build_adversarial_artifact()
    input_bytes = len(measurement._canonical_bytes_unchecked(artifact))
    plan_seconds = []
    plan = None
    for _ in range(samples):
        started = time.perf_counter()
        plan = measurement.plan_retention(artifact, now=now)
        plan_seconds.append(time.perf_counter() - started)
        if plan.status != "ok":
            raise RuntimeError(plan.status)
    assert plan is not None

    accumulator = measurement.MeasurementAccumulator(artifact)
    hot_seconds = []
    for index in range(hot_samples):
        started = time.perf_counter()
        status = accumulator.record_mutation(
            "core.batch_cursor", estimated_plaintext_bytes=100,
            record_count=1, latency_micros=100, success=True,
            coverage_classification="UNKNOWN", observed_at=now,
            local_sequence=measurement.MAX_RECENT_MUTATIONS + index)
        hot_seconds.append(time.perf_counter() - started)
        if status != "recorded":
            raise RuntimeError(status)
    plan_p95 = _p95(plan_seconds)
    hot_p95 = _p95(hot_seconds)
    hot_max = max(hot_seconds)
    gates = {
        "adversarialInput13To14MiB": 13 <= input_bytes / MIB <= 14,
        "planningP95Seconds": plan_p95 <= 2.0,
        "hotPathP95Milliseconds": hot_p95 * 1000 <= 5.0,
        "hotPathMaximumMilliseconds": hot_max * 1000 <= 20.0,
        "rowEncodeBound": plan.evidence.row_encodes <=
            plan.evidence.input_rows,
        "collectionPassBound": plan.evidence.collection_passes == 4,
        "finalDocumentEncodeBound": plan.evidence.final_document_encodes == 1,
        "persistedSizeBound": plan.evidence.final_bytes <=
            measurement.MAX_PERSISTED_BYTES,
    }
    return {
        "schemaVersion": "argus-recovery-retention-benchmark-v1",
        "inputBytes": input_bytes,
        "inputMiB": round(input_bytes / MIB, 3),
        "planningSamples": samples,
        "planningP95Seconds": round(plan_p95, 6),
        "hotPathSamples": hot_samples,
        "hotPathP95Milliseconds": round(hot_p95 * 1000, 6),
        "hotPathMaximumMilliseconds": round(hot_max * 1000, 6),
        "retentionEvidence": plan.evidence.__dict__,
        "gates": gates,
        "passed": all(gates.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--hot-samples", type=int, default=200)
    args = parser.parse_args()
    if not 1 <= args.samples <= 20 or not 10 <= args.hot_samples <= 10_000:
        raise SystemExit("benchmark_arguments_invalid")
    report = run(args.samples, args.hot_samples)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

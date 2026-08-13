"""Bounded, privacy-safe recovery measurement (non-authoritative shadow only).

Only counters, timestamps, stable registry identifiers and byte estimates are
accepted.  This module intentionally has no payload parameter and never stores
checkpoint/WAL content, URLs, prompts, holdings, research or model output.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import resource
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

import argus_persistent_storage
import argus_recovery_registry


SCHEMA = "argus-recovery-measurement-shadow-v1"
RETENTION_DAYS = 31
BUCKET_MINUTES = 5
MAX_BUCKETS = RETENTION_DAYS * 24 * (60 // BUCKET_MINUTES)
MAX_DAILY_DISTRIBUTIONS = RETENTION_DAYS + 1
MAX_RECENT_MUTATIONS = 256
MAX_CHECKPOINT_SAMPLES = 2048
MAX_PERSISTED_BYTES = 12 * 1024 * 1024
PERSIST_INTERVAL_SECONDS = 5 * 60
FUTURE_RECORD_FRAMING_ESTIMATE_BYTES = 256
LARGE_SECTION_KEYS = (
    "marketLedger", "verifiedViewSnapshots", "assetChartReports",
    "chartIntelligence", "marketReplay", "todayIntelligence")
_HISTOGRAM_UPPER_BOUNDS = (
    0, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768,
    65536, 131072, 262144, 524288, 1048576, 2097152, 4194304,
    8388608, 16777216, 33554432, 67108864, 134217728, 268435456,
    536870912)
UTC = dt.timezone.utc


def _utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def _iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[dt.datetime]:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _canonical_size(value: Any) -> int:
    encoder = json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sum(len(chunk.encode("utf-8")) for chunk in encoder.iterencode(value))


def serialized_size_estimate(value: Any) -> int:
    """Return canonical plaintext bytes without retaining or returning content."""
    return _canonical_size(value)


def checkpoint_section_sizes(blob: Mapping[str, Any]) -> Dict[str, int]:
    """Deterministic top-level accounting, sampled only at checkpoint assembly."""
    known_keys = sorted({key for row in argus_recovery_registry.states()
                         for key in row.checkpointKeys})
    return {key: _canonical_size(blob[key]) for key in known_keys if key in blob}


def peak_rss_bytes() -> Optional[int]:
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # macOS reports bytes; Linux and most BSD production images report KiB.
        return value if sys.platform == "darwin" else value * 1024
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def measure_jsonl_metadata(path: Optional[str], *,
                           maximum_bytes: int = 64 * 1024 * 1024
                           ) -> Dict[str, Any]:
    """Count bytes/non-empty records without parsing or retaining private rows."""
    result = {"configured": bool(path), "exists": False, "bytes": 0,
              "recordCount": 0, "complete": True}
    if not path:
        return result
    try:
        size = os.path.getsize(path)
        result.update({"exists": True, "bytes": int(size)})
        if size > int(maximum_bytes):
            result["complete"] = False
            result["reason"] = "measurement_maximum_exceeded"
            return result
        count = 0
        with open(path, "rb") as handle:
            for line in handle:
                if line.strip():
                    count += 1
        result["recordCount"] = count
    except FileNotFoundError:
        pass
    except OSError:
        result.update({"complete": False, "reason": "measurement_io_error"})
    return result


def _histogram() -> Dict[str, int]:
    return {str(value): 0 for value in _HISTOGRAM_UPPER_BOUNDS}


def _histogram_add(histogram: Dict[str, int], value: float) -> None:
    safe = max(0, int(math.ceil(float(value or 0))))
    upper = next((bound for bound in _HISTOGRAM_UPPER_BOUNDS
                  if safe <= bound), _HISTOGRAM_UPPER_BOUNDS[-1])
    histogram[str(upper)] = int(histogram.get(str(upper)) or 0) + 1


def _histogram_quantile(histogram: Mapping[str, int], quantile: float
                        ) -> Optional[int]:
    total = sum(max(0, int(value or 0)) for value in histogram.values())
    if total <= 0:
        return None
    target = max(1, int(math.ceil(total * float(quantile))))
    seen = 0
    for bound in _HISTOGRAM_UPPER_BOUNDS:
        seen += max(0, int(histogram.get(str(bound)) or 0))
        if seen >= target:
            return bound
    return _HISTOGRAM_UPPER_BOUNDS[-1]


def _distribution_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
    histogram = row.get("plaintextBytesHistogram") or {}
    return {
        "mutationCount": int(row.get("mutationCount") or 0),
        "plaintextBytesEstimate": int(row.get("plaintextBytesEstimate") or 0),
        "candidateRecordPlaintextBytesEstimate": int(
            row.get("candidateRecordPlaintextBytesEstimate") or 0),
        "maxSingleMutationPlaintextBytesEstimate": int(
            row.get("maxSingleMutationPlaintextBytesEstimate") or 0),
        "mutationPlaintextBytesApproxP50": _histogram_quantile(histogram, .50),
        "mutationPlaintextBytesApproxP95": _histogram_quantile(histogram, .95),
        "mutationPlaintextBytesApproxP99": _histogram_quantile(histogram, .99),
        "histogramQuantilesAreUpperBounds": True,
    }


def _new_distribution() -> Dict[str, Any]:
    return {
        "mutationCount": 0, "plaintextBytesEstimate": 0,
        "candidateRecordPlaintextBytesEstimate": 0,
        "maxSingleMutationPlaintextBytesEstimate": 0,
        "plaintextBytesHistogram": _histogram(),
        "latencyMsHistogram": _histogram(),
    }


def _merge_distribution(target: Dict[str, Any], source: Mapping[str, Any]) -> None:
    target["mutationCount"] += int(source.get("mutationCount") or 0)
    target["plaintextBytesEstimate"] += int(
        source.get("plaintextBytesEstimate") or 0)
    target["candidateRecordPlaintextBytesEstimate"] += int(
        source.get("candidateRecordPlaintextBytesEstimate") or 0)
    target["maxSingleMutationPlaintextBytesEstimate"] = max(
        target["maxSingleMutationPlaintextBytesEstimate"],
        int(source.get("maxSingleMutationPlaintextBytesEstimate") or 0))
    for field in ("plaintextBytesHistogram", "latencyMsHistogram"):
        source_histogram = source.get(field) or {}
        for bound in _HISTOGRAM_UPPER_BOUNDS:
            key = str(bound)
            target[field][key] += int(source_histogram.get(key) or 0)


def _empty_document(now: dt.datetime) -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA,
        "authoritative": False,
        "coverage": "SHADOW_INCOMPLETE",
        "createdAt": _iso(now),
        "updatedAt": _iso(now),
        "retentionDays": RETENTION_DAYS,
        "bucketMinutes": BUCKET_MINUTES,
        "acceptanceClockStarted": False,
        "buckets": [],
        "dailyDistributions": {},
        "recentMutations": [],
        "checkpointSamples": [],
        "measurementErrors": 0,
    }


def _validate_document(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA or \
            value.get("authoritative") is not False or \
            value.get("coverage") != "SHADOW_INCOMPLETE":
        return False
    for key, maximum in (("buckets", MAX_BUCKETS),
                         ("recentMutations", MAX_RECENT_MUTATIONS),
                         ("checkpointSamples", MAX_CHECKPOINT_SAMPLES)):
        rows = value.get(key)
        if not isinstance(rows, list) or len(rows) > maximum:
            return False
        if any(not isinstance(row, dict) for row in rows):
            return False
    if not isinstance(value.get("dailyDistributions"), dict) or len(
            value.get("dailyDistributions") or {}) > MAX_DAILY_DISTRIBUTIONS:
        return False
    top_keys = {
        "schemaVersion", "authoritative", "coverage", "createdAt",
        "updatedAt", "retentionDays", "bucketMinutes",
        "acceptanceClockStarted", "buckets", "dailyDistributions",
        "recentMutations", "checkpointSamples", "measurementErrors"}
    if not set(value) <= top_keys:
        return False
    known_mutations = set(argus_recovery_registry.mutation_by_class())
    known_coverage = {row.value for row in argus_recovery_registry.WalCoverage}
    safe_state_ids = {row.stateId for row in argus_recovery_registry.states()
                      if row.allowedInTelemetry}
    histogram_keys = {str(value) for value in _HISTOGRAM_UPPER_BOUNDS}

    def valid_histogram(histogram: Any) -> bool:
        return isinstance(histogram, dict) and \
            set(histogram) <= histogram_keys and all(
                isinstance(count, int) and not isinstance(count, bool) and
                count >= 0 for count in histogram.values())
    recent_keys = {
        "observedAt", "mutationClass", "targetStateIds",
        "redactedTargetCount", "plaintextBytesEstimate",
        "candidateRecordPlaintextBytesEstimate", "transitionCount",
        "recordCount", "latencyMs", "success", "currentWalCoverage",
        "localSequence"}
    for row in value.get("recentMutations") or []:
        if not set(row) <= recent_keys or row.get("mutationClass") not in \
                known_mutations or row.get("currentWalCoverage") not in \
                known_coverage or not isinstance(row.get("targetStateIds"), list) \
                or not set(row.get("targetStateIds") or []) <= safe_state_ids or \
                _parse_iso(row.get("observedAt")) is None:
            return False
    bucket_keys = {
        "bucketStart", "mutationCount", "transitionCount", "recordCount",
        "successCount", "failureCount", "plaintextBytesEstimate",
        "candidateRecordPlaintextBytesEstimate",
        "maxSingleMutationPlaintextBytesEstimate", "byMutationClass",
        "byWalCoverage"}
    for row in value.get("buckets") or []:
        by_class = row.get("byMutationClass")
        by_coverage = row.get("byWalCoverage")
        if not set(row) <= bucket_keys or not isinstance(by_class, dict) or \
                not isinstance(by_coverage, dict) or \
                not set(by_class) <= known_mutations or \
                not set(by_coverage) <= known_coverage or any(
                    not isinstance(count, int) or isinstance(count, bool) or
                    count < 0 for count in by_class.values()):
            return False
        if _parse_iso(row.get("bucketStart")) is None:
            return False
    distribution_keys = {
        "mutationCount", "plaintextBytesEstimate",
        "candidateRecordPlaintextBytesEstimate",
        "maxSingleMutationPlaintextBytesEstimate", "plaintextBytesHistogram",
        "latencyMsHistogram"}
    for day, daily in value["dailyDistributions"].items():
        try:
            dt.date.fromisoformat(str(day))
        except ValueError:
            return False
        if not isinstance(daily, dict) or not set(daily) <= known_mutations or any(
                not isinstance(row, dict) or not set(row) <= distribution_keys or
                not valid_histogram(row.get("plaintextBytesHistogram") or {}) or
                not valid_histogram(row.get("latencyMsHistogram") or {})
                for row in daily.values()):
            return False
    checkpoint_keys = {
        "observedAt", "success", "checkpointSerializedBytes",
        "sectionSerializedBytes", "dominantSectionSerializedBytes",
        "sourceAssemblyMs", "sectionAccountingMs", "sealMs",
        "atomicWriteFsyncReadbackMs", "peakRssBytes", "localWalBytes",
        "localWalRecordCount", "localWalHighWater",
        "legacyRemoteAckSequence", "legacyRemoteAckAt",
        "legacyRemoteAckIsExactWalDurability", "legacyPredictionsJsonl"}
    allowed_sections = {key for row in argus_recovery_registry.states()
                        for key in row.checkpointKeys}
    prediction_keys = {"configured", "exists", "bytes", "recordCount",
                       "complete"}
    for row in value.get("checkpointSamples") or []:
        sections = row.get("sectionSerializedBytes")
        dominant = row.get("dominantSectionSerializedBytes")
        predictions = row.get("legacyPredictionsJsonl")
        if not set(row) <= checkpoint_keys or not isinstance(sections, dict) or \
                not set(sections) <= allowed_sections or \
                not isinstance(dominant, dict) or \
                not set(dominant) <= set(LARGE_SECTION_KEYS) or \
                not isinstance(predictions, dict) or \
                not set(predictions) <= prediction_keys or \
                _parse_iso(row.get("observedAt")) is None:
            return False
    # The persisted schema has no place for content-bearing keys.
    forbidden = {"payload", "prompt", "url", "holdings", "sourceText",
                 "modelOutput", "research", "plaintext", "secret"}
    stack: List[Any] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if any(str(key).lower() in {item.lower() for item in forbidden}
                   for key in current):
                return False
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        elif not isinstance(current, (str, int, float, bool, type(None))):
            return False
    return True


def _bucket_start(value: dt.datetime, minutes: int = BUCKET_MINUTES) -> dt.datetime:
    epoch = int(value.timestamp())
    width = int(minutes) * 60
    return dt.datetime.fromtimestamp(epoch - epoch % width, tz=UTC)


def _new_bucket(start: dt.datetime) -> Dict[str, Any]:
    return {
        "bucketStart": _iso(start),
        "mutationCount": 0,
        "transitionCount": 0,
        "recordCount": 0,
        "successCount": 0,
        "failureCount": 0,
        "plaintextBytesEstimate": 0,
        "candidateRecordPlaintextBytesEstimate": 0,
        "maxSingleMutationPlaintextBytesEstimate": 0,
        "byMutationClass": {},
        "byWalCoverage": {},
    }


def _rollup_buckets(buckets: Iterable[Mapping[str, Any]], minutes: int
                    ) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for bucket in buckets:
        parsed = _parse_iso(bucket.get("bucketStart"))
        if parsed is None:
            continue
        key = _iso(_bucket_start(parsed, minutes))
        row = rows.setdefault(key, {
            "intervalStart": key, "mutationCount": 0, "transitionCount": 0,
            "recordCount": 0, "successCount": 0, "failureCount": 0,
            "plaintextBytesEstimate": 0,
            "candidateSegmentPlaintextBytesEstimate": 0,
            "maxSingleMutationPlaintextBytesEstimate": 0,
            "byMutationClass": {},
        })
        for field in ("mutationCount", "transitionCount", "recordCount",
                      "successCount", "failureCount", "plaintextBytesEstimate"):
            row[field] += int(bucket.get(field) or 0)
        row["candidateSegmentPlaintextBytesEstimate"] += int(
            bucket.get("candidateRecordPlaintextBytesEstimate") or 0)
        row["maxSingleMutationPlaintextBytesEstimate"] = max(
            row["maxSingleMutationPlaintextBytesEstimate"],
            int(bucket.get("maxSingleMutationPlaintextBytesEstimate") or 0))
        for mutation_class, count in (
                bucket.get("byMutationClass") or {}).items():
            row["byMutationClass"][mutation_class] = int(
                row["byMutationClass"].get(mutation_class) or 0) + int(
                    count or 0)
    return [rows[key] for key in sorted(rows)]


def _numeric_summary(values: Iterable[int]) -> Dict[str, Optional[int]]:
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return {"p50": None, "p95": None, "p99": None, "max": None}

    def at(q: float) -> int:
        return ordered[max(0, int(math.ceil(len(ordered) * q)) - 1)]
    return {"p50": at(.50), "p95": at(.95), "p99": at(.99),
            "max": ordered[-1]}


def _interval_statistics(buckets: Iterable[Mapping[str, Any]], minutes: int
                         ) -> Dict[str, Any]:
    rows = _rollup_buckets(buckets, minutes)
    return {
        "intervalMinutes": minutes,
        "intervalCount": len(rows),
        "mutationCount": _numeric_summary(row["mutationCount"] for row in rows),
        "plaintextBytesEstimate": _numeric_summary(
            row["plaintextBytesEstimate"] for row in rows),
        "recordCount": _numeric_summary(row["recordCount"] for row in rows),
        "candidateSegmentPlaintextBytesEstimate": _numeric_summary(
            row["candidateSegmentPlaintextBytesEstimate"] for row in rows),
        "latest": rows[-1] if rows else None,
        "encryptedBytesClaimed": False,
    }


def exact_cold_recovery_diagnostic(*, checkpoint_mode: str,
                                   legacy_remote_status: str,
                                   encrypted_sidecar_status: str,
                                   stage1_state: str,
                                   mutation_coverage_complete: bool = False,
                                   exact_full_generation_verified: bool = False,
                                   exact_wal_tail_verified: bool = False,
                                   exact_authority_manifest_verified: bool = False
                                   ) -> Dict[str, Any]:
    exact_inputs = (mutation_coverage_complete,
                    exact_full_generation_verified,
                    exact_wal_tail_verified,
                    exact_authority_manifest_verified)
    # A legacy-only selector cannot become exact merely because scalar booleans
    # were accidentally supplied by a caller.
    proven = all(exact_inputs) and checkpoint_mode != "legacy_only"
    any_shadow = any(exact_inputs)
    status = "proven" if proven else ("shadow" if any_shadow else "not_proven")
    reasons = []
    if checkpoint_mode == "legacy_only":
        reasons.append("legacy_checkpoint_mode")
    if encrypted_sidecar_status in ("not_configured", "not_issued", "absent", ""):
        reasons.append("encrypted_sidecar_not_current_authority")
    if not mutation_coverage_complete:
        reasons.append("authoritative_mutation_coverage_incomplete")
    if not exact_full_generation_verified:
        reasons.append("exact_full_generation_not_verified")
    if not exact_wal_tail_verified:
        reasons.append("exact_remote_wal_tail_not_verified")
    if not exact_authority_manifest_verified:
        reasons.append("exact_authority_manifest_not_verified")
    return {
        "status": status,
        "authoritative": False,
        "legacyRemoteHealth": legacy_remote_status or "unknown",
        "legacyRemoteHealthIsExactColdRecoveryProof": False,
        "checkpointMode": checkpoint_mode or "unknown",
        "encryptedSidecarStatus": encrypted_sidecar_status or "unknown",
        "stage1State": stage1_state or "unknown",
        "mutationCoverage": ("complete" if mutation_coverage_complete
                             else "incomplete"),
        "hardRpoClaimPermitted": bool(proven),
        "reasonCodes": sorted(set(reasons)),
    }


class RecoveryMeasurementStore:
    """Thread-safe bounded aggregator with optional atomic local persistence."""

    def __init__(self, path: Optional[str], *,
                 clock: Callable[[], dt.datetime] = _utc_now):
        self.path = os.path.abspath(path) if path else None
        self.clock = clock
        self._lock = threading.Lock()
        self._document: Optional[Dict[str, Any]] = None
        self._load_status = "not_loaded"
        self._last_persist_monotonic = 0.0

    def _ensure_loaded(self) -> None:
        if self._document is not None:
            return
        now = self.clock()
        self._document = _empty_document(now)
        if not self.path:
            self._load_status = "disabled"
            return
        try:
            if os.path.islink(self.path):
                self._load_status = "invalid_symlink"
                return
            if not os.path.exists(self.path):
                self._load_status = "not_found"
                return
            if os.path.getsize(self.path) > MAX_PERSISTED_BYTES:
                self._load_status = "invalid_oversized"
                return
            with open(self.path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not _validate_document(loaded):
                self._load_status = "invalid_schema"
                return
            self._document = loaded
            self._load_status = "loaded"
            self._prune(now)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            self._load_status = "invalid_or_partial"

    def _prune(self, now: dt.datetime) -> None:
        assert self._document is not None
        cutoff = now.astimezone(UTC) - dt.timedelta(days=RETENTION_DAYS)
        self._document["buckets"] = [
            row for row in self._document.get("buckets") or []
            if (_parse_iso(row.get("bucketStart")) or dt.datetime.min.replace(
                tzinfo=UTC)) >= cutoff][-MAX_BUCKETS:]
        self._document["recentMutations"] = [
            row for row in self._document.get("recentMutations") or []
            if (_parse_iso(row.get("observedAt")) or dt.datetime.min.replace(
                tzinfo=UTC)) >= cutoff][-MAX_RECENT_MUTATIONS:]
        self._document["checkpointSamples"] = [
            row for row in self._document.get("checkpointSamples") or []
            if (_parse_iso(row.get("observedAt")) or dt.datetime.min.replace(
                tzinfo=UTC)) >= cutoff][-MAX_CHECKPOINT_SAMPLES:]
        cutoff_day = cutoff.date().isoformat()
        daily = self._document.get("dailyDistributions") or {}
        self._document["dailyDistributions"] = {
            key: daily[key] for key in sorted(daily)
            if key >= cutoff_day}
        if len(self._document["dailyDistributions"]) > \
                MAX_DAILY_DISTRIBUTIONS:
            keys = sorted(self._document["dailyDistributions"])[
                -MAX_DAILY_DISTRIBUTIONS:]
            self._document["dailyDistributions"] = {
                key: self._document["dailyDistributions"][key] for key in keys}
        self._document["updatedAt"] = _iso(now)

    def _note_error(self) -> None:
        if self._document is not None:
            self._document["measurementErrors"] = int(
                self._document.get("measurementErrors") or 0) + 1

    def record_mutation(self, mutation_class: str, *,
                        plaintext_bytes_estimate: int,
                        transition_count: int = 1,
                        record_count: int = 1,
                        latency_ms: float = 0.0,
                        success: bool = True,
                        observed_at: Optional[dt.datetime] = None,
                        local_sequence: Optional[int] = None) -> bool:
        """Record metadata only; unknown classes fail loud to the caller."""
        definition = argus_recovery_registry.mutation_by_class().get(
            str(mutation_class))
        if definition is None:
            raise ValueError("unregistered_mutation_class")
        size = max(0, int(plaintext_bytes_estimate))
        transitions = max(0, int(transition_count))
        records = max(0, int(record_count))
        latency = max(0.0, float(latency_ms))
        observed = observed_at or self.clock()
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        candidate = size + records * FUTURE_RECORD_FRAMING_ESTIMATE_BYTES
        state_index = argus_recovery_registry.state_by_id()
        safe_targets = [target for target in definition.targetStateIds
                        if state_index[target].allowedInTelemetry]
        redacted_targets = len(definition.targetStateIds) - len(safe_targets)
        with self._lock:
            self._ensure_loaded()
            assert self._document is not None
            self._prune(observed)
            start = _bucket_start(observed)
            key = _iso(start)
            buckets = self._document["buckets"]
            bucket = next((row for row in reversed(buckets)
                           if row.get("bucketStart") == key), None)
            if bucket is None:
                bucket = _new_bucket(start)
                buckets.append(bucket)
                buckets.sort(key=lambda row: str(row.get("bucketStart") or ""))
                self._document["buckets"] = buckets[-MAX_BUCKETS:]
            bucket["mutationCount"] += 1
            bucket["transitionCount"] += transitions
            bucket["recordCount"] += records
            bucket["successCount" if success else "failureCount"] += 1
            bucket["plaintextBytesEstimate"] += size
            bucket["candidateRecordPlaintextBytesEstimate"] += candidate
            bucket["maxSingleMutationPlaintextBytesEstimate"] = max(
                bucket["maxSingleMutationPlaintextBytesEstimate"], size)
            bucket["byMutationClass"][definition.mutationClass] = int(
                bucket["byMutationClass"].get(definition.mutationClass) or 0) + 1
            coverage = definition.currentWalCoverage.value
            bucket["byWalCoverage"][coverage] = int(
                bucket["byWalCoverage"].get(coverage) or 0) + 1
            day = observed.astimezone(UTC).date().isoformat()
            distribution = self._document["dailyDistributions"].setdefault(
                day, {}).setdefault(definition.mutationClass, _new_distribution())
            distribution["mutationCount"] += 1
            distribution["plaintextBytesEstimate"] += size
            distribution["candidateRecordPlaintextBytesEstimate"] += candidate
            distribution["maxSingleMutationPlaintextBytesEstimate"] = max(
                distribution["maxSingleMutationPlaintextBytesEstimate"], size)
            _histogram_add(distribution["plaintextBytesHistogram"], size)
            _histogram_add(distribution["latencyMsHistogram"], latency)
            recent = {
                "observedAt": _iso(observed),
                "mutationClass": definition.mutationClass,
                "targetStateIds": safe_targets,
                "redactedTargetCount": redacted_targets,
                "plaintextBytesEstimate": size,
                "candidateRecordPlaintextBytesEstimate": candidate,
                "transitionCount": transitions,
                "recordCount": records,
                "latencyMs": round(latency, 3),
                "success": bool(success),
                "currentWalCoverage": coverage,
            }
            if local_sequence is not None:
                recent["localSequence"] = max(0, int(local_sequence))
            self._document["recentMutations"].append(recent)
            self._document["recentMutations"].sort(
                key=lambda row: str(row.get("observedAt") or ""))
            self._document["recentMutations"] = self._document[
                "recentMutations"][-MAX_RECENT_MUTATIONS:]
            self._document["updatedAt"] = _iso(observed)
        # Hot mutations update memory only. Persistence is forced by the
        # already-existing checkpoint boundary; diagnostics never add WAL-path
        # fsync latency per record.
        return True

    def record_checkpoint(self, *, checkpoint_bytes: int,
                          section_sizes: Mapping[str, int],
                          source_assembly_ms: float,
                          section_accounting_ms: float,
                          seal_ms: float,
                          atomic_write_readback_ms: float,
                          local_wal_bytes: int,
                          local_wal_record_count: int,
                          local_wal_high_water: int,
                          legacy_remote_ack_sequence: int,
                          legacy_remote_ack_at: Optional[str],
                          legacy_predictions: Mapping[str, Any],
                          success: bool = True,
                          observed_at: Optional[dt.datetime] = None) -> bool:
        observed = observed_at or self.clock()
        allowed_sections = {key for row in argus_recovery_registry.states()
                            for key in row.checkpointKeys}
        parsed_ack_at = _parse_iso(legacy_remote_ack_at)
        sample = {
            "observedAt": _iso(observed), "success": bool(success),
            "checkpointSerializedBytes": max(0, int(checkpoint_bytes)),
            "sectionSerializedBytes": {
                str(key): max(0, int(value))
                for key, value in sorted(section_sizes.items())
                if str(key) in allowed_sections},
            "dominantSectionSerializedBytes": {
                key: max(0, int(section_sizes.get(key) or 0))
                for key in LARGE_SECTION_KEYS},
            "sourceAssemblyMs": round(max(0.0, float(source_assembly_ms)), 3),
            "sectionAccountingMs": round(max(0.0, float(section_accounting_ms)), 3),
            "sealMs": round(max(0.0, float(seal_ms)), 3),
            # Existing writer combines stream serialization, file flush/fsync,
            # hash readback, replace and parent fsync; do not invent a split.
            "atomicWriteFsyncReadbackMs": round(
                max(0.0, float(atomic_write_readback_ms)), 3),
            "peakRssBytes": peak_rss_bytes(),
            "localWalBytes": max(0, int(local_wal_bytes)),
            "localWalRecordCount": max(0, int(local_wal_record_count)),
            "localWalHighWater": max(0, int(local_wal_high_water)),
            "legacyRemoteAckSequence": max(0, int(legacy_remote_ack_sequence)),
            "legacyRemoteAckAt": (_iso(parsed_ack_at)
                                  if parsed_ack_at is not None else None),
            "legacyRemoteAckIsExactWalDurability": False,
            "legacyPredictionsJsonl": {
                "configured": bool(legacy_predictions.get("configured")),
                "exists": bool(legacy_predictions.get("exists")),
                "bytes": max(0, int(legacy_predictions.get("bytes") or 0)),
                "recordCount": max(0, int(
                    legacy_predictions.get("recordCount") or 0)),
                "complete": bool(legacy_predictions.get("complete")),
            },
        }
        with self._lock:
            self._ensure_loaded()
            assert self._document is not None
            self._prune(observed)
            self._document["checkpointSamples"].append(sample)
            self._document["checkpointSamples"].sort(
                key=lambda row: str(row.get("observedAt") or ""))
            self._document["checkpointSamples"] = self._document[
                "checkpointSamples"][-MAX_CHECKPOINT_SAMPLES:]
            self._document["updatedAt"] = _iso(observed)
        self.maybe_persist(force=True)
        return True

    def _bounded_snapshot(self) -> Dict[str, Any]:
        assert self._document is not None
        snapshot = json.loads(json.dumps(self._document, ensure_ascii=False))
        # Size is an independent cap in addition to time/count retention.  Drop
        # oldest observations only; aggregates remain bounded by registry size.
        while _canonical_size(snapshot) > MAX_PERSISTED_BYTES:
            if snapshot.get("recentMutations"):
                snapshot["recentMutations"] = snapshot["recentMutations"][1:]
            elif snapshot.get("checkpointSamples"):
                snapshot["checkpointSamples"] = snapshot["checkpointSamples"][1:]
            elif snapshot.get("buckets"):
                snapshot["buckets"] = snapshot["buckets"][1:]
            else:
                raise ValueError("measurement_document_exceeds_bound")
        return snapshot

    def maybe_persist(self, *, force: bool = False) -> bool:
        if not self.path:
            return False
        now_mono = time.monotonic()
        if not force and now_mono - self._last_persist_monotonic < \
                PERSIST_INTERVAL_SECONDS:
            return False
        with self._lock:
            self._ensure_loaded()
            assert self._document is not None
            try:
                snapshot = self._bounded_snapshot()
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                argus_persistent_storage.atomic_write_json(
                    self.path, snapshot,
                    temp_directory=os.path.dirname(self.path),
                    validator=_validate_document,
                    maximum_bytes=MAX_PERSISTED_BYTES,
                    file_mode=0o600,
                    temp_label="recovery-measurement")
                self._last_persist_monotonic = now_mono
                self._load_status = "persisted"
                return True
            except Exception:
                self._note_error()
                self._load_status = "persist_failed"
                return False

    def summary(self, *, legacy_remote_ack_at: Optional[str] = None,
                legacy_remote_ack_sequence: int = 0,
                local_wal_high_water: int = 0) -> Dict[str, Any]:
        now = self.clock()
        with self._lock:
            self._ensure_loaded()
            assert self._document is not None
            self._prune(now)
            buckets = list(self._document["buckets"])
            raw_distributions: Dict[str, Dict[str, Any]] = {}
            mutation_index = argus_recovery_registry.mutation_by_class()
            for daily in self._document["dailyDistributions"].values():
                for key, value in sorted(daily.items()):
                    definition = mutation_index[key]
                    public_key = ("private.redacted" if
                                  definition.payloadTelemetryPolicy ==
                                  argus_recovery_registry.PayloadTelemetryPolicy.FORBIDDEN
                                  else key)
                    _merge_distribution(
                        raw_distributions.setdefault(
                            public_key, _new_distribution()), value)
            distributions = {}
            for key, value in sorted(raw_distributions.items()):
                definition = mutation_index.get(key)
                distributions[key] = {
                    **_distribution_summary(value),
                    "currentWalCoverage": (
                        definition.currentWalCoverage.value
                        if definition is not None else "REDACTED_MIXED"),
                    "exactReplayPayloadCoverageObserved": bool(
                        definition is not None and
                        definition.currentWalCoverage ==
                        argus_recovery_registry.WalCoverage.COMPLETE),
                }
            recent = list(self._document["recentMutations"])
            checkpoints = list(self._document["checkpointSamples"])
            load_status = self._load_status
            errors = int(self._document.get("measurementErrors") or 0)
        latest_mutation_at = recent[-1].get("observedAt") if recent else None
        ack_time = _parse_iso(legacy_remote_ack_at)
        oldest_after_ack = None
        for row in buckets:
            bucket_at = _parse_iso(row.get("bucketStart"))
            if int(row.get("mutationCount") or 0) and bucket_at is not None and \
                    (ack_time is None or bucket_at > ack_time):
                oldest_after_ack = bucket_at
                break
        age_seconds = None
        if oldest_after_ack is not None:
            age_seconds = max(0, int((now.astimezone(UTC) -
                                      oldest_after_ack).total_seconds()))
        return {
            "schemaVersion": SCHEMA,
            "status": "SHADOW",
            "coverage": "INCOMPLETE",
            "authoritative": False,
            "hardRpoClaim": None,
            "hardRpoClaimPermitted": False,
            "latestObservedLocalMutationAt": latest_mutation_at,
            "oldestObservedAuthoritativeMutationAgeSeconds": age_seconds,
            "oldestAgeIsBucketApproximation": True,
            "latestLegacyRemoteAckAt": legacy_remote_ack_at,
            "legacyRemoteAckSequence": max(0, int(legacy_remote_ack_sequence)),
            "localWalHighWater": max(0, int(local_wal_high_water)),
            "legacySequenceLag": max(
                0, int(local_wal_high_water) - int(legacy_remote_ack_sequence)),
            "legacyRemoteAckIsExactWalDurability": False,
            "retentionDays": RETENTION_DAYS,
            "acceptanceClockStarted": False,
            "loadStatus": load_status,
            "measurementErrors": errors,
            "intervalStatistics": {
                str(minutes): _interval_statistics(buckets, minutes)
                for minutes in (5, 15, 30)},
            "mutationDistributions": distributions,
            "latestCheckpointMeasurement": checkpoints[-1] if checkpoints else None,
            "candidateWalEstimatesArePlaintextOnly": True,
            "candidateWalEstimateCoverage": "INCOMPLETE",
            "encryptedWalBytesClaimed": False,
        }


__all__ = [
    "RecoveryMeasurementStore", "checkpoint_section_sizes",
    "exact_cold_recovery_diagnostic", "measure_jsonl_metadata",
    "peak_rss_bytes", "serialized_size_estimate", "SCHEMA",
]

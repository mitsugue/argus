#!/usr/bin/env python3
"""Bounded resource proof for the Round 2 research compute plane.

The probe builds the same deterministic, point-in-time research artifact twice
from a small synthetic fixture.  It never reads a provider, credentials, owner
state, the environment, or the wall clock.  CI can require the exact cgroup-v2
contract: 4 GiB memory, no swap, peak below the limit, and no OOM event delta.

Only compact scalar receipts are written.  Raw OHLC rows and event details are
intentionally discarded after the canonical research artifact is verified.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import date, timedelta
from typing import Any, Dict, Iterable, Mapping, Optional


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_research_compute as research  # noqa: E402


REPORT_SCHEMA = "argus-round2-macro-resource-proof-v1"
FIXTURE_VERSION = "round2-bounded-pit-research-fixture-v1"
EXACT_4_GIB_BYTES = 4 * 1024 * 1024 * 1024
PROOF_CAP_BYTES = 16 * 1024
CGROUP_ROOT = pathlib.Path("/sys/fs/cgroup")


def _ranges() -> list[Dict[str, str]]:
    return [
        {"name": "DEVELOPMENT", "startDate": "2026-01-01",
         "endDate": "2026-04-30"},
        {"name": "EMBARGO", "startDate": "2026-05-01",
         "endDate": "2026-05-20"},
        {"name": "HOLDOUT", "startDate": "2026-05-21",
         "endDate": "2026-06-20"},
        {"name": "EMBARGO", "startDate": "2026-06-21",
         "endDate": "2026-07-20"},
        {"name": "GOLDEN", "startDate": "2026-07-21",
         "endDate": "2026-08-31"},
    ]


def _manifest(*, bar_sha256: Optional[str] = None,
              event_sha256: Optional[str] = None) -> Dict[str, Any]:
    if bar_sha256 is None:
        bar_sha256 = research.sha256_hex(research.canonical_bytes(_bars()))
    if event_sha256 is None:
        event_sha256 = research.sha256_hex(research.canonical_bytes(_events()))
    draft = {
        "schemaVersion": research.MANIFEST_SCHEMA,
        "researchId": "round2-ci-bounded-resource-v1",
        "datasetVersion": FIXTURE_VERSION,
        "datasets": [
            {"datasetId": "round2-probe-bars-v1", "kind": "bars",
             "partitionScope": "NON_GOLDEN",
             "path": "synthetic-bars.json", "sha256": bar_sha256,
             "sourceKind": "synthetic", "rightsStatus": "TEST_ONLY"},
            {"datasetId": "round2-probe-events-v1", "kind": "events",
             "partitionScope": "NON_GOLDEN",
             "path": "synthetic-events.json", "sha256": event_sha256,
             "sourceKind": "synthetic", "rightsStatus": "TEST_ONLY"},
        ],
        "informationCutoffAt": "2026-09-01T00:00:00Z",
        "pitPolicyId": research.PIT_POLICY_ID,
        "propositionRegistryVersion": "sho-jp-canonical-round2-v1",
        "policyVersion": "round2-resource-policy-v1",
        "parameterVersion": "round2-resource-parameters-v1",
        "buildSha": "c" * 40,
        "calendarVersion": "synthetic-daily-calendar-v1",
        "adjustmentPolicy": "split-adjusted-synthetic-v1",
        "executionPolicy": "next_session_open",
        "costBps": 5.0,
        "slippageBps": 5.0,
        "seed": 17,
        "horizons": [1, 5, 10, 20],
        "horizon40Preregistered": False,
        "horizon40PreregistrationId": None,
        "partitionPolicy": {
            "schemaVersion": research.PARTITION_POLICY_SCHEMA,
            "policyId": "round2-fixed-date-partitions-v1",
            "embargoSessions": 20,
            "ranges": _ranges(),
            "walkForwardFolds": [{
                "foldId": "wf-1",
                "trainStartDate": "2026-01-01",
                "trainEndDate": "2026-02-15",
                "validationStartDate": "2026-02-16",
                "validationEndDate": "2026-03-15",
                "forwardStartDate": "2026-03-16",
                "forwardEndDate": "2026-04-15",
            }],
        },
        "goldenPolicy": {
            "caseId": "jp-late-july-august-2026-reversal-v1",
            "expectedEventId": "golden-reversal",
            "expectedInstrumentId": "JP:1321:ETF",
            "access": "SEALED",
            "openedAt": None,
            "openedForPolicyIdentity": None,
            "openedForResearchDataIdentity": None,
        },
        "freeze": {
            "status": "DRAFT", "policyIdentity": None, "frozenAt": None,
            "holdoutStatus": "UNTOUCHED", "holdoutResultDigest": None,
            "holdoutRecordedAt": None, "researchDataIdentity": None,
        },
        "retune": {"priorPolicyIdentity": None, "reason": None},
        "parameters": {
            "targetPct": 3.0,
            "invalidationPct": -3.0,
            "newLowLookback": 20,
            "rallyThresholdPct": 3.0,
            "reversalThresholdPct": 2.0,
            "waitFailureThresholdPct": 3.0,
            "counterfactualHorizon": 20,
            "turtle": {
                "entryLookbacks": [20, 55],
                "exitLookbacks": [10, 20],
                "atrPeriod": 20,
                "entryRule": "20_or_55_day_high_break",
                "exitRule": "10_or_20_day_low_break",
                "shadowOnly": True,
                "hardVeto": False,
            },
        },
    }
    return research.freeze_manifest(
        draft, frozen_at="2026-05-01T00:00:00Z")


def _bars() -> list[Dict[str, Any]]:
    first = date(2026, 1, 1)
    last = date(2026, 7, 20)
    result = []
    day = first
    index = 0
    while day <= last:
        trend = 100.0 + index * 0.22
        close = trend + (-4.0 if index and index % 37 == 0 else 0.0)
        signals: Dict[str, bool] = {}
        for period, name in (
            (29, "shoReversal"),
            (31, "vixDecreasingConfirmation"),
            (41, "sarFlip"),
            (43, "macdGoldenCross"),
            (47, "ma25Reclaim"),
        ):
            if index % period == period % 7:
                signals[name] = True
        result.append({
            "datasetId": "round2-probe-bars-v1",
            "instrumentId": "JP:1321:ETF",
            "date": day.isoformat(),
            "availableFrom": day.isoformat() + "T20:00:00Z",
            "decisionCutoffAt": day.isoformat() + "T20:30:00Z",
            "revision": 0,
            "sourceId": "round2-probe:" + day.isoformat(),
            "open": close - 0.2,
            "high": close + 1.2,
            "low": close - 1.1,
            "close": close,
            "volume": 1_000 + index,
            "signals": signals,
        })
        day += timedelta(days=1)
        index += 1
    return result


def _events() -> list[Dict[str, Any]]:
    rows = (
        ("dev-validation", "2026-03-01", "calm", ["credit"]),
        ("dev-forward", "2026-03-20", "risk_off", ["vix", "credit"]),
        ("holdout-one", "2026-05-25", "risk_off", ["credit"]),
    )
    return [{
        "datasetId": "round2-probe-events-v1",
        "eventId": event_id,
        "instrumentId": "JP:1321:ETF",
        "signalDate": day,
        "availableFrom": day + "T20:30:00Z",
        "decisionCutoffAt": day + "T20:30:00Z",
        "expectedDirection": "UP",
        "probability": 0.65,
        "targetPct": 3.0,
        "invalidationPct": -3.0,
        "regime": regime,
        "ablationTags": tags,
        "validatedReversal": True,
        "evidenceRefs": ["round2-probe:" + event_id],
    } for event_id, day, regime, tags in rows]


def _read_scalar(name: str) -> Optional[int]:
    try:
        raw = (CGROUP_ROOT / name).read_text(encoding="ascii").strip()
        return None if raw == "max" else int(raw)
    except (FileNotFoundError, OSError, PermissionError, UnicodeError,
            ValueError):
        return None


def _memory_events() -> Dict[str, Optional[int]]:
    values: Dict[str, int] = {}
    try:
        lines = (CGROUP_ROOT / "memory.events").read_text(
            encoding="ascii").splitlines()
    except (FileNotFoundError, OSError, PermissionError, UnicodeError):
        lines = []
    for line in lines:
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            values[fields[0]] = int(fields[1])
        except ValueError:
            continue
    return {"oom": values.get("oom"), "oomKill": values.get("oom_kill")}


def _snapshot() -> Dict[str, Any]:
    return {
        "memoryMaxBytes": _read_scalar("memory.max"),
        "memoryPeakBytes": _read_scalar("memory.peak"),
        "swapMaxBytes": _read_scalar("memory.swap.max"),
        "events": _memory_events(),
    }


def _delta(before: Mapping[str, Any], after: Mapping[str, Any],
           name: str) -> Optional[int]:
    left = (before.get("events") or {}).get(name)
    right = (after.get("events") or {}).get(name)
    return right - left if isinstance(left, int) and isinstance(right, int) \
        else None


def _contains_raw_ohlc(value: Any) -> bool:
    if isinstance(value, dict):
        if {"open", "high", "low", "close"}.issubset(value):
            return True
        return any(_contains_raw_ohlc(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_raw_ohlc(item) for item in value)
    return False


def _stabilized_payload(report: Dict[str, Any]) -> bytes:
    report["reportBytes"] = 0
    for _ in range(8):
        payload = research.canonical_bytes(report) + b"\n"
        size = len(payload)
        if report["reportBytes"] == size:
            return payload
        report["reportBytes"] = size
    raise RuntimeError("report_size_did_not_stabilize")


def build_report(*, require_exact_4g: bool) -> Dict[str, Any]:
    before = _snapshot()
    bars = _bars()
    events = _events()
    bar_payload = research.canonical_bytes(bars)
    event_payload = research.canonical_bytes(events)
    manifest = _manifest(
        bar_sha256=research.sha256_hex(bar_payload),
        event_sha256=research.sha256_hex(event_payload))
    dataset_payloads = {
        "round2-probe-bars-v1": bar_payload,
        "round2-probe-events-v1": event_payload,
    }
    first = research.build_verified_research_artifact(
        manifest, dataset_payloads)
    second = research.build_verified_research_artifact(
        manifest, dataset_payloads)
    after = _snapshot()

    artifact_bytes = len(research.canonical_bytes(first))
    event_details = first.get("eventDetails") or []
    counterfactual_details = (first.get("counterfactuals") or {}).get(
        "perEvent") or []
    turtle_details = (first.get("turtleShadow") or {}).get("signals") or []
    deterministic = first == second
    artifact_verified = research.verify_research_artifact(first)
    compact = all((
        artifact_bytes <= research.MAX_ARTIFACT_BYTES,
        len(event_details) <= research.MAX_EVENT_DETAILS,
        len(counterfactual_details) <= research.MAX_EVENT_DETAILS,
        len(turtle_details) <= research.MAX_TURTLE_SIGNAL_DETAILS,
        not _contains_raw_ohlc(first),
        (first.get("counterfactuals") or {}).get("ownerPnl") is False,
    ))

    memory_max = after.get("memoryMaxBytes")
    swap_max = after.get("swapMaxBytes")
    memory_peak = after.get("memoryPeakBytes")
    oom_delta = _delta(before, after, "oom")
    oom_kill_delta = _delta(before, after, "oomKill")
    exact_cgroup = all((
        memory_max == EXACT_4_GIB_BYTES,
        swap_max == 0,
        isinstance(memory_peak, int),
        isinstance(memory_max, int) and isinstance(memory_peak, int)
        and memory_peak < memory_max,
        oom_delta == 0,
        oom_kill_delta == 0,
    ))
    cgroup_passed = exact_cgroup if require_exact_4g else True
    workload_digest = research.sha256_hex({
        "artifactDigest": first["artifactDigest"],
        "artifactBytes": artifact_bytes,
        "barCount": len(bars),
        "eventCount": len(events),
        "fixtureVersion": FIXTURE_VERSION,
    })

    report = {
        "schemaVersion": REPORT_SCHEMA,
        "fixtureVersion": FIXTURE_VERSION,
        "mode": "bounded",
        "researchIdentity": first["identity"]["researchIdentity"],
        "inputIdentity": first["identity"]["inputIdentity"],
        "artifactId": first["artifactId"],
        "artifactDigest": first["artifactDigest"],
        "workloadDigest": workload_digest,
        "barCount": len(bars),
        "eventCount": len(events),
        "artifactBytes": artifact_bytes,
        "artifactCapBytes": research.MAX_ARTIFACT_BYTES,
        "eventDetailCount": len(event_details),
        "eventDetailCap": research.MAX_EVENT_DETAILS,
        "counterfactualDetailCount": len(counterfactual_details),
        "counterfactualDetailCap": research.MAX_EVENT_DETAILS,
        "turtleSignalDetailCount": len(turtle_details),
        "turtleSignalDetailCap": research.MAX_TURTLE_SIGNAL_DETAILS,
        "proofCapBytes": PROOF_CAP_BYTES,
        "deterministicRebuild": deterministic,
        "artifactVerified": artifact_verified,
        "rawOhlcRetained": _contains_raw_ohlc(first),
        "ownerPnlPresent": (
            (first.get("counterfactuals") or {}).get("ownerPnl") is not False),
        "cgroupRequired": bool(require_exact_4g),
        "cgroupEnforcementStatus": (
            "PASS" if require_exact_4g and exact_cgroup else
            "FAIL" if require_exact_4g else "SKIPPED_LOCAL"),
        "memoryMaxBytes": memory_max,
        "swapMaxBytes": swap_max,
        "memoryPeakBytes": memory_peak,
        "oomDelta": oom_delta,
        "oomKillDelta": oom_kill_delta,
        "passed": bool(deterministic and artifact_verified and compact
                       and cgroup_passed),
    }
    payload = _stabilized_payload(report)
    if len(payload) > PROOF_CAP_BYTES:
        report["passed"] = False
        _stabilized_payload(report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bounded Round 2 research resource proof")
    parser.add_argument("--require-exact-4g", action="store_true")
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Iterable[str] = None) -> int:
    args = _parser().parse_args(argv)
    report = build_report(require_exact_4g=args.require_exact_4g)
    payload = _stabilized_payload(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    if not args.quiet:
        sys.stdout.buffer.write(payload)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

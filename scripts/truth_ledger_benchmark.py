#!/usr/bin/env python3
"""Reproducible Market Truth + Prediction Ledger v2 resource benchmark.

Only synthetic, repository-representative facts are constructed.  The script
imports the canonical pure contracts directly; it never imports scanner, opens
a network connection, reads credentials, or calls a provider.

Local runs observe and report cgroup-v2 state without requiring it.  CI/resource
jobs can add ``--require-exact-4g`` to fail unless memory.max is exactly 4 GiB,
swap.max is zero, peak remains below the limit, and oom/oom_kill do not change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import resource
except ImportError:  # pragma: no cover - resource is Unix-only.
    resource = None  # type: ignore[assignment]


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_decision_ledger as decision_ledger
import argus_market_data_truth as market_truth


REPORT_SCHEMA = "argus-truth-ledger-benchmark-v1"
FIXTURE_VERSION = "repository-representative-truth-ledger-v1"
EXACT_4_GIB_BYTES = 4 * 1024 * 1024 * 1024
SMOKE_REQUEST_COUNT = 10
BOUNDED_REQUEST_COUNT = 32
BUILD_SHA = "b" * 40
DECISION_AT = "2026-08-14T20:00:00Z"
GENERATED_AT = DECISION_AT
CGROUP_ROOT = pathlib.Path("/sys/fs/cgroup")


_SCOPE_TEMPLATES: Tuple[Dict[str, Any], ...] = (
    {"market": "JP", "factType": "QUOTE", "assetType": "EQUITY",
     "currency": "JPY", "symbol": "7203", "base": 2800.0},
    {"market": "JP", "factType": "OHLCV_BAR", "assetType": "EQUITY",
     "currency": "JPY", "symbol": "6758", "base": 12000.0},
    {"market": "JP", "factType": "INDEX_PROXY", "assetType": "ETF_PROXY",
     "currency": "JPY", "symbol": "1321", "base": 41000.0},
    {"market": "JP", "factType": "NAV", "assetType": "FUND",
     "currency": "JPY", "symbol": "FUNDJP", "base": 18450.0},
    {"market": "US", "factType": "QUOTE", "assetType": "EQUITY",
     "currency": "USD", "symbol": "AAPL", "base": 230.0},
    {"market": "US", "factType": "OHLCV_BAR", "assetType": "EQUITY",
     "currency": "USD", "symbol": "NVDA", "base": 180.0},
    {"market": "US", "factType": "INDEX_PROXY", "assetType": "ETF_PROXY",
     "currency": "USD", "symbol": "QQQ", "base": 560.0},
    {"market": "FX", "factType": "QUOTE", "assetType": "FX_PAIR",
     "currency": "JPY", "symbol": "USDJPY", "base": 148.0},
    {"market": "FX", "factType": "RATE", "assetType": "RATE",
     "currency": None, "symbol": "DFF", "base": 4.25},
    {"market": "CRYPTO", "factType": "QUOTE", "assetType": "CRYPTO",
     "currency": "USD", "symbol": "BTC", "base": 118000.0},
)

_OBSERVED_AT = {
    "JP": "2026-08-14T06:00:00Z",
    "US": "2026-08-14T19:55:00Z",
    "FX": "2026-08-14T19:56:00Z",
    "CRYPTO": "2026-08-14T19:57:00Z",
}
_RECEIVED_AT = {
    "JP": "2026-08-14T06:00:10Z",
    "US": "2026-08-14T19:55:10Z",
    "FX": "2026-08-14T19:56:10Z",
    "CRYPTO": "2026-08-14T19:57:10Z",
}
_TARGET_TIMES = {
    "JP": ("2026-08-17T06:00:00Z", "2026-08-17T06:05:00Z"),
    "US": ("2026-08-17T20:00:00Z", "2026-08-17T20:05:00Z"),
    "FX": ("2026-08-17T20:00:00Z", "2026-08-17T20:05:00Z"),
    "CRYPTO": ("2026-08-17T20:00:00Z", "2026-08-17T20:05:00Z"),
}
_CALENDARS = {"JP": "XTKS", "US": "XNYS", "FX": "FX24H", "CRYPTO": "CRYPTO24H"}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _iso_after(value: str, seconds: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(seconds=seconds)).astimezone(timezone.utc) \
        .isoformat().replace("+00:00", "Z")


def _peak_rss_bytes() -> Optional[int]:
    if resource is None:
        return None
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (AttributeError, OSError, OverflowError, TypeError, ValueError):
        return None


def _read_cgroup_scalar(root: pathlib.Path, name: str) -> Optional[int]:
    try:
        text = (root / name).read_text(encoding="ascii").strip()
        return None if text == "max" else int(text)
    except (FileNotFoundError, OSError, PermissionError, UnicodeError, ValueError):
        return None


def _read_memory_events(root: pathlib.Path) -> Dict[str, Optional[int]]:
    values: Dict[str, int] = {}
    try:
        lines = (root / "memory.events").read_text(encoding="ascii").splitlines()
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


def cgroup_snapshot(root: pathlib.Path = CGROUP_ROOT) -> Dict[str, Any]:
    return {
        "available": (root / "memory.max").is_file(),
        "memoryCurrentBytes": _read_cgroup_scalar(root, "memory.current"),
        "memoryPeakBytes": _read_cgroup_scalar(root, "memory.peak"),
        "memoryMaxBytes": _read_cgroup_scalar(root, "memory.max"),
        "swapMaxBytes": _read_cgroup_scalar(root, "memory.swap.max"),
        "events": _read_memory_events(root),
    }


def cgroup_contract(
    before: Mapping[str, Any], after: Mapping[str, Any], *, required: bool,
) -> Dict[str, Any]:
    before_events = before.get("events") or {}
    after_events = after.get("events") or {}

    def delta(name: str) -> Optional[int]:
        left, right = before_events.get(name), after_events.get(name)
        return right - left if isinstance(left, int) and isinstance(right, int) else None

    oom_delta = delta("oom")
    oom_kill_delta = delta("oomKill")
    memory_max = after.get("memoryMaxBytes")
    swap_max = after.get("swapMaxBytes")
    memory_peak = after.get("memoryPeakBytes")
    reasons = []
    if memory_max != EXACT_4_GIB_BYTES:
        reasons.append("memory_max_not_exact_4gib")
    if swap_max != 0:
        reasons.append("swap_max_not_zero")
    if memory_peak is None:
        reasons.append("memory_peak_unavailable")
    elif isinstance(memory_max, int) and memory_peak >= memory_max:
        reasons.append("memory_peak_reached_limit")
    if oom_delta is None or oom_kill_delta is None:
        reasons.append("memory_events_unavailable")
    else:
        if oom_delta != 0:
            reasons.append("oom_changed")
        if oom_kill_delta != 0:
            reasons.append("oom_kill_changed")
    exact = not reasons
    return {
        "required": bool(required),
        "enforcementStatus": (
            "PASS" if required and exact else
            "FAIL" if required else
            "SKIPPED_LOCAL"
        ),
        "passed": exact if required else True,
        "observedExactContract": exact,
        "requiredMemoryMaxBytes": EXACT_4_GIB_BYTES,
        "requiredSwapMaxBytes": 0,
        "memoryMaxBytes": memory_max,
        "swapMaxBytes": swap_max,
        "memoryCurrentBytes": after.get("memoryCurrentBytes"),
        "memoryPeakBytes": memory_peak,
        "oomDelta": oom_delta,
        "oomKillDelta": oom_kill_delta,
        "failureReasons": reasons,
    }


def _scope(index: int) -> Dict[str, Any]:
    template = dict(_SCOPE_TEMPLATES[index % len(_SCOPE_TEMPLATES)])
    template["instrumentId"] = (
        f"BENCH:{template['market']}:{template['factType']}:{index:03d}")
    template["symbol"] = f"{template['symbol']}{index:03d}"
    template["base"] = float(template["base"]) * (1.0 + (index // 10) * 0.005)
    return template


def _values(scope: Mapping[str, Any], *, provider_offset: int = 0) -> Dict[str, Any]:
    base = float(scope["base"]) * (1.0 + provider_offset * 0.0005)
    fact_type = scope["factType"]
    if fact_type == "OHLCV_BAR":
        return {
            "open": round(base, 6), "high": round(base * 1.012, 6),
            "low": round(base * 0.992, 6), "close": round(base * 1.006, 6),
            "volume": 1_000_000 + provider_offset * 10_000,
        }
    if fact_type == "NAV":
        return {"nav": round(base, 6)}
    if fact_type == "RATE":
        return {"rate": round(base, 6)}
    return {
        "price": round(base, 6), "previousClose": round(base * 0.995, 6),
        "volume": 2_000_000 + provider_offset * 10_000,
    }


def _build_decision_observation(
    scope: Mapping[str, Any], provider: str, provider_offset: int, *,
    adapter: Optional[str] = None,
) -> Dict[str, Any]:
    market = str(scope["market"])
    observed_at = _OBSERVED_AT[market]
    received_at = _RECEIVED_AT[market]
    return market_truth.build_observation(
        instrument_id=str(scope["instrumentId"]), symbol=str(scope["symbol"]),
        market=market, asset_type=str(scope["assetType"]),
        fact_type=str(scope["factType"]), values=_values(
            scope, provider_offset=provider_offset),
        provider=provider,
        adapter=adapter or f"benchmark-{provider}-v1",
        source_ref=f"benchmark:{provider}:{scope['instrumentId']}",
        observed_at=observed_at, received_at=received_at,
        known_at=received_at, freshness=market_truth.FRESH,
        completeness=market_truth.COMPLETE,
        fresh_until="2026-08-14T21:00:00Z",
        currency=scope.get("currency"), revision=0,
        provenance={"fixture": FIXTURE_VERSION,
                    "providerRank": provider_offset},
    )


def _build_target_observation(scope: Mapping[str, Any], index: int) -> Dict[str, Any]:
    market = str(scope["market"])
    target_at, maturity_at = _TARGET_TIMES[market]
    base = float(scope["base"])
    providers = market_truth.repository_provider_priority(
        market, str(scope["factType"]))
    provider = providers[0]
    currency = scope.get("currency") or ("JPY" if market == "FX" else "USD")
    return market_truth.build_observation(
        instrument_id=str(scope["instrumentId"]), symbol=str(scope["symbol"]),
        market=market, asset_type=str(scope["assetType"]),
        fact_type="OHLCV_BAR",
        values={
            "open": round(base, 6), "high": round(base * 1.04, 6),
            "low": round(base * 0.985, 6), "close": round(base * 1.015, 6),
            "volume": 3_000_000 + index,
        },
        provider=provider, adapter=f"benchmark-{provider}-target-v1",
        source_ref=f"benchmark:target:{scope['instrumentId']}",
        observed_at=target_at, received_at=maturity_at, known_at=maturity_at,
        freshness=market_truth.FRESH, completeness=market_truth.COMPLETE,
        fresh_until=_iso_after(maturity_at, 3600), currency=currency,
        period_start=target_at, period_end=target_at, revision=0,
        provenance={"fixture": FIXTURE_VERSION, "targetSession": "observed"},
    )


def _build_observations(
    request_count: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    scopes = [_scope(index) for index in range(request_count)]
    decision_observations: List[Dict[str, Any]] = []
    target_observations: List[Dict[str, Any]] = []

    registry = market_truth.ProviderAdapterRegistry()
    fixture_adapter = "benchmark-fixture-candidate-v1"
    registry.register(
        market_truth.AdapterSpec(
            adapter_id=fixture_adapter, provider="fixture_candidate",
            markets=("JP",), fact_types=("QUOTE",),
            schema_version="benchmark-fixture-v1"),
        lambda payload, _context: {"observations": list(payload), "errors": []},
    )
    adapter_description = registry.describe()[0]

    for index, scope in enumerate(scopes):
        providers = market_truth.repository_provider_priority(
            str(scope["market"]), str(scope["factType"]))
        for provider_offset, provider in enumerate(providers):
            decision_observations.append(_build_decision_observation(
                scope, provider, provider_offset))
        if index == 0:  # One explicit non-authoritative JP adapter candidate.
            fixture_candidate = _build_decision_observation(
                scope, "fixture_candidate", len(providers), adapter=fixture_adapter)
            adapted = registry.adapt(fixture_adapter, [fixture_candidate], {})
            decision_observations.extend(adapted["observations"])
        target_observations.append(_build_target_observation(scope, index))
    return scopes, decision_observations, target_observations, adapter_description


def _requests(scopes: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "instrumentId": scope["instrumentId"], "market": scope["market"],
        "factType": scope["factType"], "currency": scope.get("currency"),
        "required": True,
    } for scope in scopes]


def _select(
    observations: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    return [market_truth.select_truth(
        observations, instrument_id=str(scope["instrumentId"]),
        market=str(scope["market"]), fact_type=str(scope["factType"]),
        as_of=DECISION_AT, expected_currency=scope.get("currency"),
    ) for scope in scopes]


def _derived_evidence(selections: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for index, selection in enumerate(
            selections[:market_truth.MAX_DERIVED_EVIDENCE]):
        inputs = [
            row["observation"]["observationId"]
            for row in selection.get("candidates") or []
        ]
        if not inputs:
            continue
        out.append({
            "evidenceId": f"benchmark-selection-{index:03d}",
            "kind": "provider_selection",
            "knownAt": DECISION_AT,
            "methodVersion": "benchmark-selection-v1",
            "inputObservationIds": inputs,
            "summary": {
                "candidateCount": int(selection.get("candidateCount") or 0),
                "disagreement": str(
                    (selection.get("disagreement") or {}).get("status") or "NONE"),
            },
        })
    return out


def _snapshot(
    observations: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
    selections: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return market_truth.build_decision_snapshot(
        observations, requests=_requests(scopes), decision_at=DECISION_AT,
        generated_at=GENERATED_AT, build_identity=BUILD_SHA,
        derived_evidence=_derived_evidence(selections),
    )


def _decision_truth_ref(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    result = decision_ledger.point_in_time_truth_ref(
        snapshot_id=str(snapshot["snapshotId"]),
        source_id="argus-market-data-truth",
        as_of=str(snapshot["decisionAt"]), known_at=str(snapshot["generatedAt"]),
        content_hash=str(snapshot["digest"]),
        observation_kind="decision_market_snapshot",
        observed_fields=["selections", "qualitySummary", "datasetDigest"],
        revision=market_truth.SNAPSHOT_SCHEMA_VERSION,
    )
    if result is None:
        raise RuntimeError("decision_truth_ref_rejected")
    return result


def _maturity(scope: Mapping[str, Any]) -> Dict[str, Any]:
    market = str(scope["market"])
    target_at, maturity_at = _TARGET_TIMES[market]
    session_id = f"{_CALENDARS[market]}:2026-08-17:regular"
    result = decision_ledger.session_maturity_contract(
        calendar_id=_CALENDARS[market], target_session_id=session_id,
        target_at=target_at, maturity_at=maturity_at,
        horizon="1d", session_kind="regular")
    if result is None:
        raise RuntimeError("maturity_contract_rejected")
    return result


def _build_predictions(
    scopes: Sequence[Mapping[str, Any]], selections: Sequence[Mapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    truth_ref = _decision_truth_ref(snapshot)
    modes = decision_ledger.PREDICTION_MODES
    predictions = []
    for index, (scope, selection) in enumerate(zip(scopes, selections)):
        mode = modes[index % len(modes)]
        candidate_action = "WAIT" if index % 4 == 0 else "BUY"
        selected_id = str(selection.get("selectedObservationId") or "")
        distribution = decision_ledger.forecast_distribution(
            class_labels=["down", "flat", "up"],
            probabilities=[0.2, 0.2, 0.6],
            class_order_version="direction-v1",
        )
        if distribution is None:
            raise RuntimeError("forecast_distribution_rejected")
        prediction = decision_ledger.prediction_record_v2(
            mode=mode, symbol=str(scope["symbol"]), market=str(scope["market"]),
            issued_at=DECISION_AT, horizon="1d", target_type="direction",
            forecast_value="up", confidence=0.62 + (index % 7) * 0.03,
            candidate_action=candidate_action,
            forecast_distribution=distribution,
            target_ladder=[{"targetId": "up-2pct", "value": 2.0, "unit": "%"}],
            invalidation={"ruleId": "down-1pct", "value": -1.0, "unit": "%"},
            truth_ref=truth_ref, maturity=_maturity(scope),
            engine_id="truth-ledger-benchmark", engine_version="1",
            build_sha=BUILD_SHA,
            evaluation_policy={"policyId": "direction-1d", "policyVersion": "1",
                               "parametersHash": _digest({"horizon": "1d"})},
            evidence_refs=[selected_id], missing_evidence=[], dissent=[],
            replay_cutoff_at=DECISION_AT if mode == "historical_replay" else "",
            now_iso=DECISION_AT,
        )
        if prediction is None or not decision_ledger.verify_prediction_record_v2(prediction):
            raise RuntimeError("prediction_record_rejected")
        predictions.append(prediction)
    return predictions


def _target_truth_ref(
    observation: Mapping[str, Any], maturity: Mapping[str, Any],
) -> Dict[str, Any]:
    result = decision_ledger.point_in_time_truth_ref(
        snapshot_id=str(observation["observationId"]),
        source_id="argus-market-data-truth",
        provider=str((observation.get("source") or {}).get("providerKey") or ""),
        as_of=str(maturity["targetAt"]), known_at=str(maturity["maturityAt"]),
        revision=str(observation.get("revision") or 0),
        content_hash=_digest(observation), observation_kind="target_session_ohlc",
        observed_fields=["open", "high", "low", "close", "volume"],
        target_session_id=str(maturity["targetSessionId"]),
    )
    if result is None:
        raise RuntimeError("target_truth_ref_rejected")
    return result


def _metric(
    *, metric_type: str, family: str, value: Any, unit: str,
    observed_at: str = "", first_observed_at: str = "",
    observation_ref: str = "", target_ref: str = "",
    evidence_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    result = decision_ledger.evaluation_metric(
        metric_type=metric_type, family=family, value=value, unit=unit,
        metric_version="1", method_version="synthetic-ohlc-path-v1",
        polarity="contextual", window="target_session",
        observed_at=observed_at, first_observed_at=first_observed_at,
        observation_ref=observation_ref, target_ref=target_ref,
        evidence_refs=evidence_refs or [],
    )
    if result is None:
        raise RuntimeError(f"evaluation_metric_rejected:{metric_type}")
    return result


def _evaluate(
    predictions: Sequence[Mapping[str, Any]],
    target_observations: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    outcomes, evaluations = [], []
    for index, (prediction, observation) in enumerate(
            zip(predictions, target_observations)):
        maturity = prediction["maturity"]
        target_at, maturity_at = maturity["targetAt"], maturity["maturityAt"]
        observation_ref = f"bar:{maturity['targetSessionId']}:{index:03d}"
        evidence_ref = str(observation["observationId"])
        metrics = [
            _metric(metric_type="path.mfe_pct", family="mfe", value=4.0,
                    unit="%", observed_at=target_at,
                    evidence_refs=[evidence_ref]),
            _metric(metric_type="path.mae_pct", family="mae", value=-1.5,
                    unit="%", observed_at=target_at,
                    evidence_refs=[evidence_ref]),
            _metric(metric_type="target.touch", family="target", value=True,
                    unit="boolean", observed_at=target_at,
                    first_observed_at=target_at, observation_ref=observation_ref,
                    target_ref="up-2pct", evidence_refs=[evidence_ref]),
            _metric(metric_type="invalidation.touch", family="invalidation",
                    value=False, unit="boolean", observed_at=target_at,
                    target_ref="down-1pct", evidence_refs=[evidence_ref]),
            _metric(metric_type="horizon.end_return_pct", family="end",
                    value=1.5, unit="%", observed_at=target_at,
                    evidence_refs=[evidence_ref]),
        ]
        if prediction.get("candidateAction") == "WAIT":
            metrics.extend([
                _metric(metric_type="opportunity.avoided_mae_pct",
                        family="opportunity", value=1.5, unit="%",
                        observed_at=target_at, evidence_refs=[evidence_ref]),
                _metric(metric_type="opportunity.missed_mfe_pct",
                        family="opportunity", value=4.0, unit="%",
                        observed_at=target_at, evidence_refs=[evidence_ref]),
            ])
        outcome = decision_ledger.outcome_resolution_event(
            prediction=dict(prediction), recorded_at=maturity_at,
            truth_ref=_target_truth_ref(observation, maturity),
            status="OBSERVED", metrics=metrics,
            method_version="synthetic-target-session-v1")
        if outcome is None or not decision_ledger.verify_outcome_resolution_event(
                outcome, dict(prediction)):
            raise RuntimeError("outcome_resolution_rejected")
        score = _metric(
            metric_type="score.brier", family="score",
            value=round(0.04 + (index % 5) * 0.01, 6), unit="score",
            evidence_refs=[outcome["id"]])
        evaluation = decision_ledger.evaluation_event_record(
            prediction=dict(prediction), outcome=outcome,
            evaluated_at=_iso_after(maturity_at, 60), metrics=[score],
            scoring_policy={"policyId": "direction-brier", "policyVersion": "1",
                            "parametersHash": _digest({"score": "brier"})},
            evaluator_id="truth-ledger-benchmark-evaluator",
            evaluator_version="1", build_sha=BUILD_SHA)
        if evaluation is None or not decision_ledger.verify_evaluation_event(
                evaluation, dict(prediction), outcome):
            raise RuntimeError("evaluation_event_rejected")
        outcomes.append(outcome)
        evaluations.append(evaluation)
    return outcomes, evaluations


def _aggregate(evaluations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_mode = {
        mode: decision_ledger.aggregate_evaluation_events(
            list(evaluations), mode=mode, purpose="diagnostic")
        for mode in decision_ledger.PREDICTION_MODES
    }
    by_mode["forward_live_calibration"] = decision_ledger.aggregate_evaluation_events(
        list(evaluations), mode="forward_live", purpose="calibration")
    return by_mode


def _canonical_sizes(artifacts: Mapping[str, Any]) -> Dict[str, int]:
    sizes = {key: len(_canonical_bytes(value)) for key, value in artifacts.items()}
    sizes["artifactEnvelope"] = len(_canonical_bytes(artifacts))
    return sizes


def _caps(request_count: int) -> Dict[str, Any]:
    return {
        "benchmark": {
            "requestCount": request_count,
            "smokeRequestCount": SMOKE_REQUEST_COUNT,
            "boundedRequestCount": BOUNDED_REQUEST_COUNT,
        },
        "marketTruth": {
            "maxInputObservations": market_truth.MAX_INPUT_OBSERVATIONS,
            "maxAdapterObservations": market_truth.MAX_ADAPTER_OBSERVATIONS,
            "maxAdapterErrors": market_truth.MAX_ADAPTER_ERRORS,
            "maxCandidates": market_truth.MAX_CANDIDATES,
            "maxAlternates": market_truth.MAX_ALTERNATES,
            "maxSnapshotRequests": market_truth.MAX_SNAPSHOT_REQUESTS,
            "maxDerivedEvidence": market_truth.MAX_DERIVED_EVIDENCE,
            "maxEvidenceInputs": market_truth.MAX_EVIDENCE_INPUTS,
            "maxObservationBytes": market_truth.MAX_OBSERVATION_BYTES,
            "maxSnapshotBytes": market_truth.MAX_SNAPSHOT_BYTES,
        },
        "predictionLedgerV2": {
            "maxEvidenceRefs": decision_ledger._V2_MAX_EVIDENCE_REFS,
            "maxMetricsPerEvent": decision_ledger._V2_MAX_METRICS,
            "maxAggregateEvents": decision_ledger._V2_MAX_AGGREGATE_EVENTS,
            "maxEmbeddedBytes": decision_ledger._V2_MAX_EMBEDDED_BYTES,
            "maxTargetLadderEntries": 12,
            "maxForecastDistributionClasses": (
                decision_ledger._V2_MAX_DISTRIBUTION_CLASSES),
        },
    }


def run_benchmark(
    *, smoke: bool = False, require_exact_4g: bool = False,
    cgroup_root: pathlib.Path = CGROUP_ROOT,
) -> Dict[str, Any]:
    request_count = SMOKE_REQUEST_COUNT if smoke else BOUNDED_REQUEST_COUNT
    cgroup_before = cgroup_snapshot(cgroup_root)
    rss_before = _peak_rss_bytes()
    tracemalloc.start()
    total_started = time.perf_counter_ns()

    started = time.perf_counter_ns()
    scopes, observations, targets, fixture_adapter = _build_observations(
        request_count)
    build_observations_ns = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    selections = _select(observations, scopes)
    select_truth_ns = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    snapshot = _snapshot(observations, scopes, selections)
    snapshot_build_ns = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    predictions = _build_predictions(scopes, selections, snapshot)
    prediction_build_ns = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    outcomes, evaluations = _evaluate(predictions, targets)
    evaluate_ns = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    aggregates = _aggregate(evaluations)
    aggregate_ns = time.perf_counter_ns() - started

    total_ns = time.perf_counter_ns() - total_started
    _, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = _peak_rss_bytes()
    cgroup_after = cgroup_snapshot(cgroup_root)
    cgroup = cgroup_contract(cgroup_before, cgroup_after,
                             required=require_exact_4g)

    artifacts = {
        "decisionObservations": observations,
        "targetObservations": targets,
        "selections": selections,
        "decisionSnapshot": snapshot,
        "predictions": predictions,
        "outcomes": outcomes,
        "evaluations": evaluations,
        "aggregates": aggregates,
    }
    canonical_sizes = _canonical_sizes(artifacts)
    deterministic_digest = _digest(artifacts)
    observation_valid = all(
        market_truth.validate_observation(row) == (True, "ok")
        for row in [*observations, *targets])
    snapshot_valid = market_truth.verify_decision_snapshot(snapshot) == (True, "ok")
    prediction_valid = all(decision_ledger.verify_prediction_record_v2(row)
                           for row in predictions)
    outcome_valid = all(decision_ledger.verify_outcome_resolution_event(
        outcome, prediction) for prediction, outcome in zip(predictions, outcomes))
    evaluation_valid = all(decision_ledger.verify_evaluation_event(
        evaluation, prediction, outcome)
        for prediction, outcome, evaluation in zip(
            predictions, outcomes, evaluations))

    fixture_candidate_selected = sum(
        1 for row in selections
        if (((row.get("selected") or {}).get("observation") or {}).get("source") or {})
        .get("providerKey") == "fixture_candidate")
    fixture_candidate_rejected = sum(
        1 for selection in selections
        for candidate in selection.get("candidates") or []
        if ((candidate.get("observation") or {}).get("source") or {}).get(
            "providerKey") == "fixture_candidate"
        and candidate.get("rejectionReason") == "provider_not_authoritative")
    fixture_candidate_authority = any(
        bool(scope.get("authority"))
        for scope in fixture_adapter.get("scopes") or [])

    core_passed = all((
        observation_valid, snapshot_valid, prediction_valid,
        outcome_valid, evaluation_valid,
        len(selections) == request_count,
        all(row.get("selected") is not None for row in selections),
        fixture_candidate_selected == 0,
        fixture_candidate_rejected == 1,
        not fixture_candidate_authority,
        canonical_sizes["decisionSnapshot"] <= market_truth.MAX_SNAPSHOT_BYTES,
    ))
    return {
        "schemaVersion": REPORT_SCHEMA,
        "fixtureVersion": FIXTURE_VERSION,
        "mode": "smoke" if smoke else "bounded",
        "passed": bool(core_passed and cgroup["passed"]),
        "deterministicDigest": deterministic_digest,
        "counts": {
            "requestCount": request_count,
            "decisionObservationCount": len(observations),
            "targetObservationCount": len(targets),
            "selectionCount": len(selections),
            "selectedCount": sum(row.get("selected") is not None for row in selections),
            "predictionCount": len(predictions),
            "outcomeCount": len(outcomes),
            "evaluationCount": len(evaluations),
            "aggregateCount": len(aggregates),
        },
        "canonicalJsonBytes": canonical_sizes,
        "timingsNs": {
            "buildObservations": build_observations_ns,
            "selectTruth": select_truth_ns,
            "buildDecisionSnapshot": snapshot_build_ns,
            "buildPredictions": prediction_build_ns,
            "evaluate": evaluate_ns,
            "aggregate": aggregate_ns,
            "total": total_ns,
        },
        "resources": {
            "tracemallocPeakBytes": traced_peak,
            "processPeakRssBeforeBytes": rss_before,
            "processPeakRssAfterBytes": rss_after,
            "cgroup": cgroup,
        },
        "caps": _caps(request_count),
        "validation": {
            "observations": observation_valid,
            "decisionSnapshot": snapshot_valid,
            "predictions": prediction_valid,
            "outcomes": outcome_valid,
            "evaluations": evaluation_valid,
        },
        "providerSeams": {
            "nonAuthoritativeFixtureCandidate": {
                "adapterRegistered": True,
                "registrationGrantsAuthority": False,
                "authorityGrantedByRepositoryPolicy": fixture_candidate_authority,
                "selectedCount": fixture_candidate_selected,
                "rejectedNonAuthoritativeCandidateCount": fixture_candidate_rejected,
            },
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke", action="store_true",
        help="run the 10-request representative fixture instead of 32 requests")
    parser.add_argument(
        "--require-exact-4g", action="store_true",
        help="fail unless the exact 4 GiB/no-swap/no-OOM cgroup contract holds")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_benchmark(
            smoke=args.smoke, require_exact_4g=args.require_exact_4g)
    except (AssertionError, RuntimeError, TypeError, ValueError) as exc:
        report = {
            "schemaVersion": REPORT_SCHEMA,
            "mode": "smoke" if args.smoke else "bounded",
            "passed": False,
            "error": type(exc).__name__,
            "errorReason": str(exc)[:160],
        }
    print(json.dumps(report, ensure_ascii=False, allow_nan=False,
                     sort_keys=True, separators=(",", ":")))
    return 0 if report.get("passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline canonical breadth and AI added-value truth audit.

The input is a previously downloaded production GET snapshot. This script
performs no network calls and does not mutate the snapshot, backend, Market
Ledger, scheduler, Soak, or Remote Journal.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path
import sys
from typing import Any, Callable, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from argus_market_ledger import detect_turning_points


Partition = Tuple[str, str, str]


def _direction_parts(point: Dict[str, Any]) -> Tuple[str, str]:
    direction = str(point.get("direction") or "unknown")
    if ":" in direction:
        return tuple(direction.split(":", 1))  # type: ignore[return-value]
    return "legacy", direction


def partition_key(point: Dict[str, Any]) -> Partition:
    universe, rule = _direction_parts(point)
    return str(point.get("effectiveFrom") or ""), universe, rule


def _partition_row(key: Partition) -> Dict[str, str]:
    return {"date": key[0], "universe": key[1], "rule": key[2]}


def breadth_reconciliation(
    market_ledger: Dict[str, Any],
    *,
    as_of: str,
    detected_at: str,
    detector: Callable[[Dict[str, Any], str, str], List[Dict[str, Any]]]
    = detect_turning_points,
) -> Dict[str, Any]:
    persisted = [
        row for row in market_ledger.get("turningPoints") or []
        if isinstance(row, dict) and row.get("ruleId") == "BREADTH_TURN"
    ]
    canonical = [
        row for row in detector(market_ledger, as_of, detected_at)
        if isinstance(row, dict) and row.get("ruleId") == "BREADTH_TURN"
    ]
    persisted_groups: Dict[Partition, List[Dict[str, Any]]] = defaultdict(list)
    canonical_groups: Dict[Partition, List[Dict[str, Any]]] = defaultdict(list)
    for row in persisted:
        persisted_groups[partition_key(row)].append(row)
    for row in canonical:
        canonical_groups[partition_key(row)].append(row)
    persisted_keys = set(persisted_groups)
    canonical_keys = set(canonical_groups)
    duplicate_partitions = {
        key: rows for key, rows in persisted_groups.items() if len(rows) > 1
    }
    missing = sorted(canonical_keys - persisted_keys)
    obsolete = sorted(persisted_keys - canonical_keys)
    canonical_rule_counts = Counter(
        f"{universe}:{rule}" for _, universe, rule in canonical_keys
    )
    weak_rules = sorted(
        rule for rule, count in canonical_rule_counts.items() if count < 60
    )
    backtests = [
        row for row in market_ledger.get("backtests") or []
        if isinstance(row, dict) and row.get("ruleId") == "BREADTH_TURN"
    ]
    backtest_truth = [{
        "universe": row.get("universe"),
        "sampleSize": row.get("sampleSize"),
        "classification": row.get("classification"),
        "noFutureLeakage": (row.get("summary") or {}).get("noFutureLeakage")
        if isinstance(row.get("summary"), dict) else None,
        "hasTwoNonOverlappingHoldouts": False,
        "hasUnconditionalAndMomentumBaselines": False,
        "hasWilsonHalfWidth": False,
        "hasEce": False,
    } for row in backtests]
    return {
        "dedupeKey": ["date", "universe", "rule"],
        "persistedCount": len(persisted),
        "persistedUniquePartitionCount": len(persisted_keys),
        "persistedDuplicatePartitionCount": len(duplicate_partitions),
        "persistedDuplicateExtraRows": sum(len(rows) - 1 for rows in duplicate_partitions.values()),
        "canonicalCount": len(canonical),
        "canonicalUniquePartitionCount": len(canonical_keys),
        "canonicalInternalDuplicateCount": len(canonical) - len(canonical_keys),
        "canonicalMissingFromPersistedCount": len(missing),
        "canonicalMissingFromPersisted": [_partition_row(key) for key in missing],
        "persistedNotCanonicalCount": len(obsolete),
        "persistedNotCanonical": [_partition_row(key) for key in obsolete],
        "ruleEffectiveEpisodes": dict(sorted(canonical_rule_counts.items())),
        "weakRulesBelow60": weak_rules,
        "provisionalRules": sorted(canonical_rule_counts),
        "provisionalReason": (
            "rule-level two-holdout skill, unconditional+momentum dominance, "
            "Wilson width, ECE, and freshness evidence are not persisted"
        ),
        "persistedBacktestEvidence": backtest_truth,
        "migrationExecuted": False,
    }


def ai_added_value(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    forecasts = [row for row in snapshot.get("forecasts") or [] if isinstance(row, dict)]
    outcomes = [row for row in snapshot.get("outcomes") or [] if isinstance(row, dict)]
    outcome_by_forecast = {
        str(row.get("forecastId")): row for row in outcomes if row.get("forecastId")
    }
    resolved = [
        row for row in outcomes
        if str(row.get("status") or "").lower() == "resolved"
    ]
    comparable: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for forecast in forecasts:
        outcome = outcome_by_forecast.get(str(forecast.get("id") or ""))
        if not outcome or outcome not in resolved:
            continue
        if forecast.get("ruleAction") is None or forecast.get("aiFinalAction") is None:
            continue
        comparable.append((forecast, outcome))
    epochs = Counter(str(row.get("modelEpoch") or "unknown") for row in forecasts)
    power_rows = [row for row in snapshot.get("rpsHistory") or [] if isinstance(row, dict)]
    return {
        "actualForecastRuns": len(forecasts),
        "modelEpochs": dict(sorted(epochs.items())),
        "outcomeRecords": len(outcomes),
        "resolvedOutcomes": len(resolved),
        "ruleActionRecords": sum(row.get("ruleAction") is not None for row in forecasts),
        "aiRevisedActionRecords": sum(row.get("aiFinalAction") is not None for row in forecasts),
        "comparableResolvedActionPairs": len(comparable),
        "brier": None,
        "rankedProbabilityScore": None,
        "downsideMissRate": None,
        "falsePositiveRate": None,
        "actionChangeValue": None,
        "researchPowerScoreRecords": len(power_rows),
        "researchPowerScoreIsPredictiveRps": False,
        "conclusion": "SECOND_OPINION_ONLY",
        "reason": (
            "No resolved forecast contains both Rule action and AI revised action; "
            "predictive Brier/RPS and action-change value cannot be estimated"
        ),
    }


def build_report(snapshot: Dict[str, Any], *, generated_at: str) -> Dict[str, Any]:
    market = snapshot.get("marketLedger") if isinstance(snapshot.get("marketLedger"), dict) else {}
    build = snapshot.get("buildIdentity") if isinstance(snapshot.get("buildIdentity"), dict) else {}
    soak = snapshot.get("soak") if isinstance(snapshot.get("soak"), dict) else {}
    return {
        "schemaVersion": "argus-breadth-probability-truth-audit-v1",
        "generatedAt": generated_at,
        "mode": "offline_read_only",
        "productionMutation": False,
        "backendIdentity": {
            "version": build.get("appVersion"),
            "sha": build.get("buildSha"),
        },
        "soakIdentity": {
            "soakId": soak.get("soakId"),
            "startedAt": soak.get("startedAt"),
        },
        "marketLedger": {
            "observationCount": len(market.get("observations") or []),
            "stateHash": market.get("stateHash") or snapshot.get("marketLedgerStateHash"),
            "methodVersion": market.get("methodVersion"),
        },
        "canonicalRegeneration": breadth_reconciliation(
            market, as_of=generated_at, detected_at=generated_at
        ),
        "probabilityDisplayAudit": {
            "exactPercentagePolicy": {
                "oosEffectiveNMin": 100,
                "ruleEffectiveNMin": 60,
                "nonOverlappingSkilledHoldoutsMin": 2,
                "minimumBrierSkill": 0.05,
                "mustBeat": ["unconditional", "momentum"],
                "wilsonHalfWidthPtMax": 10,
                "eceMax": 0.05,
                "breadthLagTradingDaysMax": 1,
                "unresolvedPartitionsMax": 0,
                "duplicatesMax": 0,
            },
            "currentExactPercentagesAllowed": False,
            "fallback": [
                "directional lean", "evidence strength", "effective n",
                "uncertainty", "EXPERIMENTAL",
            ],
            "directionalLeanPopulation": {
                "source": "argus_today_intelligence.calibrate_horizon price-bar episodes",
                "barDeduplication": "one normalized OHLCV row per trading date",
                "episodeDeduplication": "one best occurrence per signal family and non-overlapping cooldown window",
                "breadthTurningPointsUsed": False,
                "persisted4509TurningPointsUsed": False,
                "canonical4061TurningPointsUsed": False,
                "calculation": "plurality of the hidden UP/RANGE/DOWN calibration vector",
            },
        },
        "aiAddedValueAudit": ai_added_value(snapshot),
        "backendMigrationExecuted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--generated-at")
    args = parser.parse_args()
    snapshot_path = Path(args.snapshot)
    output_path = Path(args.output)
    snapshot = json.loads(snapshot_path.read_text())
    if not isinstance(snapshot, dict):
        raise SystemExit("snapshot must be a JSON object")
    generated_at = args.generated_at or str(
        snapshot.get("generatedAt")
        or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    )
    report = build_report(snapshot, generated_at=generated_at)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "artifact": str(output_path),
        "persisted": report["canonicalRegeneration"]["persistedCount"],
        "canonical": report["canonicalRegeneration"]["canonicalCount"],
        "missing": report["canonicalRegeneration"]["canonicalMissingFromPersistedCount"],
        "duplicates": report["canonicalRegeneration"]["persistedDuplicateExtraRows"],
        "aiConclusion": report["aiAddedValueAudit"]["conclusion"],
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

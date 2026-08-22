"""Today headline view — the fast canonical bootstrap for the Today surface.

Derives a compact, decision-first document from the already-verified market
snapshots (1321/1306/SPY/QQQ).  Nothing here computes new market facts: every
value is copied from the canonical verified snapshot, so the headline cannot
become a second decision authority.  The heavy verified snapshot remains the
authority for full history, replay evidence, and decision gating; this view
exists so the Today screen can show prices, four compact charts, and canonical
probabilities without first transporting and hashing ~13 MB.

Pure module: no Flask, no network, no clock (caller supplies now_iso).
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, Mapping, Optional

HEADLINE_SCHEMA = "argus-today-headline-v1"
HEADLINE_INSTRUMENTS = ("1321", "1306", "SPY", "QQQ")
HEADLINE_BAR_COUNT = 31
HEADLINE_BAR_FIELDS = (
    "date", "open", "high", "low", "close", "volume",
    "atr14", "availableFrom", "ma", "volumeRatio20",
)
# The projection/probability consumers use exactly these calibration fields
# (buildTodayProjection + probability truth evaluation).  Everything else in
# the ~40-field calibration horizon object stays on the heavy path.
HEADLINE_CALIBRATION_FIELDS = (
    "horizon", "directionProbabilities", "referenceDirectionProbabilities",
    "probabilities", "levelProbabilities", "targetProbabilities",
    "returnDistribution", "probabilityEligibility", "probabilityTruthEvidence",
    "effectiveSampleCount", "episodeCount", "evaluationSampleCount",
    "rawOccurrenceCount", "brierScore", "confidenceInterval",
    "brierSkillConfidenceInterval", "calibrationError", "averageReactionDelay",
    "modelBrier", "baselineBrier", "brierSkill", "calibrationIntegrity",
    "calibrationVersion", "calibrationDatasetHash", "calibrationStatus",
    "expectedValue", "signalFamily",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _compact_bars(payload: Mapping[str, Any]) -> list:
    bars = ((payload.get("indicators") or {}).get("bars") or [])
    compact = []
    for row in bars[-HEADLINE_BAR_COUNT:]:
        if not isinstance(row, Mapping):
            continue
        compact.append({key: copy.deepcopy(row.get(key))
                        for key in HEADLINE_BAR_FIELDS})
    return compact


def _compact_calibration(payload: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    calibration = ((payload.get("todayIntelligence") or {})
                   .get("calibration") or None)
    if not isinstance(calibration, Mapping):
        return None
    horizons = calibration.get("horizons")
    compact_horizons: Dict[str, Any] = {}
    if isinstance(horizons, Mapping):
        for horizon_key, horizon in horizons.items():
            if not isinstance(horizon, Mapping):
                continue
            compact_horizons[str(horizon_key)] = {
                key: copy.deepcopy(horizon.get(key))
                for key in HEADLINE_CALIBRATION_FIELDS if key in horizon
            }
    return {
        "schemaVersion": calibration.get("schemaVersion"),
        "calibrationVersion": calibration.get("calibrationVersion"),
        "methodVersion": calibration.get("methodVersion"),
        "historyStart": calibration.get("historyStart"),
        "historyEnd": calibration.get("historyEnd"),
        "historyCount": calibration.get("historyCount"),
        # v13.5.14: SHO conditioning transparency rides to the phone so the
        # owner can SEE which state dimensions conditioned today's analogs.
        "shoConditioning": copy.deepcopy(calibration.get("shoConditioning")),
        "horizons": compact_horizons,
    }


def _active_zones(payload: Mapping[str, Any]) -> list:
    zones = payload.get("zones") or []
    return [copy.deepcopy(zone) for zone in zones
            if isinstance(zone, Mapping)
            and zone.get("status") in ("active", "reclaimed")]


def _recent_turning_points(payload: Mapping[str, Any]) -> list:
    points = [point for point in (payload.get("turningPoints") or [])
              if isinstance(point, Mapping)
              and point.get("status") in ("confirmed", "candidate")]
    return [copy.deepcopy(point) for point in points[-3:]]


def _relative_strength_summary(
        payload: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    nikkei = ((payload.get("relativeStrength") or {})
              .get("nikkei_sp500") or None)
    if not isinstance(nikkei, Mapping):
        return None
    change = nikkei.get("change20Pct")
    if not isinstance(change, (int, float)):
        return None
    return {"nikkeiSp500Change20Pct": change}


def build_instrument_headline(snapshot: Optional[Mapping[str, Any]],
                              symbol: str) -> Dict[str, Any]:
    """One instrument's headline entry, or an explicit unavailable state."""
    if not isinstance(snapshot, Mapping) \
            or snapshot.get("verificationStatus") != "verified":
        return {"status": "unavailable", "instrument": symbol,
                "reason": "verified_snapshot_missing"}
    payload = snapshot.get("payload") or {}
    today = payload.get("todayIntelligence") or {}
    entry: Dict[str, Any] = {
        "status": "ready",
        "instrument": symbol,
        "market": "JP" if symbol in ("1321", "1306") else "US",
        "parentSnapshotId": snapshot.get("snapshotId"),
        "parentPayloadHash": snapshot.get("payloadHash"),
        "parentDatasetHash": snapshot.get("datasetHash"),
        "verificationStatus": "verified",
        "methodVersion": snapshot.get("methodVersion"),
        "quality": snapshot.get("quality"),
        "asOf": snapshot.get("asOf"),
        "generatedAt": snapshot.get("generatedAt"),
        "verifiedAt": snapshot.get("verifiedAt"),
        "displayNameJa": payload.get("displayNameJa"),
        "instrumentMetadata": copy.deepcopy(payload.get("instrumentMetadata")),
        "periodEnd": payload.get("periodEnd"),
        "payloadStatus": payload.get("status"),
        "quoteState": payload.get("quoteState"),
        "marketCalendar": copy.deepcopy(payload.get("marketCalendar")),
        "bars": _compact_bars(payload),
        "zones": _active_zones(payload),
        "turningPoints": _recent_turning_points(payload),
        "eventMarkers": copy.deepcopy((payload.get("eventMarkers") or [])[-8:]),
        "calibration": _compact_calibration(payload),
        "shortSelling": copy.deepcopy(today.get("shortSelling")),
        "failedRally": copy.deepcopy(today.get("failedRally")),
        "historyCoverage": copy.deepcopy(today.get("historyCoverage")),
        "relativeStrengthSummary": _relative_strength_summary(payload),
        "automaticAiCalls": 0,
    }
    entry["headlineHash"] = _digest(entry)
    return entry


def build_today_headline(snapshots: Mapping[str, Optional[Mapping[str, Any]]],
                         now_iso: str) -> Dict[str, Any]:
    """The single-response Today bootstrap for all headline instruments.

    ``snapshots`` maps instrument symbol to its verified 5D market snapshot
    (or None).  Unavailable instruments produce explicit truthful states —
    never silent absence.
    """
    instruments = {symbol: build_instrument_headline(
        snapshots.get(symbol), symbol) for symbol in HEADLINE_INSTRUMENTS}
    ready = [entry["parentSnapshotId"] for entry in instruments.values()
             if entry.get("status") == "ready"]
    document = {
        "schemaVersion": HEADLINE_SCHEMA,
        "generatedAt": now_iso,
        "automaticAiCalls": 0,
        "readyCount": len(ready),
        "instrumentCount": len(HEADLINE_INSTRUMENTS),
        "instruments": instruments,
    }
    document["headlineSetId"] = "th-" + _digest(sorted(ready))[:32]
    return document

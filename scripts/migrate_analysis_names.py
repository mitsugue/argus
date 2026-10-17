#!/usr/bin/env python3
"""Offline migration of analysis metadata with an external exact-string map.

Never modifies the input file. No numeric, boolean, time, holding or setting
transformation is supported. Existing content identities are verified first;
new identities and the original file digest are recorded in a separate receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argus_asset_chart_cache as asset_cache
import argus_today_intelligence as today
import argus_verified_snapshot as views


SECTIONS = frozenset({"todayIntelligence", "assetChartReports", "verifiedViewSnapshots"})


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def translate(value, mapping):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        result = [translate(item, mapping) for item in value]
        return value if all(a is b for a, b in zip(value, result)) else result
    if isinstance(value, dict):
        result, changed = {}, False
        for key, child in value.items():
            target = mapping.get(key, key)
            if target in result:
                raise ValueError("renamed_key_collision")
            converted = translate(child, mapping)
            result[target] = converted
            changed = changed or target != key or converted is not child
        return result if changed else value
    return value


def _contains_mapping(value, mapping):
    if isinstance(value, str):
        return value in mapping
    if isinstance(value, list):
        return any(_contains_mapping(item, mapping) for item in value)
    if isinstance(value, dict):
        return any(key in mapping or _contains_mapping(child, mapping)
                   for key, child in value.items())
    return False


def migrate(snapshot, mapping):
    if not isinstance(snapshot, dict) or not isinstance(mapping, dict) or not mapping:
        raise ValueError("snapshot_and_mapping_required")
    if any(not isinstance(k, str) or not isinstance(v, str) or not k or not v
           or k == v for k, v in mapping.items()):
        raise ValueError("exact_string_mapping_required")
    if set(mapping).intersection(mapping.values()):
        raise ValueError("mapping_must_be_idempotent")
    # Unknown sections are immutable here. A match there needs a separately
    # reviewed migration for its own signature, chronology and storage rules.
    for key, value in snapshot.items():
        if key not in SECTIONS and _contains_mapping(value, mapping):
            raise ValueError("unhandled_section_requires_migration")
    result = dict(snapshot)
    identities, sections = [], []
    for section in sorted(SECTIONS):
        original = snapshot.get(section)
        if not isinstance(original, dict):
            continue
        changed = translate(original, mapping)
        if changed == original:
            continue
        if section == "todayIntelligence":
            for rows_key, prefix in (("snapshots", "today-"),
                                     ("failedRallyOutcomes", "failed-rally-")):
                for before, after in zip(original.get(rows_key, []), changed.get(rows_key, [])):
                    if before == after:
                        continue
                    before_body = {k: v for k, v in before.items() if k != "id"}
                    if before.get("id") != prefix + today._hash(before_body):
                        raise ValueError("analysis_source_identity_invalid")
                    after["id"] = prefix + today._hash({k: v for k, v in after.items() if k != "id"})
                    identities.append({"before": before["id"], "after": after["id"]})
        elif section == "assetChartReports":
            for key, before in original.get("records", {}).items():
                after = changed["records"][mapping.get(key, key)]
                if before == after:
                    continue
                if before.get("payloadHash") != asset_cache._hash(before.get("payload")):
                    raise ValueError("asset_source_identity_invalid")
                if before.get("logicalKey") != key or key != asset_cache.logical_key(
                        before["market"], before["symbol"], before["timeframe"],
                        before["datasetHash"], before["methodVersion"]):
                    raise ValueError("asset_source_pointer_invalid")
                after["payloadHash"] = asset_cache._hash(after["payload"])
                expected_key = asset_cache.logical_key(after["market"], after["symbol"],
                    after["timeframe"], after["datasetHash"], after["methodVersion"])
                if after["logicalKey"] != expected_key:
                    raise ValueError("asset_target_pointer_invalid")
                identities.append({"before": before["payloadHash"], "after": after["payloadHash"]})
        else:
            for key, before in original.get("current", {}).items():
                after = changed["current"][mapping.get(key, key)]
                if before == after:
                    continue
                if not views.verify_snapshot(before)[0]:
                    raise ValueError("view_source_identity_invalid")
                after["payloadHash"] = views.payload_hash(after["payload"])
                after["snapshotId"] = views.snapshot_id(after)
                if not views.verify_snapshot(after)[0]:
                    raise ValueError("view_target_identity_invalid")
                identities.append({"before": before["snapshotId"], "after": after["snapshotId"]})
        result[section] = changed
        hash_key = section + "StateHash"
        if hash_key in snapshot:
            hasher = (today.state_hash if section == "todayIntelligence" else
                      asset_cache.state_hash if section == "assetChartReports" else views.state_hash)
            # Verify the original with its own content; the state hasher's
            # metadata normalization is part of the unchanged storage schema.
            if hasher(original) != snapshot[hash_key]:
                raise ValueError("source_section_hash_invalid")
            result[hash_key] = hasher(changed)
        sections.append({"section": section, "beforeHash": digest(original),
                         "afterHash": digest(changed)})
    # No extra history rows are created or deleted. Only named metadata and
    # its dependent identities differ; all other top-level stores stay exact.
    receipt = {"schemaVersion": "analysis-name-migration-v1", "status": "MIGRATED",
               "sections": sections, "identityChanges": identities,
               "mappingDigest": digest(mapping), "originalPreserved": True,
               "productionApplied": False}
    return result, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.input, args.mapping, args.output, args.receipt)]
    if len(set(paths)) != 4 or args.output.exists() or args.receipt.exists():
        raise SystemExit("Distinct paths and new output files are required")
    if args.mapping.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise SystemExit("The concrete migration map must stay outside the product")
    raw = args.input.read_bytes()
    value, receipt = migrate(json.loads(raw), json.loads(args.mapping.read_text()))
    receipt["inputFileSha256"] = hashlib.sha256(raw).hexdigest()
    encoded = canonical(value).encode()
    receipt["outputFileSha256"] = hashlib.sha256(encoded).hexdigest()
    with args.output.open("xb") as handle:
        handle.write(encoded)
    with args.receipt.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, sort_keys=True, indent=2)
    print(json.dumps({"status": "MIGRATED_OFFLINE", "sectionCount": len(receipt["sections"]),
                      "identityChangeCount": len(receipt["identityChanges"]),
                      "productionApplied": False}))


if __name__ == "__main__":
    main()

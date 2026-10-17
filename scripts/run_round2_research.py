#!/usr/bin/env python3
"""Offline, deterministic CLI for the ARGUS Round 2 Research Compute Plane.

Only explicitly named local files are read.  The runner does not inspect the
environment, call a provider, open a socket, or derive the current time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argus_research_compute as research  # noqa: E402


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DATASET_BYTES = 256 * 1024 * 1024
MAX_TOTAL_DATASET_BYTES = 512 * 1024 * 1024
MAX_OUTPUT_BYTES = research.MAX_ARTIFACT_BYTES
ALLOWED_SUFFIXES = (".json", ".jsonl", ".csv")


class RunnerError(RuntimeError):
    pass


def _read_bytes(path: Path, maximum: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise RunnerError(label + "_unreadable") from exc
    if size < 0 or size > maximum:
        raise RunnerError(label + "_byte_bound_exceeded")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RunnerError(label + "_unreadable") from exc
    if len(raw) != size:
        raise RunnerError(label + "_changed_while_reading")
    return raw


def _json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError(label + "_invalid_json") from exc


def _confined_candidate(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RunnerError("dataset_path_escape") from exc
    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        raise RunnerError("unsupported_dataset_format")
    return candidate


def _confined(root: Path, relative: str) -> Path:
    candidate = _confined_candidate(root, relative)
    if not candidate.is_file():
        raise RunnerError("dataset_not_file")
    return candidate


def _verified_payloads(manifest: Mapping[str, Any], dataset_root: Path) \
        -> Tuple[Dict[str, bytes], List[Path]]:
    payloads: Dict[str, bytes] = {}
    total_bytes = 0
    verified_paths: List[Path] = []
    contract = research.validate_manifest(manifest)
    golden_open = contract["goldenPolicy"]["access"] == "OPEN"
    for descriptor in contract["datasets"]:
        if descriptor["partitionScope"] == "GOLDEN" and not golden_open:
            continue
        path = _confined(dataset_root, descriptor["path"])
        verified_paths.append(path)
        raw = _read_bytes(path, MAX_DATASET_BYTES, "dataset")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_DATASET_BYTES:
            raise RunnerError("total_dataset_byte_bound_exceeded")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != descriptor["sha256"]:
            raise RunnerError("dataset_sha256_mismatch")
        payloads[descriptor["datasetId"]] = raw
    return payloads, verified_paths


def run(*, manifest_path: Path, dataset_root: Path, output_path: Path,
        expected_research_identity: str = "",
        previous_manifest_path: Path = None) -> Dict[str, Any]:
    manifest_raw = _read_bytes(manifest_path.resolve(), MAX_MANIFEST_BYTES,
                               "manifest")
    manifest = _json(manifest_raw, "manifest")
    if not isinstance(manifest, dict):
        raise RunnerError("manifest_must_be_object")
    contract = research.validate_manifest(manifest)
    if expected_research_identity and expected_research_identity != \
            contract["researchIdentity"]:
        raise RunnerError("research_identity_mismatch")
    if previous_manifest_path is not None:
        previous_raw = _read_bytes(previous_manifest_path.resolve(),
                                   MAX_MANIFEST_BYTES, "previous_manifest")
        previous = _json(previous_raw, "previous_manifest")
        if not isinstance(previous, dict):
            raise RunnerError("previous_manifest_must_be_object")
        research.validate_retune(previous, manifest)
    root = dataset_root.resolve()
    if not root.is_dir():
        raise RunnerError("dataset_root_not_directory")
    dataset_payloads, verified_paths = _verified_payloads(manifest, root)
    artifact = research.build_verified_research_artifact(
        manifest, dataset_payloads)
    digest = artifact["artifactDigest"]
    payload = research.canonical_bytes(artifact)
    if len(payload) > MAX_OUTPUT_BYTES:
        raise RunnerError("output_byte_bound_exceeded")
    if not research.verify_research_artifact(artifact):
        raise RunnerError("internal_artifact_verification_failed")
    output = output_path.resolve()
    input_paths = {manifest_path.resolve(), *verified_paths}
    input_paths.update(
        _confined_candidate(root, row["path"])
        for row in contract["datasets"])
    if previous_manifest_path is not None:
        input_paths.add(previous_manifest_path.resolve())
    if output in input_paths:
        raise RunnerError("output_may_not_replace_input")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        existing = _read_bytes(output, MAX_OUTPUT_BYTES, "existing_output")
        if existing != payload:
            raise RunnerError("immutable_output_collision")
        return artifact
    temporary = output.with_name(output.name + ".tmp." + digest[:16])
    if temporary.exists():
        existing_temp = _read_bytes(temporary, MAX_OUTPUT_BYTES,
                                    "existing_temporary_output")
        if existing_temp != payload:
            raise RunnerError("temporary_output_collision")
    else:
        temporary.write_bytes(payload)
    temporary.replace(output)
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic offline ARGUS Round 2 research")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-research-identity", default="")
    parser.add_argument("--previous-manifest", type=Path)
    return parser


def main(argv: Iterable[str] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact = run(
            manifest_path=args.manifest,
            dataset_root=args.dataset_root,
            output_path=args.output,
            expected_research_identity=args.expected_research_identity,
            previous_manifest_path=args.previous_manifest)
    except (RunnerError, research.ResearchContractError) as exc:
        sys.stderr.write(json.dumps({
            "error": str(exc), "status": "FAILED_CLOSED"},
            sort_keys=True, separators=(",", ":")) + "\n")
        return 2
    sys.stdout.write(json.dumps({
        "artifactDigest": artifact["artifactDigest"],
        "artifactId": artifact["artifactId"],
        "inputIdentity": artifact["identity"]["inputIdentity"],
        "researchIdentity": artifact["identity"]["researchIdentity"],
        "status": "COMPLETE",
    }, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

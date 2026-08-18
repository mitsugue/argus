#!/usr/bin/env python3
"""Generate or verify the detached, content-addressed V13 release certificate.

The certificate is an Actions artifact rather than a tracked file because a
Git commit cannot contain a digest that recursively names its own final SHA and
tree.  The candidate contains this generator and its policy inputs; CI binds
the detached certificate to the final, immutable candidate commit and tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from typing import Any, Dict


SCHEMA = "argus-v13-release-proof-certificate-v1"
ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_INPUTS = (
    "release/v13-snapshot-readiness-contract.json",
    "release/v13-accepted-fix-manifest.json",
    "web/scripts/release-state-machine.mjs",
    "web/scripts/release-state-machine.test.mjs",
    "web/scripts/full-release-simulation.mjs",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_file(path: pathlib.Path) -> str:
    return _digest_bytes(path.read_bytes())


def _git(value: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", value], cwd=ROOT, text=True).strip()


def _ensure_clean_candidate() -> None:
    changed = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT, text=True).strip()
    if changed:
        raise ValueError("candidate_worktree_not_clean")


def _load(path: pathlib.Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object_required:{path}")
    return value


def _validate_manifest() -> Dict[str, Any]:
    manifest = _load(ROOT / "release/v13-accepted-fix-manifest.json")
    rows = manifest.get("requirements")
    if not isinstance(rows, list) or len(rows) != 19:
        raise ValueError("accepted_fix_manifest_empty")
    for row in rows:
        if row.get("status") != "PRESENT":
            raise ValueError(
                f"accepted_fix_missing:{row.get('requirement')}")
        for relative in ((row.get("implementation") or [])
                         + (row.get("test") or [])):
            if not (ROOT / relative).exists():
                raise ValueError(f"accepted_fix_path_missing:{relative}")
    return manifest


def _validate_contract() -> Dict[str, Any]:
    contract = _load(ROOT / "release/v13-snapshot-readiness-contract.json")
    rows = contract.get("snapshots")
    identities = [row.get("identity") for row in rows or []]
    if contract.get("snapshotExpected") != 12 or len(identities) != 12 \
            or len(set(identities)) != 12:
        raise ValueError("snapshot_contract_not_exact_12")
    if any(row.get("requiredness") != "SEED_REQUIRED" for row in rows):
        raise ValueError("snapshot_contract_classification")
    return contract


def _validate_simulation(path: pathlib.Path, ordinal: int,
                         candidate_sha: str) -> Dict[str, Any]:
    value = _load(path)
    checks = (
        value.get("schemaVersion") == "argus-v13-full-release-simulation-v1",
        value.get("runNumber") == ordinal,
        value.get("status") == "pass",
        value.get("candidateSha") == candidate_sha,
        value.get("initial") == {"snapshotReady": 0, "snapshotExpected": 12},
        value.get("infrastructure", {}).get("pass") is True,
        value.get("trigger", {}).get("status") == "completed",
        len(value.get("trigger", {}).get("plan") or []) == 12,
        value.get("businessSnapshots", {}).get("pass") is True,
        len(value.get("businessSnapshots", {}).get("expectedSet") or []) == 12,
        value.get("businessSnapshots", {}).get("expectedSet")
        == value.get("businessSnapshots", {}).get("observedSet"),
        value.get("canonical", {}).get("instrument") == "1321",
        value.get("canonical", {}).get("horizon") == "5D",
        value.get("canonical", {}).get("responseSnapshotId")
        == value.get("canonical", {}).get("uiSnapshotId"),
        value.get("warmProfileSeal", {}).get("status") == "pass",
        value.get("independentProfileReopen", {}).get("status") == "pass",
        value.get("publicProductAcceptance", {}).get("status") == "pass",
    )
    if not all(checks):
        raise ValueError(f"full_release_simulation_{ordinal}_invalid")
    return value


def generate(args: argparse.Namespace) -> Dict[str, Any]:
    _ensure_clean_candidate()
    candidate_sha = _git("HEAD")
    candidate_tree = _git("HEAD^{tree}")
    _validate_manifest()
    contract = _validate_contract()
    simulations = [
        _validate_simulation(pathlib.Path(args.simulation_one), 1,
                             candidate_sha),
        _validate_simulation(pathlib.Path(args.simulation_two), 2,
                             candidate_sha),
    ]
    ci_status = {}
    for entry in args.ci_status:
        name, separator, status = entry.partition("=")
        if not separator or status != "success" or not name:
            raise ValueError(f"required_ci_not_success:{entry}")
        ci_status[name] = status
    if not ci_status:
        raise ValueError("required_ci_status_empty")
    body = {
        "schemaVersion": SCHEMA,
        "status": "PASS",
        "candidate": {"commitSha": candidate_sha, "treeSha": candidate_tree},
        "policy": {
            "engineVersion": simulations[0].get("engineVersion"),
            "snapshotExpected": contract["snapshotExpected"],
            "snapshotClassifications": contract["requirednessClassifications"],
            "productionMutationAllowedOnlyAfterCertificate": True,
        },
        "sourceDigests": {
            relative: _digest_file(ROOT / relative)
            for relative in POLICY_INPUTS
        },
        "simulationEvidence": [{
            "runNumber": ordinal,
            "sha256": _digest_file(pathlib.Path(path_value)),
            "status": simulations[ordinal - 1]["status"],
            "initialSnapshotReady": 0,
            "snapshotReady": len(simulations[ordinal - 1][
                "businessSnapshots"]["observedSet"]),
        } for ordinal, path_value in enumerate((
            args.simulation_one, args.simulation_two), start=1)],
        "requiredCiStatus": ci_status,
    }
    body["certificateDigest"] = _digest_bytes(_canonical(body))
    return body


def verify(args: argparse.Namespace) -> Dict[str, Any]:
    _ensure_clean_candidate()
    certificate = _load(pathlib.Path(args.certificate))
    digest = certificate.pop("certificateDigest", None)
    if digest != _digest_bytes(_canonical(certificate)):
        raise ValueError("certificate_digest_mismatch")
    if certificate.get("schemaVersion") != SCHEMA \
            or certificate.get("status") != "PASS":
        raise ValueError("certificate_status")
    if certificate.get("candidate") != {
            "commitSha": _git("HEAD"), "treeSha": _git("HEAD^{tree}")}:
        raise ValueError("certificate_candidate_mismatch")
    _validate_manifest()
    _validate_contract()
    expected_digests = {
        relative: _digest_file(ROOT / relative) for relative in POLICY_INPUTS
    }
    if certificate.get("sourceDigests") != expected_digests:
        raise ValueError("certificate_policy_digest_mismatch")
    if not certificate.get("requiredCiStatus") or any(
            status != "success" for status in
            certificate["requiredCiStatus"].values()):
        raise ValueError("certificate_ci_status")
    certificate["certificateDigest"] = digest
    return certificate


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("generate")
    create.add_argument("--simulation-one", required=True)
    create.add_argument("--simulation-two", required=True)
    create.add_argument("--ci-status", action="append", default=[])
    create.add_argument("--out", required=True)
    check = subparsers.add_parser("verify")
    check.add_argument("--certificate", required=True)
    args = parser.parse_args()
    value = generate(args) if args.command == "generate" else verify(args)
    output = pathlib.Path(args.out) if args.command == "generate" else None
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(
            value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
    print(f"V13_RELEASE_CERTIFICATE_{args.command.upper()}=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

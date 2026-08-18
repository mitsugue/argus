#!/usr/bin/env python3
"""Create, fetch, and verify the detached V13.5 production certificate."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import pathlib
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Dict, Mapping


SCHEMA = "argus-v13-5-release-proof-certificate-v1"
CHECKS_SCHEMA = "argus-current-required-checks-v1"
RUNTIME_PROOF_SCHEMA = "argus-zero-install-runtime-proof-v1"
PRODUCT_VERSION = "v13.5"
ACCEPTED_V13_SOURCE = "c946afd07869dbe739026afad11ef5e15418dbbf"
ACCEPTED_V13_TREE = "dee0b33a9b4eb82671f13dc1d9a06d71a71cb124"
ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_INPUTS = (
    "product-version.json",
    "release/v13-acceptance-runtime.json",
    "release/v13-snapshot-readiness-contract.json",
    "release/v13-accepted-fix-manifest.json",
    ".github/actions/acceptance-runtime-preflight/action.yml",
    ".github/actions/warm-profile-seed/action.yml",
    ".github/actions/warm-profile-consumer/action.yml",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/market-public-acceptance.yml",
    "web/scripts/acceptance-runtime.mjs",
    "web/scripts/release-state-machine.mjs",
    "web/scripts/full-release-simulation.mjs",
)
AUTHORIZED_EXTENSION_PATHS = frozenset({
    ".github/actions/acceptance-runtime-preflight/action.yml",
    ".github/actions/candidate-pages-preview/action.yml",
    ".github/actions/warm-profile-consumer/action.yml",
    ".github/actions/warm-profile-seed/action.yml",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/market-public-acceptance.yml",
    ".github/workflows/release-gate.yml",
    ".github/workflows/restore-safe-pages.yml",
    "argus_release_identity.py",
    "docs/ops/v13-final-release-state-machine.md",
    "product-version.json",
    "release/v13-acceptance-runtime.json",
    "release/v13-accepted-fix-manifest.json",
    "scripts/deploy_scope.py",
    "scripts/v13_5_release_certificate.py",
    "scripts/v13_release_certificate.py",
    "test_argus_deploy_scope.py",
    "test_argus_release_identity.py",
    "test_release_gate_cleanliness.py",
    "test_v13_5_release_certificate.py",
    "test_verify_public_candidate_release.py",
    "web/scripts/acceptance-runtime.mjs",
    "web/scripts/acceptance-runtime.test.mjs",
    "web/scripts/full-release-simulation.mjs",
    "web/scripts/public-market-acceptance.contract.test.mjs",
    "web/scripts/round3-product-final.test.mjs",
    "web/scripts/runtime-version-truth.test.mjs",
    "web/scripts/warm-profile-contract.test.mjs",
    "web/package.json",
    "web/src/domain/runtimeVersionTruth.ts",
    "web/vite.config.ts",
})


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


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
    if type(value) is not dict:
        raise ValueError(f"json_object_required:{path}")
    return value


def _write(path: pathlib.Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")


def _candidate(ref: str) -> Dict[str, str]:
    return {"commitSha": _git(f"{ref}^{{commit}}"),
            "treeSha": _git(f"{ref}^{{tree}}")}


def _validate_manifest() -> Dict[str, Any]:
    manifest = _load(ROOT / "release/v13-accepted-fix-manifest.json")
    rows = manifest.get("requirements")
    if not isinstance(rows, list) or len(rows) < 25:
        raise ValueError("accepted_fix_manifest_incomplete")
    names = set()
    for row in rows:
        if type(row) is not dict or set(row) != {
                "requirement", "implementation", "test", "status"}:
            raise ValueError("accepted_fix_manifest_row_shape")
        if row.get("status") != "PRESENT" or type(row.get("requirement")) is not str \
                or row["requirement"] in names:
            raise ValueError("accepted_fix_missing_or_duplicate")
        names.add(row["requirement"])
        for relative in row["implementation"] + row["test"]:
            if type(relative) is not str or not (ROOT / relative).exists():
                raise ValueError(f"accepted_fix_path_missing:{relative}")
    if not {
        "productVersion = v13.5",
        "immutable zero-install acceptance runtime",
        "two fresh-runner zero-install proofs",
        "pre-deploy runtime admission",
        "rollback restore has no browser dependency",
    }.issubset(names):
        raise ValueError("accepted_fix_manifest_release_rows_missing")
    return manifest


def _validate_contract() -> Dict[str, Any]:
    contract = _load(ROOT / "release/v13-snapshot-readiness-contract.json")
    rows = contract.get("snapshots")
    identities = [row.get("identity") for row in rows or []]
    if contract.get("snapshotExpected") != 12 or len(identities) != 12 \
            or len(set(identities)) != 12 \
            or any(row.get("requiredness") != "SEED_REQUIRED" for row in rows):
        raise ValueError("snapshot_contract_not_exact_12")
    return contract


def _validate_product_semantic_diff(candidate_ref: str) -> Dict[str, Any]:
    if _git(f"{ACCEPTED_V13_SOURCE}^{{tree}}") != ACCEPTED_V13_TREE:
        raise ValueError("accepted_v13_source_tree_mismatch")
    changed = subprocess.check_output([
        "git", "diff", "--name-only", ACCEPTED_V13_SOURCE,
        f"{candidate_ref}^{{commit}}"], cwd=ROOT, text=True).splitlines()
    unauthorized = sorted(set(changed) - AUTHORIZED_EXTENSION_PATHS)
    if unauthorized:
        raise ValueError("product_semantic_change_required:" + ",".join(unauthorized))
    return {"status": "PASS", "acceptedSource": ACCEPTED_V13_SOURCE,
            "acceptedTree": ACCEPTED_V13_TREE,
            "changedPaths": sorted(changed), "productSemanticChange": False}


def _validate_simulation(path: pathlib.Path, ordinal: int,
                         candidate: Mapping[str, str]) -> Dict[str, Any]:
    value = _load(path)
    checks = (
        value.get("schemaVersion") == "argus-v13-full-release-simulation-v1",
        value.get("runNumber") == ordinal, value.get("status") == "pass",
        value.get("candidateSha") == candidate["commitSha"],
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
        value.get("warmProfileSeal", {}).get("productVersion") == PRODUCT_VERSION,
        value.get("independentProfileReopen", {}).get("status") == "pass",
        value.get("publicProductAcceptance", {}).get("status") == "pass",
    )
    if not all(checks):
        raise ValueError(f"full_release_simulation_{ordinal}_invalid")
    return value


def _validate_runtime_proof(path: pathlib.Path,
                            candidate: Mapping[str, str]) -> Dict[str, Any]:
    value = _load(path)
    digest = value.pop("proofDigest", None)
    identity, checks = value.get("runtimeIdentity"), value.get("checks")
    if digest != _digest_bytes(_canonical(value)) \
            or value.get("schemaVersion") != RUNTIME_PROOF_SCHEMA \
            or value.get("status") != "PASS" \
            or value.get("candidate") != dict(candidate) \
            or type(checks) is not dict or not checks \
            or any(item is not True for item in checks.values()) \
            or type(identity) is not dict \
            or identity.get("candidate") != dict(candidate) \
            or value.get("runtimeIdentityDigest") != _digest_bytes(_canonical(identity)) \
            or value.get("noDynamicProvisioningAudit", {}).get("pass") is not True \
            or value.get("noDynamicProvisioningAudit", {}).get("matches") != []:
        raise ValueError("runtime_proof_invalid")
    value["proofDigest"] = digest
    return value


def _validate_required_checks(path: pathlib.Path,
                              candidate_sha: str) -> Dict[str, Any]:
    value = _load(path)
    required, rows = value.get("requiredContexts"), value.get("checks")
    if value.get("schemaVersion") != CHECKS_SCHEMA \
            or value.get("candidateSha") != candidate_sha \
            or value.get("status") != "SUCCESS" \
            or not isinstance(required, list) or not required \
            or not isinstance(rows, list) or len(rows) != len(required) \
            or {row.get("name") for row in rows} != set(required) \
            or any(row.get("conclusion") != "success" for row in rows):
        raise ValueError("current_required_checks_invalid")
    return value


def generate(args: argparse.Namespace) -> Dict[str, Any]:
    _ensure_clean_candidate()
    candidate = _candidate(args.candidate_ref)
    manifest, contract = _validate_manifest(), _validate_contract()
    semantic = _validate_product_semantic_diff(args.candidate_ref)
    if _load(ROOT / "product-version.json") != {
            "schemaVersion": "argus-product-version-v1",
            "productVersion": PRODUCT_VERSION}:
        raise ValueError("product_version_not_v13_5")
    simulation_paths = [pathlib.Path(args.simulation_one),
                        pathlib.Path(args.simulation_two)]
    simulations = [_validate_simulation(path, ordinal, candidate)
                   for ordinal, path in enumerate(simulation_paths, 1)]
    runtime_paths = [pathlib.Path(args.runtime_proof_one),
                     pathlib.Path(args.runtime_proof_two)]
    runtimes = [_validate_runtime_proof(path, candidate) for path in runtime_paths]
    if runtimes[0]["runtimeIdentityDigest"] != runtimes[1]["runtimeIdentityDigest"]:
        raise ValueError("fresh_runner_runtime_identity_mismatch")
    required = _validate_required_checks(
        pathlib.Path(args.required_checks), candidate["commitSha"])
    runtime = runtimes[0]["runtimeIdentity"]
    body: Dict[str, Any] = {
        "schemaVersion": SCHEMA, "status": "PASS", "candidate": candidate,
        "productVersion": PRODUCT_VERSION,
        "acceptedV13Source": {"commitSha": ACCEPTED_V13_SOURCE,
                              "treeSha": ACCEPTED_V13_TREE},
        "acceptedFixManifestDigest": _digest_bytes(_canonical(manifest)),
        "acceptanceRuntime": {
            "identityDigest": runtimes[0]["runtimeIdentityDigest"],
            "specDigest": runtime["specDigest"],
            "seedImplementationDigest": runtime["seedImplementationDigest"],
            "container": runtime["container"], "browser": runtime["browser"],
            "nodeVersion": runtime["nodeVersion"],
            "playwrightVersion": runtime["playwrightVersion"]},
        "zeroInstallProofs": [{
            "runNumber": ordinal,
            "runtimeProofSha256": _digest_file(runtime_paths[ordinal - 1]),
            "simulationSha256": _digest_file(simulation_paths[ordinal - 1]),
            "runtimeIdentityDigest": runtimes[ordinal - 1]["runtimeIdentityDigest"],
            "initialSnapshotReady": 0,
            "snapshotReady": len(simulations[ordinal - 1]["businessSnapshots"]["observedSet"]),
            "responseSnapshotId": simulations[ordinal - 1]["canonical"]["responseSnapshotId"],
            "uiSnapshotId": simulations[ordinal - 1]["canonical"]["uiSnapshotId"],
            "status": "PASS"} for ordinal in (1, 2)],
        "noPostDeployInstall": True, "requiredChecks": required,
        "productSemanticDiff": semantic,
        "sourceDigests": {relative: _digest_file(ROOT / relative)
                          for relative in POLICY_INPUTS},
        "snapshotContractDigest": _digest_file(
            ROOT / "release/v13-snapshot-readiness-contract.json"),
        "stateMachineDigest": _digest_file(ROOT / "web/scripts/release-state-machine.mjs"),
        "tachibana": {"status": "PENDING", "authority": "NON_AUTHORITATIVE",
                       "dataStatus": "DATA_GATED", "blocking": False},
        "externalDataGates": ["tachibana", "direct_nikkei_topix", "1570",
                              "nikkei_valuation", "durable_vix_history",
                              "foreign_flow_archive", "earnings_sector_history",
                              "seven_sign_production_calibration"],
        "recovery": {"acceptance": "NOT_STARTED", "authoritative": False,
                     "acceptanceClockStarted": False},
        "policy": {"snapshotExpected": contract["snapshotExpected"],
                   "productionMutationAllowedOnlyAfterCertificate": True,
                   "oneProductionAttempt": True}}
    body["certificateDigest"] = _digest_bytes(_canonical(body))
    return body


def verify(args: argparse.Namespace) -> Dict[str, Any]:
    _ensure_clean_candidate()
    candidate = _candidate(args.candidate_ref)
    certificate = _load(pathlib.Path(args.certificate))
    digest = certificate.pop("certificateDigest", None)
    if digest != _digest_bytes(_canonical(certificate)) \
            or certificate.get("schemaVersion") != SCHEMA \
            or certificate.get("status") != "PASS" \
            or certificate.get("candidate") != candidate \
            or certificate.get("productVersion") != PRODUCT_VERSION \
            or certificate.get("noPostDeployInstall") is not True:
        raise ValueError("certificate_identity_or_status")
    manifest = _validate_manifest()
    _validate_contract()
    _validate_product_semantic_diff(args.candidate_ref)
    if certificate.get("acceptedFixManifestDigest") != _digest_bytes(_canonical(manifest)):
        raise ValueError("certificate_manifest_digest_mismatch")
    if certificate.get("sourceDigests") != {
            relative: _digest_file(ROOT / relative) for relative in POLICY_INPUTS}:
        raise ValueError("certificate_policy_digest_mismatch")
    checks = certificate.get("requiredChecks", {})
    if checks.get("status") != "SUCCESS" or any(
            row.get("conclusion") != "success" for row in checks.get("checks", [])):
        raise ValueError("certificate_required_checks")
    if args.runtime_proof:
        runtime = _validate_runtime_proof(pathlib.Path(args.runtime_proof), candidate)
        accepted = certificate.get("acceptanceRuntime", {})
        if runtime.get("runtimeIdentityDigest") != accepted.get("identityDigest") \
                or runtime.get("runtimeIdentity", {}).get("seedImplementationDigest") \
                != accepted.get("seedImplementationDigest"):
            raise ValueError("certificate_runtime_identity_mismatch")
    certificate["certificateDigest"] = digest
    return certificate


def _api(url: str, token: str, *, accept: str = "application/vnd.github+json") -> bytes:
    headers = {"Accept": accept, "User-Agent": "argus-v13-5-release-control/1",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                timeout=60) as response:
        body = response.read(64 * 1024 * 1024 + 1)
        if len(body) > 64 * 1024 * 1024:
            raise ValueError("github_api_response_too_large")
        return body


def _api_json(url: str, token: str) -> Any:
    return json.loads(_api(url, token))


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("github_token_missing")
    return token


def collect_checks(args: argparse.Namespace) -> Dict[str, Any]:
    token = _token()
    rules = _api_json(f"https://api.github.com/repos/{args.repo}/rules/branches/main", token)
    required, ruleset_ids = [], set()
    for rule in rules:
        if rule.get("type") == "required_status_checks":
            ruleset_ids.add(rule.get("ruleset_id"))
            required.extend(row.get("context") for row in
                            rule.get("parameters", {}).get("required_status_checks", []))
    required = sorted({value for value in required if type(value) is str and value})
    if not required:
        raise ValueError("current_required_contexts_empty")
    deadline, selected = time.monotonic() + args.timeout_seconds, {}
    while True:
        query = urllib.parse.urlencode({"per_page": 100, "filter": "latest"})
        payload = _api_json(f"https://api.github.com/repos/{args.repo}/commits/"
                            f"{args.candidate_sha}/check-runs?{query}", token)
        grouped: Dict[str, list[Mapping[str, Any]]] = {}
        for row in payload.get("check_runs", []):
            if row.get("name") in required:
                grouped.setdefault(row["name"], []).append(row)
        selected = {}
        for name, rows in grouped.items():
            rows.sort(key=lambda row: (str(row.get("completed_at")
                                           or row.get("started_at") or ""),
                                       int(row.get("id") or 0)), reverse=True)
            selected[name] = rows[0]
        if all(selected.get(name, {}).get("status") == "completed"
               and selected[name].get("conclusion") == "success" for name in required):
            break
        if time.monotonic() >= deadline:
            raise ValueError("current_required_not_success:" + json.dumps({
                name: {"status": selected.get(name, {}).get("status", "missing"),
                       "conclusion": selected.get(name, {}).get("conclusion")}
                for name in required}, sort_keys=True))
        time.sleep(10)
    return {"schemaVersion": CHECKS_SCHEMA, "status": "SUCCESS",
            "candidateSha": args.candidate_sha, "requiredContexts": required,
            "rulesetIds": sorted(value for value in ruleset_ids if isinstance(value, int)),
            "checks": [{"name": name, "status": selected[name]["status"],
                        "conclusion": selected[name]["conclusion"],
                        "checkRunId": selected[name]["id"],
                        "detailsUrl": selected[name].get("details_url"),
                        "completedAt": selected[name].get("completed_at")}
                       for name in required]}


def fetch(args: argparse.Namespace) -> Dict[str, Any]:
    token, name = _token(), f"v13-5-release-proof-{args.candidate_sha}"
    query = urllib.parse.urlencode({"name": name, "per_page": 100})
    payload = _api_json(f"https://api.github.com/repos/{args.repo}/actions/artifacts?{query}", token)
    rows = [row for row in payload.get("artifacts", [])
            if row.get("name") == name and row.get("expired") is False
            and row.get("workflow_run", {}).get("head_sha") == args.candidate_sha]
    if len(rows) != 1:
        raise ValueError(f"exact_release_certificate_artifact_count:{len(rows)}")
    archive = _api(rows[0]["archive_download_url"], token,
                   accept="application/octet-stream")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        matches = [entry for entry in bundle.namelist()
                   if pathlib.PurePosixPath(entry).name == "certificate.json"]
        if len(matches) != 1:
            raise ValueError("release_certificate_archive_shape")
        value = json.loads(bundle.read(matches[0]))
    if type(value) is not dict or value.get("candidate", {}).get("commitSha") \
            != args.candidate_sha:
        raise ValueError("release_certificate_artifact_candidate_mismatch")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("generate")
    for name in ("simulation-one", "simulation-two", "runtime-proof-one",
                 "runtime-proof-two", "required-checks", "out"):
        create.add_argument(f"--{name}", required=True)
    create.add_argument("--candidate-ref", default="HEAD")
    check = sub.add_parser("verify")
    check.add_argument("--certificate", required=True)
    check.add_argument("--candidate-ref", default="HEAD")
    check.add_argument("--runtime-proof", default="")
    collect = sub.add_parser("collect-checks")
    collect.add_argument("--repo", required=True)
    collect.add_argument("--candidate-sha", required=True)
    collect.add_argument("--timeout-seconds", type=int, default=1500)
    collect.add_argument("--out", required=True)
    get = sub.add_parser("fetch")
    get.add_argument("--repo", required=True)
    get.add_argument("--candidate-sha", required=True)
    get.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "generate":
        _write(pathlib.Path(args.out), generate(args))
    elif args.command == "verify":
        verify(args)
    elif args.command == "collect-checks":
        if not 1 <= args.timeout_seconds <= 3600:
            raise ValueError("invalid_required_checks_timeout")
        _write(pathlib.Path(args.out), collect_checks(args))
    else:
        _write(pathlib.Path(args.out), fetch(args))
    print(f"V13_5_RELEASE_CERTIFICATE_{args.command.upper().replace('-', '_')}=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

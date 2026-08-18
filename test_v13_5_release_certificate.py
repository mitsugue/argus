import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from scripts import v13_5_release_certificate as release


CANDIDATE = {"commitSha": "a" * 40, "treeSha": "b" * 40}


def write_json(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def runtime_proof():
    identity = {
        "candidate": CANDIDATE,
        "seedImplementationDigest": "c" * 64,
    }
    value = {
        "schemaVersion": release.RUNTIME_PROOF_SCHEMA,
        "status": "PASS",
        "candidate": CANDIDATE,
        "runtimeIdentity": identity,
        "runtimeIdentityDigest": hashlib.sha256(
            release._canonical(identity)).hexdigest(),
        "checks": {"runtimeAvailable": True, "browserLaunched": True},
        "noDynamicProvisioningAudit": {"pass": True, "matches": []},
    }
    value["proofDigest"] = hashlib.sha256(
        release._canonical(value)).hexdigest()
    return value


def test_runtime_proof_is_content_addressed_and_candidate_bound(tmp_path):
    path = tmp_path / "runtime.json"
    write_json(path, runtime_proof())
    assert release._validate_runtime_proof(path, CANDIDATE)["status"] == "PASS"
    hostile = runtime_proof()
    hostile["candidate"] = {"commitSha": "d" * 40, "treeSha": "b" * 40}
    write_json(path, hostile)
    with pytest.raises(ValueError, match="runtime_proof_invalid"):
        release._validate_runtime_proof(path, CANDIDATE)


def test_current_required_requires_exact_success_set(tmp_path):
    path = tmp_path / "checks.json"
    value = {
        "schemaVersion": release.CHECKS_SCHEMA,
        "status": "SUCCESS",
        "candidateSha": CANDIDATE["commitSha"],
        "requiredContexts": ["backend-rules", "frontend", "gate"],
        "rulesetIds": [18876691],
        "checks": [{"name": name, "conclusion": "success"}
                   for name in ("backend-rules", "frontend", "gate")],
    }
    write_json(path, value)
    assert release._validate_required_checks(
        path, CANDIDATE["commitSha"])["status"] == "SUCCESS"
    value["checks"][1]["conclusion"] = "neutral"
    write_json(path, value)
    with pytest.raises(ValueError, match="current_required_checks_invalid"):
        release._validate_required_checks(path, CANDIDATE["commitSha"])


def test_fetch_accepts_one_exact_candidate_artifact(monkeypatch, tmp_path):
    certificate = {"candidate": CANDIDATE, "certificateDigest": "e" * 64}
    archive_io = io.BytesIO()
    with zipfile.ZipFile(archive_io, "w") as bundle:
        bundle.writestr("certificate.json", json.dumps(certificate))
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(release, "_api_json", lambda _url, _token: {
        "artifacts": [{
            "name": f"v13-5-release-proof-{CANDIDATE['commitSha']}",
            "expired": False,
            "workflow_run": {"head_sha": CANDIDATE["commitSha"]},
            "archive_download_url": "https://example.invalid/artifact.zip",
        }],
    })
    monkeypatch.setattr(release, "_api", lambda *_args, **_kwargs: archive_io.getvalue())
    value = release.fetch(argparse.Namespace(
        repo="mitsugue/argus", candidate_sha=CANDIDATE["commitSha"],
        out=str(tmp_path / "out.json")))
    assert value == certificate


def test_manifest_and_product_semantic_allowlist_are_closed():
    manifest = release._validate_manifest()
    names = {row["requirement"] for row in manifest["requirements"]}
    assert "productVersion = v13.5" in names
    assert "rollback restore has no browser dependency" in names
    assert "scanner.py" not in release.AUTHORIZED_EXTENSION_PATHS

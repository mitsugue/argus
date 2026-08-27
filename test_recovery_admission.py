import copy
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import recovery_admission as recovery


BASE_SHA = "1" * 40
BASE_TREE = "2" * 40
CANDIDATE_SHA = "3" * 40
CANDIDATE_TREE = "4" * 40


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        stdout=subprocess.PIPE, text=True,
    ).stdout.strip()


def _write(repo: Path, relative: str, value: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.name", "Recovery Test")
    _run(repo, "config", "user.email", "recovery@example.invalid")
    _write(repo, "product-version.json", json.dumps({
        "schemaVersion": "argus-product-version-v1",
        "productVersion": "13.5.36",
    }))
    _write(repo, "README.md", "base\n")
    _run(repo, "add", ".")
    _run(repo, "commit", "-m", "base")
    return repo, _run(repo, "rev-parse", "HEAD")


def _commit(repo: Path, message: str = "candidate") -> str:
    _run(repo, "add", ".")
    _run(repo, "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


def _classify_temp_recovery(repo: Path, base: str, head: str):
    payload = [
        row["path"] for row in
        recovery._path_entries(repo, base, head)
        if row["path"] in recovery.RECOVERY_PAYLOAD_PATHS
    ]
    expected = recovery._digest_bytes(
        recovery._patch_bytes(repo, base, head, payload))
    return recovery.classify_repository(
        repo, base, head, expected_payload_digest=expected)


def _classification() -> dict:
    product_version = {
        "schemaVersion": "argus-product-version-v1",
        "productVersion": "13.5.36",
    }
    value = {
        "schemaVersion": recovery.CLASSIFICATION_SCHEMA,
        "status": "PASS",
        "classification": "RECOVERY_ONLY",
        "base": {"commitSha": BASE_SHA, "treeSha": BASE_TREE},
        "candidate": {
            "commitSha": CANDIDATE_SHA,
            "treeSha": CANDIDATE_TREE,
        },
        "changedPathCount": 1,
        "changedPaths": [{"status": "M", "path": "scanner.py"}],
        "recoveryPayloadPaths": ["scanner.py"],
        "recoveryAdmissionPaths": [],
        "productOrUnknownPaths": [],
        "recoveryPayloadDiffSha256":
            recovery.EXPECTED_RECOVERY_PAYLOAD_DIFF_SHA256,
        "recoveryAdmissionDiffSha256": None,
        "scopePolicySha256": recovery._digest(
            recovery.scope_policy_document()),
        "productVersion": {
            "base": product_version,
            "candidate": product_version,
            "unchanged": True,
        },
        "authorityAssertions": copy.deepcopy(recovery.AUTHORITY_ASSERTIONS),
    }
    value["classificationDigest"] = recovery._digest(value)
    return value


def _junit(path: Path, *, failures: int = 0) -> None:
    path.write_text(
        '<testsuites tests="3" failures="{0}" errors="0" skipped="0">'
        '<testsuite tests="3" failures="{0}" errors="0" skipped="0">'
        '<testcase name="one"/></testsuite></testsuites>'.format(failures),
        encoding="utf-8",
    )


def _certificate_documents(tmp_path: Path):
    classification = _classification()
    junit = tmp_path / "junit.xml"
    _junit(junit)
    evidence = recovery.record_evidence(
        classification, junit, ["focused-recovery-tests", "scope-classifier"])
    certificate = recovery.issue_certificate(classification, evidence)
    return certificate, classification, evidence


def _archive(*documents: dict) -> bytes:
    names = ("certificate.json", "classification.json", "evidence.json")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        for name, document in zip(names, documents):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            bundle.writestr(info, json.dumps(document))
    return stream.getvalue()


def test_product_only_change_routes_to_existing_product_authority(tmp_path):
    repo, base = _repository(tmp_path)
    _write(repo, "README.md", "product\n")
    head = _commit(repo)
    result = recovery.classify_repository(repo, base, head)
    assert result["classification"] == "PRODUCT"
    assert result["status"] == "PASS"
    assert result["productOrUnknownPaths"] == ["README.md"]


def test_exact_recovery_payload_routes_to_recovery_authority(tmp_path):
    repo, base = _repository(tmp_path)
    _write(repo, "scanner.py", "RECOVERY = True\n")
    head = _commit(repo)
    result = _classify_temp_recovery(repo, base, head)
    assert result["classification"] == "RECOVERY_ONLY"
    assert result["status"] == "PASS"
    assert result["productOrUnknownPaths"] == []
    assert result["productVersion"]["unchanged"] is True


def test_mixed_product_and_recovery_change_is_explicitly_denied(tmp_path):
    repo, base = _repository(tmp_path)
    _write(repo, "scanner.py", "RECOVERY = True\n")
    _write(repo, "README.md", "mixed\n")
    head = _commit(repo)
    result = recovery.classify_repository(repo, base, head)
    assert result["classification"] == "MIXED"
    assert result["status"] == "REJECTED"


def test_recovery_plus_product_version_change_is_mixed_and_denied(tmp_path):
    repo, base = _repository(tmp_path)
    _write(repo, "scanner.py", "RECOVERY = True\n")
    _write(repo, "product-version.json", json.dumps({
        "schemaVersion": "argus-product-version-v1",
        "productVersion": "13.5.37",
    }))
    head = _commit(repo)
    result = recovery.classify_repository(repo, base, head)
    assert result["classification"] == "MIXED"
    assert result["status"] == "REJECTED"
    assert result["productVersion"]["unchanged"] is False


def test_admission_only_change_stays_on_product_authority(tmp_path):
    repo, base = _repository(tmp_path)
    _write(repo, ".github/workflows/release-gate.yml", "name: changed\n")
    head = _commit(repo)
    result = recovery.classify_repository(repo, base, head)
    assert result["classification"] == "PRODUCT"
    assert result["status"] == "PASS"
    assert result["recoveryAdmissionPaths"] == [
        ".github/workflows/release-gate.yml"]


def test_recovery_patch_digest_mismatch_fails_closed(tmp_path):
    repo, base = _repository(tmp_path)
    _write(repo, "scanner.py", "UNREVIEWED = True\n")
    head = _commit(repo)
    with pytest.raises(recovery.AdmissionError,
                       match="recovery_payload_digest_mismatch"):
        recovery.classify_repository(repo, base, head)


def test_unrelated_base_is_not_accepted(tmp_path):
    repo, base = _repository(tmp_path)
    _run(repo, "checkout", "--orphan", "other")
    _write(repo, "README.md", "other\n")
    _run(repo, "add", ".")
    _run(repo, "commit", "-m", "other")
    head = _run(repo, "rev-parse", "HEAD")
    with pytest.raises(recovery.AdmissionError,
                       match="base_not_candidate_ancestor"):
        recovery.classify_repository(repo, base, head)


def test_evidence_and_certificate_are_exact_identity_bound(tmp_path):
    certificate, classification, evidence = _certificate_documents(tmp_path)
    assert recovery.verify_certificate(
        certificate, classification, evidence) == certificate
    assert certificate["candidate"] == classification["candidate"]
    hostile = copy.deepcopy(certificate)
    hostile["candidate"]["treeSha"] = "9" * 40
    with pytest.raises(recovery.AdmissionError,
                       match="certificateDigest_invalid"):
        recovery.verify_certificate(hostile, classification, evidence)


def test_failed_junit_cannot_be_recorded_as_recovery_evidence(tmp_path):
    junit = tmp_path / "junit.xml"
    _junit(junit, failures=1)
    with pytest.raises(recovery.AdmissionError,
                       match="recovery_evidence_tests_not_passed"):
        recovery.record_evidence(_classification(), junit, ["focused-tests"])


def test_archive_requires_one_of_each_bound_document(tmp_path):
    certificate, classification, evidence = _certificate_documents(tmp_path)
    archive = _archive(certificate, classification, evidence)
    assert recovery._archive_documents(archive) == (
        certificate, classification, evidence)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr("certificate.json", json.dumps(certificate))
    with pytest.raises(recovery.AdmissionError,
                       match="classification.json_count_invalid"):
        recovery._archive_documents(stream.getvalue())


def test_cross_origin_artifact_redirect_strips_bearer():
    handler = recovery._StripCrossOriginAuthorization()
    request = recovery.urllib.request.Request(
        "https://api.github.com/repos/mitsugue/argus/actions/artifacts/1/zip",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer secret",
        },
    )
    redirected = handler.redirect_request(
        request, None, 302, "Found", {},
        "https://productionresultssa.blob.core.windows.net/result.zip?sig=x",
    )
    assert redirected is not None
    assert redirected.get_header("Accept") == "application/vnd.github+json"
    assert redirected.get_header("Authorization") is None


def test_same_origin_redirect_retains_bearer():
    handler = recovery._StripCrossOriginAuthorization()
    request = recovery.urllib.request.Request(
        "https://api.github.com/repos/mitsugue/argus/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret"},
    )
    redirected = handler.redirect_request(
        request, None, 302, "Found", {},
        "https://api.github.com/repos/mitsugue/argus/actions/artifacts/1/archive",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") == "Bearer secret"


def test_https_artifact_redirect_cannot_downgrade_transport():
    handler = recovery._StripCrossOriginAuthorization()
    request = recovery.urllib.request.Request(
        "https://api.github.com/repos/mitsugue/argus/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret"},
    )
    with pytest.raises(recovery.AdmissionError,
                       match="github_redirect_insecure"):
        handler.redirect_request(
            request, None, 302, "Found", {},
            "http://example.invalid/result.zip",
        )


def test_authority_is_bound_to_exact_check_workflow_and_artifact(
        tmp_path, monkeypatch):
    certificate, classification, evidence = _certificate_documents(tmp_path)
    archive = _archive(certificate, classification, evidence)
    repository = "mitsugue/argus"
    run_id, job_id, artifact_id = 123, 456, 789
    artifact_name = f"recovery-admission-{CANDIDATE_SHA}-{run_id}-1"
    archive_url = (
        f"https://api.github.com/repos/{repository}/actions/artifacts/"
        f"{artifact_id}/zip"
    )
    artifact = {
        "id": artifact_id,
        "name": artifact_name,
        "expired": False,
        "archive_download_url": archive_url,
        "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "workflow_run": {"id": run_id, "head_sha": CANDIDATE_SHA},
    }
    check = {
        "id": 987,
        "name": recovery.RECOVERY_CHECK_CONTEXT,
        "status": "completed",
        "conclusion": "success",
        "completed_at": "2026-08-27T00:00:00Z",
        "details_url": (
            f"https://github.com/{repository}/actions/runs/{run_id}/job/"
            f"{job_id}"
        ),
    }
    run = {
        "id": run_id,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "event": "pull_request",
        "head_sha": CANDIDATE_SHA,
        "path": recovery.RECOVERY_WORKFLOW_PATH,
    }

    def fake_json(url, _token):
        if "/check-runs?" in url:
            return {"check_runs": [check]}
        if url.endswith(f"/actions/runs/{run_id}"):
            return run
        if f"/actions/runs/{run_id}/artifacts?" in url:
            return {"artifacts": [artifact]}
        if url.endswith(f"/actions/artifacts/{artifact_id}"):
            return artifact
        raise AssertionError(url)

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(recovery, "_api_json", fake_json)
    monkeypatch.setattr(recovery, "_api_bytes", lambda url, token: archive)
    authority = recovery.collect_authority(
        repository=repository,
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        candidate_tree=CANDIDATE_TREE,
        classification_digest=classification["classificationDigest"],
        timeout_seconds=1,
    )
    assert authority["producer"]["workflowPath"] == \
        recovery.RECOVERY_WORKFLOW_PATH
    assert authority["artifact"]["artifactId"] == artifact_id
    assert authority["certificate"]["certificateDigest"] == \
        certificate["certificateDigest"]

    receipt = recovery.fetch_authority(
        repository=repository,
        authority=authority,
        certificate_out=tmp_path / "fetched-certificate.json",
        classification_out=tmp_path / "fetched-classification.json",
        evidence_out=tmp_path / "fetched-evidence.json",
        receipt_out=tmp_path / "receipt.json",
    )
    assert receipt["status"] == "PASS"
    assert receipt["certificateDigest"] == certificate["certificateDigest"]


def test_wrong_recovery_producer_workflow_fails_closed(tmp_path, monkeypatch):
    certificate, classification, evidence = _certificate_documents(tmp_path)
    archive = _archive(certificate, classification, evidence)
    repository = "mitsugue/argus"
    run_id, artifact_id = 123, 789
    check = {
        "id": 987,
        "name": recovery.RECOVERY_CHECK_CONTEXT,
        "status": "completed",
        "conclusion": "success",
        "completed_at": "2026-08-27T00:00:00Z",
        "details_url": (
            f"https://github.com/{repository}/actions/runs/{run_id}/job/456"
        ),
    }
    wrong_run = {
        "id": run_id,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "event": "pull_request",
        "head_sha": CANDIDATE_SHA,
        "path": ".github/workflows/recovery-admission.yml",
    }

    def fake_json(url, _token):
        if "/check-runs?" in url:
            return {"check_runs": [check]}
        if url.endswith(f"/actions/runs/{run_id}"):
            return wrong_run
        raise AssertionError(url)

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(recovery, "_api_json", fake_json)
    monkeypatch.setattr(recovery, "_api_bytes", lambda url, token: archive)
    with pytest.raises(recovery.AdmissionError,
                       match="recovery_authority_workflow_invalid"):
        recovery.collect_authority(
            repository=repository,
            base_sha=BASE_SHA,
            candidate_sha=CANDIDATE_SHA,
            candidate_tree=CANDIDATE_TREE,
            classification_digest=classification["classificationDigest"],
            timeout_seconds=1,
        )


def test_policy_has_disjoint_explicit_paths_and_pinned_payload():
    assert not set(recovery.RECOVERY_PAYLOAD_PATHS).intersection(
        recovery.RECOVERY_ADMISSION_PATHS)
    assert len(recovery.RECOVERY_PAYLOAD_PATHS) == 15
    assert len(recovery.RECOVERY_ADMISSION_PATHS) == 4
    assert recovery.scope_policy_document()["mixedPolicy"] == "DENY"
    assert len(recovery.EXPECTED_RECOVERY_PAYLOAD_DIFF_SHA256) == 64


def test_workflow_contract_keeps_product_and_recovery_authorities_separate():
    market = Path(".github/workflows/market-public-acceptance.yml").read_text()
    gate = Path(".github/workflows/release-gate.yml").read_text()
    assert "needs.scope.outputs.classification == 'PRODUCT'" in market
    assert "name: proof-certificate" in market
    assert "name: recovery-certificate" in market
    assert "needs.scope.outputs.classification == 'RECOVERY_ONLY'" in \
        market
    assert "MIXED scope is denied" in market
    assert "collect-authority" in gate
    assert "fetch-authority" in gate
    assert "needs.classify.outputs.classification == 'RECOVERY_ONLY'" in gate
    assert "needs.classify.outputs.classification == 'PRODUCT'" in gate
    assert "name: gate" in gate

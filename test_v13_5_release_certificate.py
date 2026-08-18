import argparse
import hashlib
import io
import json
import subprocess
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from scripts import v13_5_release_certificate as release


CANDIDATE = {"commitSha": "a" * 40, "treeSha": "b" * 40}
REPOSITORY = "mitsugue/argus"
PRODUCER_RUN_ID = 12345
ARTIFACT_ID = 67890
SEMANTIC = {
    "status": "PASS",
    "acceptedSource": release.ACCEPTED_V13_SOURCE,
    "acceptedTree": release.ACCEPTED_V13_TREE,
    "changedPaths": [],
    "productSemanticChange": False,
}


def write_json(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def runtime_proof():
    identity = {
        "candidate": CANDIDATE,
        "specDigest": "1" * 64,
        "seedImplementationDigest": "c" * 64,
        "container": {"image": "playwright", "digest": "2" * 64},
        "browser": {"name": "chromium", "version": "140.0.7339.16"},
        "nodeVersion": "22.18.0",
        "playwrightVersion": "1.55.0",
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


def reseal(value):
    value = json.loads(json.dumps(value))
    value.pop("certificateDigest", None)
    value["certificateDigest"] = hashlib.sha256(
        release._canonical(value)).hexdigest()
    return value


def admission_certificate():
    proof = runtime_proof()
    identity = proof["runtimeIdentity"]
    value = {
        "schemaVersion": release.ADMISSION_SCHEMA,
        "status": "PASS",
        "candidate": CANDIDATE,
        "productVersion": release.PRODUCT_VERSION,
        "acceptedV13Source": {
            "commitSha": release.ACCEPTED_V13_SOURCE,
            "treeSha": release.ACCEPTED_V13_TREE,
        },
        "acceptedFixManifestDigest": hashlib.sha256(
            release._canonical({})).hexdigest(),
        "acceptanceRuntime": {
            "identityDigest": proof["runtimeIdentityDigest"],
            "specDigest": identity["specDigest"],
            "seedImplementationDigest": identity["seedImplementationDigest"],
            "container": identity["container"],
            "browser": identity["browser"],
            "nodeVersion": identity["nodeVersion"],
            "playwrightVersion": identity["playwrightVersion"],
        },
        "zeroInstallProofs": [{
            "runNumber": ordinal,
            "runtimeProofSha256": str(ordinal) * 64,
            "simulationSha256": str(ordinal + 2) * 64,
            "runtimeIdentityDigest": proof["runtimeIdentityDigest"],
            "initialSnapshotReady": 0,
            "snapshotReady": 12,
            "responseSnapshotId": f"vs-proof-{ordinal}",
            "uiSnapshotId": f"vs-proof-{ordinal}",
            "status": "PASS",
        } for ordinal in (1, 2)],
        "noPostDeployInstall": True,
        "productSemanticDiff": SEMANTIC,
        "sourceDigests": {relative: "f" * 64
                          for relative in release.POLICY_INPUTS},
        "snapshotContractDigest": "f" * 64,
        "stateMachineDigest": "f" * 64,
        "tachibana": {"status": "PENDING"},
        "recovery": {"acceptance": "NOT_STARTED"},
        "policy": {
            "snapshotExpected": 12,
            "preMergeAdmissionRequired": True,
            "productionMutationAllowedOnlyAfterAdmission": True,
            "oneProductionAttempt": True,
        },
    }
    return reseal(value)


def certificate_archive(value=None, *, entry="certificate.json"):
    payload = admission_certificate() if value is None else value
    raw = payload if type(payload) is bytes else json.dumps(payload).encode()
    archive_io = io.BytesIO()
    with zipfile.ZipFile(archive_io, "w") as bundle:
        bundle.writestr(entry, raw)
    return archive_io.getvalue()


def fetch_args(tmp_path, **overrides):
    values = {
        "repo": REPOSITORY,
        "candidate_sha": CANDIDATE["commitSha"],
        "candidate_tree": CANDIDATE["treeSha"],
        "consumer_run_id": "99999",
        "expected_producer_workflow":
            ".github/workflows/market-public-acceptance.yml",
        "timeout_seconds": 0,
        "poll_seconds": 1,
        "out": str(tmp_path / "certificate.json"),
        "receipt_out": str(tmp_path / "receipt.json"),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def artifact_row(**overrides):
    values = {
        "id": ARTIFACT_ID,
        "name": f"v13-5-premerge-admission-{CANDIDATE['commitSha']}",
        "expired": False,
        "workflow_run": {
            "id": PRODUCER_RUN_ID,
            "head_sha": CANDIDATE["commitSha"],
        },
        "archive_download_url":
            f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/"
            f"{ARTIFACT_ID}/zip",
    }
    values.update(overrides)
    return values


def producer_run(**overrides):
    values = {
        "id": PRODUCER_RUN_ID,
        "status": "completed",
        "conclusion": "success",
        "event": "pull_request",
        "head_sha": CANDIDATE["commitSha"],
        "path": ".github/workflows/market-public-acceptance.yml",
    }
    values.update(overrides)
    return values


def install_fetch_mocks(monkeypatch, *, rows=None, producer=None, archive=None):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    artifact_rows = [artifact_row()] if rows is None else rows
    producer_value = producer_run() if producer is None else producer

    def fake_json(url, _token):
        if "/actions/artifacts?" in url:
            return {"artifacts": artifact_rows}
        if f"/actions/runs/{PRODUCER_RUN_ID}" in url:
            return producer_value
        raise AssertionError(f"unexpected URL: {url}")

    calls = []

    def fake_api(url, _token, **kwargs):
        calls.append((url, kwargs))
        return certificate_archive() if archive is None else archive

    monkeypatch.setattr(release, "_api_json", fake_json)
    monkeypatch.setattr(release, "_api", fake_api)
    return calls


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


def test_github_artifact_transport_uses_supported_json_media_type(monkeypatch):
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b"artifact-zip"

    class Opener:
        def open(self, request, timeout):
            observed["accept"] = request.get_header("Accept")
            observed["timeout"] = timeout
            return Response()

    monkeypatch.setattr(
        release.urllib.request, "build_opener", lambda _handler: Opener())
    assert release._api("https://api.github.com/example", "token") == b"artifact-zip"
    assert observed == {
        "accept": "application/vnd.github+json",
        "timeout": 60,
    }
    assert observed["accept"] != "application/octet-stream"


@pytest.mark.parametrize("status", [404, 415, 500, 503])
def test_github_http_failures_are_precise_and_fail_closed(monkeypatch, status):
    class Opener:
        def open(self, *_args, **_kwargs):
            raise urllib.error.HTTPError(
                "https://api.github.com/example", status, "failure", {},
                io.BytesIO(json.dumps({
                    "message": "transport rejected"}).encode()))

    monkeypatch.setattr(
        release.urllib.request, "build_opener", lambda _handler: Opener())
    with pytest.raises(
            ValueError,
            match=rf"github_http_error:{status}:transport rejected"):
        release._api("https://api.github.com/example", "token")


def test_cross_origin_artifact_redirect_strips_bearer_and_keeps_media_type():
    handler = release._StripCrossOriginAuthorization()
    request = release.urllib.request.Request(
        "https://api.github.com/repos/mitsugue/argus/actions/artifacts/1/zip",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer secret",
        })
    redirected = handler.redirect_request(
        request, None, 302, "Found", {},
        "https://productionresultssa.blob.core.windows.net/result.zip?sig=x")
    assert redirected is not None
    assert redirected.get_header("Accept") == "application/vnd.github+json"
    assert redirected.get_header("Authorization") is None


def test_same_origin_redirect_retains_bearer():
    handler = release._StripCrossOriginAuthorization()
    request = release.urllib.request.Request(
        "https://api.github.com/repos/mitsugue/argus/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret"})
    redirected = handler.redirect_request(
        request, None, 302, "Found", {},
        "https://api.github.com/repos/mitsugue/argus/actions/artifacts/1/archive")
    assert redirected is not None
    assert redirected.get_header("Authorization") == "Bearer secret"


def test_https_artifact_redirect_cannot_downgrade_transport():
    handler = release._StripCrossOriginAuthorization()
    request = release.urllib.request.Request(
        "https://api.github.com/repos/mitsugue/argus/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret"})
    with pytest.raises(ValueError, match="github_redirect_insecure"):
        handler.redirect_request(
            request, None, 302, "Found", {}, "http://example.invalid/file")


def test_detached_fetch_times_out_when_exact_artifact_is_missing(monkeypatch,
                                                                  tmp_path):
    install_fetch_mocks(monkeypatch, rows=[])
    with pytest.raises(ValueError, match="detached_certificate_artifact_not_ready"):
        release.fetch_admission(fetch_args(tmp_path))


def test_wrong_candidate_artifact_is_never_used_as_fallback(monkeypatch, tmp_path):
    wrong = artifact_row(workflow_run={
        "id": PRODUCER_RUN_ID,
        "head_sha": "d" * 40,
    })
    install_fetch_mocks(monkeypatch, rows=[wrong])
    with pytest.raises(ValueError, match="detached_certificate_artifact_not_ready"):
        release.fetch_admission(fetch_args(tmp_path))


def test_ambiguous_exact_artifacts_fail_closed(monkeypatch, tmp_path):
    install_fetch_mocks(monkeypatch, rows=[artifact_row(), artifact_row()])
    with pytest.raises(ValueError, match="detached_certificate_artifact_ambiguous:2"):
        release.fetch_admission(fetch_args(tmp_path))


@pytest.mark.parametrize(("archive", "error"), [
    (b"", "detached_certificate_archive_empty"),
    (b"not-a-zip", "detached_certificate_archive_invalid"),
    (certificate_archive({}, entry="other.json"),
     "detached_certificate_archive_shape:0"),
    (certificate_archive(b""), "detached_certificate_payload_empty"),
    (certificate_archive(b"{"), "detached_certificate_payload_malformed"),
])
def test_malformed_detached_archive_or_payload_fails_closed(
        monkeypatch, tmp_path, archive, error):
    install_fetch_mocks(monkeypatch, archive=archive)
    with pytest.raises(ValueError, match=error):
        release.fetch_admission(fetch_args(tmp_path))


@pytest.mark.parametrize("attack", ["digest", "candidate", "tree", "simulation"])
def test_certificate_identity_and_simulation_binding_fail_closed(
        monkeypatch, tmp_path, attack):
    value = admission_certificate()
    if attack == "digest":
        value["certificateDigest"] = "0" * 64
    elif attack == "candidate":
        value["candidate"]["commitSha"] = "d" * 40
        value = reseal(value)
    elif attack == "tree":
        value["candidate"]["treeSha"] = "d" * 40
        value = reseal(value)
    else:
        value["zeroInstallProofs"][1]["runtimeIdentityDigest"] = "d" * 64
        value = reseal(value)
    install_fetch_mocks(monkeypatch, archive=certificate_archive(value))
    with pytest.raises(ValueError, match="admission_certificate_identity_or_status"):
        release.fetch_admission(fetch_args(tmp_path))


@pytest.mark.parametrize("change", [
    {"conclusion": "failure"},
    {"event": "workflow_dispatch"},
    {"head_sha": "d" * 40},
    {"path": ".github/workflows/other.yml"},
])
def test_wrong_producer_run_identity_fails_closed(monkeypatch, tmp_path, change):
    install_fetch_mocks(monkeypatch, producer=producer_run(**change))
    with pytest.raises(ValueError, match="detached_certificate_producer_run_invalid"):
        release.fetch_admission(fetch_args(tmp_path))


def test_producer_and_consumer_must_be_genuinely_detached(monkeypatch, tmp_path):
    install_fetch_mocks(monkeypatch)
    with pytest.raises(ValueError, match="detached_certificate_not_detached"):
        release.fetch_admission(fetch_args(
            tmp_path, consumer_run_id=str(PRODUCER_RUN_ID)))


def test_artifact_archive_url_must_match_exact_artifact_identity(
        monkeypatch, tmp_path):
    install_fetch_mocks(monkeypatch, rows=[artifact_row(
        archive_download_url=f"https://api.github.com/repos/{REPOSITORY}/"
        "actions/artifacts/111/zip")])
    with pytest.raises(
            ValueError, match="detached_certificate_artifact_identity_invalid"):
        release.fetch_admission(fetch_args(tmp_path))


def test_retrieval_receipt_tamper_fails_closed(monkeypatch, tmp_path):
    install_fetch_mocks(monkeypatch)
    certificate, receipt = release.fetch_admission(fetch_args(tmp_path))
    receipt["certificateDigest"] = "0" * 64
    receipt.pop("receiptDigest")
    receipt["receiptDigest"] = hashlib.sha256(
        release._canonical(receipt)).hexdigest()
    path = tmp_path / "receipt.json"
    write_json(path, receipt)
    with pytest.raises(
            ValueError, match="detached_certificate_retrieval_receipt_invalid"):
        release._validate_retrieval_receipt(path, certificate, CANDIDATE)


def configure_verification_mocks(monkeypatch, *, mock_source=True):
    monkeypatch.setattr(release, "_ensure_clean_candidate", lambda: None)
    monkeypatch.setattr(release, "_candidate", lambda _ref: CANDIDATE)
    monkeypatch.setattr(release, "_validate_manifest", lambda: {})
    monkeypatch.setattr(release, "_validate_contract", lambda: {})
    monkeypatch.setattr(
        release, "_validate_product_semantic_diff", lambda _ref: SEMANTIC)
    if mock_source:
        monkeypatch.setattr(
            release.source_provenance, "validate_receipt",
            lambda *_args, **_kwargs: {"semanticDiff": SEMANTIC})
    monkeypatch.setattr(release, "_digest_file", lambda _path: "f" * 64)


def merge_bound_source_receipt(*, certificate_digest, merge_sha="d" * 40,
                               merge_tree=CANDIDATE["treeSha"]):
    value = {
        "schemaVersion": release.source_provenance.SCHEMA,
        "status": "PASS",
        "remote": {"name": "origin", "url": "https://github.com/mitsugue/argus"},
        "fetch": {
            "requestedCommitSha": release.ACCEPTED_V13_SOURCE,
            "fetchHeadCommitSha": release.ACCEPTED_V13_SOURCE,
            "depth": 1,
            "noTags": True,
            "sourcePresentBeforeFetch": False,
            "initialCheckoutShallow": True,
            "postFetchShallow": True,
        },
        "acceptedSource": {
            "commitSha": release.ACCEPTED_V13_SOURCE,
            "treeSha": release.ACCEPTED_V13_TREE,
        },
        "candidate": CANDIDATE,
        "releaseMerge": {
            "commitSha": merge_sha,
            "treeSha": merge_tree,
            "candidateParentSha": CANDIDATE["commitSha"],
        },
        "productVersion": release.PRODUCT_VERSION,
        "certificateDigest": certificate_digest,
        "acceptedFixManifestDigest": hashlib.sha256(
            release._canonical({})).hexdigest(),
        "semanticDiff": SEMANTIC,
    }
    value["provenanceDigest"] = hashlib.sha256(
        release._canonical(value)).hexdigest()
    return value


def run_shared_action_verify_block(tmp_path, *, merge_sha, merge_tree):
    root = Path(__file__).resolve().parent
    action = (root / ".github/actions/v13-5-pre-mutation-rehearsal/action.yml").read_text()
    block = action.split(
        "- name: Verify detached certificate against the admitted source and runtime",
        1)[1].split("    - uses: actions/setup-node@v5", 1)[0]
    block = block.split("      run: |", 1)[1]
    lines = block.splitlines()
    indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
    command = "\n".join(line[indent:] for line in lines if line.strip())
    capture = tmp_path / "capture.py"
    captured = tmp_path / "argv.json"
    capture.write_text(
        "import json,sys\n"
        f"open({str(captured)!r}, 'w').write(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8")
    command = command.replace(
        "python3 -B scripts/v13_5_release_certificate.py",
        f"python3 -B {capture}")
    replacements = {
        "certificate-path": "/proof/certificate.json",
        "candidate-sha": CANDIDATE["commitSha"],
        "runtime-proof-path": "/proof/runtime.json",
        "retrieval-receipt-path": "/proof/retrieval.json",
        "evidence-dir": "/proof/evidence",
        "release-merge-sha": merge_sha,
        "release-merge-tree": merge_tree,
    }
    for name, value in replacements.items():
        command = command.replace(f"${{{{ inputs.{name} }}}}", value)
    subprocess.run(["bash", "-eu", "-o", "pipefail", "-c", command], check=True)
    return json.loads(captured.read_text())


def test_exact_detached_producer_to_consumer_admission_passes(
        monkeypatch, tmp_path):
    calls = install_fetch_mocks(monkeypatch)
    certificate, receipt = release.fetch_admission(fetch_args(tmp_path))
    assert calls == [(
        f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/"
        f"{ARTIFACT_ID}/zip",
        {},
    )]
    certificate_path, receipt_path = tmp_path / "certificate.json", tmp_path / "receipt.json"
    runtime_path = tmp_path / "runtime.json"
    source_path = tmp_path / "source.json"
    write_json(certificate_path, certificate)
    write_json(receipt_path, receipt)
    write_json(runtime_path, runtime_proof())
    write_json(source_path, {})
    configure_verification_mocks(monkeypatch)
    admitted = release.verify_admission(argparse.Namespace(
        candidate_ref="HEAD",
        certificate=str(certificate_path),
        runtime_proof=str(runtime_path),
        retrieval_receipt=str(receipt_path),
        source_provenance=str(source_path),
        release_merge_sha="",
        release_merge_tree="",
    ))
    assert admitted["candidate"] == CANDIDATE
    assert admitted["certificateDigest"] == certificate["certificateDigest"]


def test_shared_action_forwards_both_release_merge_arguments(tmp_path):
    merge_sha = "d" * 40
    merge_tree = CANDIDATE["treeSha"]
    argv = run_shared_action_verify_block(
        tmp_path, merge_sha=merge_sha, merge_tree=merge_tree)
    assert argv[0] == "verify-admission"
    assert argv[argv.index("--release-merge-sha") + 1] == merge_sha
    assert argv[argv.index("--release-merge-tree") + 1] == merge_tree
    assert argv.count("--release-merge-sha") == 1
    assert argv.count("--release-merge-tree") == 1


@pytest.mark.parametrize(("merge_sha", "merge_tree", "receipt_sha",
                          "receipt_tree", "expected_error"), [
    ("", "", "d" * 40, CANDIDATE["treeSha"],
     "source_provenance_release_merge_mismatch"),
    ("d" * 40, "", "d" * 40, CANDIDATE["treeSha"],
     "release_merge_identity_incomplete"),
    ("", CANDIDATE["treeSha"], "d" * 40, CANDIDATE["treeSha"],
     "release_merge_identity_incomplete"),
    ("e" * 40, CANDIDATE["treeSha"], "d" * 40,
     CANDIDATE["treeSha"], "source_provenance_release_merge_mismatch"),
    ("d" * 40, "e" * 40, "d" * 40, CANDIDATE["treeSha"],
     "source_provenance_release_merge_mismatch"),
    ("d" * 40, CANDIDATE["treeSha"], "e" * 40,
     CANDIDATE["treeSha"], "source_provenance_release_merge_mismatch"),
    ("d" * 40, CANDIDATE["treeSha"], "d" * 40, "e" * 40,
     "source_provenance_release_merge_mismatch"),
    ("d" * 40, CANDIDATE["treeSha"], "d" * 40,
     CANDIDATE["treeSha"], None),
])
def test_merge_bound_admission_matrix(
        monkeypatch, tmp_path, merge_sha, merge_tree, receipt_sha,
        receipt_tree, expected_error):
    certificate = admission_certificate()
    certificate_path = tmp_path / "certificate.json"
    runtime_path = tmp_path / "runtime.json"
    source_path = tmp_path / "source.json"
    write_json(certificate_path, certificate)
    write_json(runtime_path, runtime_proof())
    write_json(source_path, merge_bound_source_receipt(
        certificate_digest=certificate["certificateDigest"],
        merge_sha=receipt_sha, merge_tree=receipt_tree))
    configure_verification_mocks(monkeypatch, mock_source=False)
    monkeypatch.setattr(
        release.source_provenance, "validate_product_semantic_diff",
        lambda *_args, **_kwargs: SEMANTIC)
    monkeypatch.setattr(
        release.source_provenance, "_manifest_identity", lambda _repo: {})
    args = argparse.Namespace(
        candidate_ref="HEAD", certificate=str(certificate_path),
        runtime_proof=str(runtime_path), retrieval_receipt="",
        source_provenance=str(source_path),
        release_merge_sha=merge_sha, release_merge_tree=merge_tree)
    if expected_error:
        with pytest.raises(ValueError, match=expected_error):
            release.verify_admission(args)
    else:
        admitted = release.verify_admission(args)
        assert admitted["candidate"] == CANDIDATE
        assert admitted["certificateDigest"] == certificate["certificateDigest"]


def test_wrong_runtime_identity_fails_after_detached_fetch(monkeypatch, tmp_path):
    certificate = admission_certificate()
    certificate_path, runtime_path = tmp_path / "certificate.json", tmp_path / "runtime.json"
    write_json(certificate_path, certificate)
    hostile = runtime_proof()
    hostile.pop("proofDigest")
    hostile["runtimeIdentity"]["browser"]["version"] = "999.0"
    hostile["runtimeIdentityDigest"] = hashlib.sha256(
        release._canonical(hostile["runtimeIdentity"])).hexdigest()
    hostile["proofDigest"] = hashlib.sha256(
        release._canonical(hostile)).hexdigest()
    write_json(runtime_path, hostile)
    source_path = tmp_path / "source.json"
    write_json(source_path, {})
    configure_verification_mocks(monkeypatch)
    with pytest.raises(
            ValueError, match="admission_certificate_runtime_identity_mismatch"):
        release.verify_admission(argparse.Namespace(
            candidate_ref="HEAD",
            certificate=str(certificate_path),
            runtime_proof=str(runtime_path),
            retrieval_receipt="",
            source_provenance=str(source_path),
            release_merge_sha="",
            release_merge_tree="",
        ))


def test_admission_without_source_provenance_fails_closed(
        monkeypatch, tmp_path):
    certificate_path = tmp_path / "certificate.json"
    runtime_path = tmp_path / "runtime.json"
    write_json(certificate_path, admission_certificate())
    write_json(runtime_path, runtime_proof())
    configure_verification_mocks(monkeypatch)
    with pytest.raises(ValueError, match="source_provenance_receipt_required"):
        release.verify_admission(argparse.Namespace(
            candidate_ref="HEAD",
            certificate=str(certificate_path),
            runtime_proof=str(runtime_path),
            retrieval_receipt="",
            source_provenance="",
            release_merge_sha="",
            release_merge_tree="",
        ))


def test_manifest_and_product_semantic_allowlist_are_closed():
    manifest = release._validate_manifest()
    names = {row["requirement"] for row in manifest["requirements"]}
    assert "productVersion = v13.5" in names
    assert "pre-merge detached runtime admission" in names
    assert "GitHub artifact JSON media and safe redirect transport" in names
    assert "mobile Today canonical projection-state acceptance" in names
    assert "warm cached projection semantic revalidation" in names
    assert "rollback restore has no browser dependency" in names
    assert "scanner.py" not in release.AUTHORIZED_EXTENSION_PATHS


def _simulation_payload(ordinal):
    return {
        "schemaVersion": "argus-v13-full-release-simulation-v1",
        "runNumber": ordinal,
        "status": "pass",
        "candidateSha": CANDIDATE["commitSha"],
        "initial": {"snapshotReady": 0, "snapshotExpected": 12},
        "infrastructure": {"pass": True},
        "trigger": {"status": "completed", "plan": [{}] * 12},
        "businessSnapshots": {"pass": True,
                              "expectedSet": [f"s{i}" for i in range(12)],
                              "observedSet": [f"s{i}" for i in range(12)]},
        "canonical": {"instrument": "1321", "horizon": "5D",
                      "responseSnapshotId": "vs-x", "uiSnapshotId": "vs-x"},
        "warmProfileSeal": {"status": "pass",
                            "productVersion": release.PRODUCT_VERSION},
        "independentProfileReopen": {"status": "pass"},
        "publicProductAcceptance": {"status": "pass"},
        "mobileAcceptance": {
            "status": "pass", "verdict": "PASS", "exitCode": 0,
            "frontendSha": CANDIDATE["commitSha"], "combinationCount": 12,
            "failures": [],
            "gateInventory": [{"id": f"M{i:02d}"} for i in range(1, 15)],
        },
    }


def test_simulation_requires_candidate_bound_mobile_acceptance(tmp_path):
    path = tmp_path / "simulation.json"
    write_json(path, _simulation_payload(1))
    assert release._validate_simulation(path, 1, CANDIDATE)["status"] == "pass"


@pytest.mark.parametrize("mutate", [
    lambda value: value.pop("mobileAcceptance"),
    lambda value: value["mobileAcceptance"].update(status="failure"),
    lambda value: value["mobileAcceptance"].update(verdict="FAIL"),
    lambda value: value["mobileAcceptance"].update(exitCode=1),
    lambda value: value["mobileAcceptance"].update(frontendSha="c" * 40),
    lambda value: value["mobileAcceptance"].update(combinationCount=11),
    lambda value: value["mobileAcceptance"].update(failures=["warm"]),
    lambda value: value["mobileAcceptance"].update(gateInventory=[]),
])
def test_simulation_without_full_mobile_acceptance_fails_closed(
        tmp_path, mutate):
    payload = _simulation_payload(1)
    mutate(payload)
    path = tmp_path / "simulation.json"
    write_json(path, payload)
    with pytest.raises(ValueError, match="full_release_simulation_1_invalid"):
        release._validate_simulation(path, 1, CANDIDATE)

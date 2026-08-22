#!/usr/bin/env python3
"""Acquire and admit the exact accepted V13 source for V13.5 release control.

The release starts from an intentionally shallow checkout.  This module always
asks the configured remote for the exact accepted commit, binds FETCH_HEAD to
that request, verifies its tree, and then performs the product semantic diff.
Pre-merge and production call this same implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import urllib.parse
from typing import Any, Dict, Mapping, Optional


SCHEMA = "argus-v13-5-source-provenance-v1"
PRODUCT_VERSION = "v13.5.13"
ACCEPTED_V13_SOURCE = "f79548bb274c5c5acc4075c181195834c252d54d"
ACCEPTED_V13_TREE = "bdba7c970872b92b88bc6e7cc7b0b8afe4785a96"
CANONICAL_REMOTE = "https://github.com/mitsugue/argus.git"
ROOT = pathlib.Path(__file__).resolve().parents[1]

AUTHORIZED_EXTENSION_PATHS = frozenset({
    # v13.5.13 owner-functional correction: compact iPhone navigation, concise
    # Japanese news projection, source-diverse market evidence, and semantic
    # de-duplication of recurring long-end-rate conditions.  Investment and
    # calibration authority stay outside this list and remain fail-closed.
    # owner-authorized path set for interaction performance (off-thread
    # verification, idle-sliced device ledger appends, keep-mounted Today),
    # the name-selector Today UX, the compact Seven Sign surface, the
    # market-shock (Major News) pipeline, the Prediction Ledger workflow
    # correction (canonical steps before private-store extras + precise
    # diagnostics), the checkpoint-v2 capacity budgets, and the v13.5.x
    # identity. The accepted baseline is the LIVE v13.5.0 release
    # (f79548bb…); anything outside this list fails the release closed.
    ".github/actions/v13-5-pre-mutation-rehearsal/action.yml",
    ".github/workflows/caos-scan.yml",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/market-public-acceptance.yml",
    ".github/workflows/news-intake-ops.yml",
    ".github/workflows/prediction-ledger.yml",
    ".github/workflows/release-gate.yml",
    "argus_causal_event_memory.py",
    "argus_checkpoint_v2.py",
    "argus_gmail_intake.py",
    "argus_market_shock.py",
    "argus_news_i18n.py",
    "argus_news_intelligence.py",
    "argus_route_catalog.py",
    "argus_today_headline.py",
    "backend-version.json",
    "bridge/moomoo_push.py",
    "docs/ARGUS_V13_5_4_CAUSAL_EVENT_MEMORY.md",
    "product-version.json",
    "release/v13-accepted-fix-manifest.json",
    "scanner.py",
    "scripts/checkpoint_v2_isolated_probe.py",
    "scripts/news_gmail_authorize.py",
    "scripts/normalized_hash_resource_probe.py",
    "scripts/v13_5_pre_mutation_rehearsal.py",
    "scripts/v13_5_release_certificate.py",
    "scripts/v13_5_source_provenance.py",
    "scripts/workflow_http.py",
    "test_argus_deploy_scope.py",
    "test_argus_causal_event_memory.py",
    "test_argus_causal_event_memory_backend.py",
    "test_argus_bridge_v1157.py",
    "test_argus_mission_tick_durability.py",
    "test_argus_sho_non_regression.py",
    "test_argus_gmail_intake.py",
    "test_argus_market_shock.py",
    "test_argus_news_i18n.py",
    "test_argus_news_intelligence.py",
    "test_argus_news_pipeline.py",
    "test_argus_notification_eligibility.py",
    "test_argus_public_operational_boundary.py",
    "test_argus_release_identity.py",
    "test_argus_v12_2_12.py",
    "test_argus_v12_4_0.py",
    "test_argus_v13_1_0.py",
    "test_caos_workflow_recovery.py",
    "test_remote_journal_rearm.py",
    "test_v13_5_release_certificate.py",
    "test_v13_5_pre_mutation_rehearsal.py",
    "test_v13_5_source_provenance.py",
    "test_verify_public_candidate_release.py",
    "web/package-lock.json",
    "web/package.json",
    "web/scripts/full-release-simulation.mjs",
    "web/scripts/argus-engine.test.cjs",
    "web/scripts/asset-desk.test.cjs",
    "web/scripts/causal-event-memory.test.mjs",
    "web/scripts/iphone-profile.mjs",
    "web/scripts/market-data-truth.test.cjs",
    "web/scripts/market-system-integrity.test.cjs",
    "web/scripts/mobile-today-acceptance.mjs",
    "web/scripts/mobile-today-integrity.test.mjs",
    "web/scripts/owner-functional-ui.test.mjs",
    "web/scripts/release-state-machine.mjs",
    "web/scripts/release-state-machine.test.mjs",
    "web/scripts/release-fixture-target.mjs",
    "web/scripts/acceptance-runtime.test.mjs",
    "web/scripts/round3-product-final.test.mjs",
    "web/scripts/runtime-version-truth.test.mjs",
    "web/scripts/today-benchmark.mjs",
    "web/src/App.tsx",
    "web/src/main.tsx",
    "web/vite.config.ts",
    "web/src/components/dashboard/MobileStickyCommand.css",
    "web/src/components/NavRail.css",
    "web/src/components/assetDesk/AssetDecisionCard.tsx",
    "web/src/components/assetDesk/AssetDecisionDetails.tsx",
    "web/src/components/assetDesk/AssetDecisionSummary.tsx",
    "web/src/components/assetDesk/AssetDesk.css",
    "web/src/components/assetDesk/AssetDeskList.tsx",
    "web/src/components/chart/ChartIntelligencePanel.css",
    "web/src/components/chart/ChartIntelligencePanel.tsx",
    "web/src/components/today/ArgusToday.css",
    "web/src/components/today/ArgusTodayPanel.tsx",
    "web/src/hooks/useAssetIntel.ts",
    "web/src/hooks/useChartIntelligence.ts",
    "web/src/hooks/useMarketNews.ts",
    "web/src/components/settings/NewsIntakePanel.tsx",
    "web/src/hooks/useMarketShock.ts",
    "web/src/hooks/useNewsIntelligence.ts",
    "web/src/hooks/useTodayHeadline.ts",
    "web/src/domain/assetDesk.ts",
    "web/src/domain/argusTodayView.ts",
    "web/src/lib/notifications.ts",
    "web/src/routes/Settings.tsx",
    "web/src/lib/sdaDeviceLocal.ts",
    "web/src/lib/todayHeadline.ts",
    "web/src/lib/verifiedSnapshot.ts",
    "web/src/lib/verify.worker.ts",
    "web/src/lib/verifyWorkerClient.ts",
    "web/src/routes/CommandCenter.tsx",
    "web/src/routes/PageShell.tsx",
    "web/src/routes/Watchlist.tsx",
    "web/src/types/assetItem.ts",
    # v13.5.13 owner spec conformance (2026-08-22): news-risk ⊥ market
    # confirmation, tri-state Action Priority context, honest probability-truth
    # evidence, the canonical artifact resolver boundary (backend
    # decision-evidence route + device resolver + SDA registration seam),
    # canonical candidateAction in issued decisions, and the encrypted-vault
    # ride-along for the append-only device SDA ledger.
    "argus_action_priority.py",
    "argus_single_decision.py",
    "argus_today_intelligence.py",
    "test_argus_action_priority.py",
    "test_argus_decision_evidence.py",
    "test_argus_market_truth_scanner.py",
    "test_argus_v12_rc.py",
    "web/scripts/backup-protection-contract.test.cjs",
    "web/scripts/canonical-decision-evidence.test.cjs",
    "web/scripts/device-local-sda-ledger.test.cjs",
    "web/src/domain/canonicalDecisionEvidence.ts",
    "web/src/domain/singleDecisionAuthority.ts",
    "web/src/hooks/useDecisionEvidence.ts",
    "web/src/lib/backup.ts",
})


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha256_hex(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_bytes(value)
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 40 \
        and all(character in "0123456789abcdef" for character in value)


def _load(path: pathlib.Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"source_provenance_json_invalid:{path}") from exc
    if type(value) is not dict:
        raise ValueError(f"source_provenance_json_object_required:{path}")
    return value


def _write(path: pathlib.Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")


def _git(repo: pathlib.Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise ValueError(f"git_{args[0].replace('-', '_')}_failed:{detail[:300]}")
    return result.stdout.strip() if result.returncode == 0 else ""


def _resolve(repo: pathlib.Path, ref: str, kind: str) -> str:
    if kind not in {"commit", "tree"}:
        raise ValueError("source_provenance_internal_kind")
    value = _git(repo, "rev-parse", "--verify", f"{ref}^{{{kind}}}")
    if not _is_sha(value):
        raise ValueError(f"{kind}_identity_invalid")
    return value


def _sanitize_remote(url: str) -> str:
    if url.startswith("git@github.com:"):
        return "https://github.com/" + url.split(":", 1)[1]
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme in {"http", "https"}:
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return urllib.parse.urlunsplit(
            (parsed.scheme, host + port, parsed.path, "", ""))
    return url


def _validate_remote(url: str, *, allow_local_remote: bool) -> str:
    clean = _sanitize_remote(url)
    normalized = clean[:-1] if clean.endswith("/") else clean
    canonical = CANONICAL_REMOTE[:-4] if CANONICAL_REMOTE.endswith(".git") \
        else CANONICAL_REMOTE
    candidate = normalized[:-4] if normalized.endswith(".git") else normalized
    if not allow_local_remote and candidate != canonical:
        raise ValueError(f"accepted_source_remote_mismatch:{clean}")
    return clean


def _certificate_identity(path: pathlib.Path) -> Dict[str, Any]:
    value = _load(path)
    digest = value.get("certificateDigest")
    body = dict(value)
    body.pop("certificateDigest", None)
    if type(digest) is not str or len(digest) != 64 \
            or digest != sha256_hex(body):
        raise ValueError("source_provenance_certificate_digest_invalid")
    return value


def _manifest_identity(repo: pathlib.Path) -> Dict[str, Any]:
    manifest = _load(repo / "release/v13-accepted-fix-manifest.json")
    source = manifest.get("canonicalSource")
    if type(source) is not dict or source.get("head") != ACCEPTED_V13_SOURCE \
            or source.get("tree") != ACCEPTED_V13_TREE:
        raise ValueError("accepted_source_authority_conflict")
    return manifest


def validate_product_semantic_diff(
        candidate_ref: str, *, repo: pathlib.Path = ROOT) -> Dict[str, Any]:
    accepted_commit = _resolve(repo, ACCEPTED_V13_SOURCE, "commit")
    accepted_tree = _resolve(repo, accepted_commit, "tree")
    if accepted_commit != ACCEPTED_V13_SOURCE:
        raise ValueError("accepted_v13_source_commit_mismatch")
    if accepted_tree != ACCEPTED_V13_TREE:
        raise ValueError("accepted_v13_source_tree_mismatch")
    candidate_commit = _resolve(repo, candidate_ref, "commit")
    changed = _git(repo, "diff", "--name-only", accepted_commit,
                   candidate_commit).splitlines()
    if len(changed) != len(set(changed)):
        raise ValueError("product_semantic_diff_duplicate_path")
    unauthorized = sorted(set(changed) - AUTHORIZED_EXTENSION_PATHS)
    if unauthorized:
        raise ValueError(
            "product_semantic_change_required:" + ",".join(unauthorized))
    return {
        "status": "PASS",
        "acceptedSource": accepted_commit,
        "acceptedTree": accepted_tree,
        "changedPaths": sorted(changed),
        "productSemanticChange": False,
    }


def acquire_source(
        *, repo: pathlib.Path, remote: str, accepted_source: str,
        accepted_tree: str, candidate_sha: str, candidate_tree: str,
        certificate_path: pathlib.Path, release_merge_sha: Optional[str] = None,
        release_merge_tree: Optional[str] = None,
        allow_local_remote: bool = False) -> Dict[str, Any]:
    repo = repo.resolve()
    if accepted_source != ACCEPTED_V13_SOURCE \
            or accepted_tree != ACCEPTED_V13_TREE:
        raise ValueError("accepted_source_authority_conflict")
    if not _is_sha(candidate_sha) or not _is_sha(candidate_tree):
        raise ValueError("candidate_identity_invalid")
    if (release_merge_sha is None) != (release_merge_tree is None):
        raise ValueError("release_merge_identity_incomplete")
    if release_merge_sha is not None \
            and (not _is_sha(release_merge_sha)
                 or not _is_sha(release_merge_tree)):
        raise ValueError("release_merge_identity_invalid")

    _manifest_identity(repo)
    product = _load(repo / "product-version.json")
    if product != {"schemaVersion": "argus-product-version-v1",
                   "productVersion": PRODUCT_VERSION}:
        raise ValueError("product_version_not_v13_5")
    certificate = _certificate_identity(certificate_path)
    if certificate.get("candidate") != {
            "commitSha": candidate_sha, "treeSha": candidate_tree}:
        raise ValueError("source_provenance_certificate_candidate_mismatch")
    if certificate.get("acceptedV13Source") != {
            "commitSha": accepted_source, "treeSha": accepted_tree}:
        raise ValueError("source_provenance_certificate_source_mismatch")
    if certificate.get("productVersion") != PRODUCT_VERSION:
        raise ValueError("source_provenance_certificate_product_mismatch")

    remote_url = _validate_remote(
        _git(repo, "remote", "get-url", remote),
        allow_local_remote=allow_local_remote)
    shallow_before = _git(repo, "rev-parse", "--is-shallow-repository") == "true"
    present_before = bool(_git(
        repo, "rev-parse", "--verify", f"{accepted_source}^{{commit}}",
        check=False))

    fetch = subprocess.run([
        "git", "fetch", "--force", "--no-tags", "--no-recurse-submodules",
        "--depth=1", remote, accepted_source,
    ], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
       check=False)
    if fetch.returncode != 0:
        detail = (fetch.stderr or fetch.stdout).strip().replace("\n", " ")
        raise ValueError(f"accepted_source_fetch_failed:{detail[:300]}")
    fetched_commit = _resolve(repo, "FETCH_HEAD", "commit")
    if fetched_commit != accepted_source:
        raise ValueError("accepted_source_fetch_head_mismatch")
    resolved_commit = _resolve(repo, accepted_source, "commit")
    if resolved_commit != accepted_source:
        raise ValueError("accepted_source_commit_mismatch")
    resolved_tree = _resolve(repo, resolved_commit, "tree")
    if resolved_tree != accepted_tree:
        raise ValueError("accepted_source_tree_mismatch")

    resolved_candidate = _resolve(repo, candidate_sha, "commit")
    resolved_candidate_tree = _resolve(repo, resolved_candidate, "tree")
    if resolved_candidate != candidate_sha:
        raise ValueError("candidate_commit_mismatch")
    if resolved_candidate_tree != candidate_tree:
        raise ValueError("candidate_tree_mismatch")

    release: Optional[Dict[str, Any]] = None
    if release_merge_sha is not None:
        resolved_release = _resolve(repo, release_merge_sha, "commit")
        resolved_release_tree = _resolve(repo, resolved_release, "tree")
        if resolved_release != release_merge_sha:
            raise ValueError("release_merge_commit_mismatch")
        if resolved_release_tree != release_merge_tree:
            raise ValueError("release_merge_tree_mismatch")
        if resolved_release_tree != candidate_tree:
            raise ValueError("release_merge_candidate_tree_mismatch")
        parents = _git(
            repo, "rev-list", "--parents", "-n", "1", resolved_release).split()
        if len(parents) != 3 or parents[0] != resolved_release \
                or parents[2] != candidate_sha:
            raise ValueError("release_merge_candidate_parent_mismatch")
        release = {"commitSha": resolved_release,
                   "treeSha": resolved_release_tree,
                   "candidateParentSha": parents[2]}

    semantic = validate_product_semantic_diff(candidate_sha, repo=repo)
    manifest = _manifest_identity(repo)
    body: Dict[str, Any] = {
        "schemaVersion": SCHEMA,
        "status": "PASS",
        "remote": {"name": remote, "url": remote_url},
        "fetch": {
            "requestedCommitSha": accepted_source,
            "fetchHeadCommitSha": fetched_commit,
            "depth": 1,
            "noTags": True,
            "sourcePresentBeforeFetch": present_before,
            "initialCheckoutShallow": shallow_before,
            "postFetchShallow": _git(
                repo, "rev-parse", "--is-shallow-repository") == "true",
        },
        "acceptedSource": {"commitSha": resolved_commit,
                           "treeSha": resolved_tree},
        "candidate": {"commitSha": resolved_candidate,
                      "treeSha": resolved_candidate_tree},
        "releaseMerge": release,
        "productVersion": PRODUCT_VERSION,
        "certificateDigest": certificate["certificateDigest"],
        "acceptedFixManifestDigest": sha256_hex(manifest),
        "semanticDiff": semantic,
    }
    body["provenanceDigest"] = sha256_hex(body)
    return body


def validate_receipt(
        value: Mapping[str, Any], *, candidate_sha: str, candidate_tree: str,
        certificate_digest: str, release_merge_sha: Optional[str] = None,
        release_merge_tree: Optional[str] = None,
        repo: pathlib.Path = ROOT) -> Dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("source_provenance_receipt_object_required")
    receipt = dict(value)
    digest = receipt.pop("provenanceDigest", None)
    expected_keys = {
        "schemaVersion", "status", "remote", "fetch", "acceptedSource",
        "candidate", "releaseMerge", "productVersion", "certificateDigest",
        "acceptedFixManifestDigest", "semanticDiff",
    }
    if set(receipt) != expected_keys or type(digest) is not str \
            or len(digest) != 64 or digest != sha256_hex(receipt) \
            or receipt.get("schemaVersion") != SCHEMA \
            or receipt.get("status") != "PASS" \
            or receipt.get("acceptedSource") != {
                "commitSha": ACCEPTED_V13_SOURCE,
                "treeSha": ACCEPTED_V13_TREE} \
            or receipt.get("candidate") != {
                "commitSha": candidate_sha, "treeSha": candidate_tree} \
            or receipt.get("productVersion") != PRODUCT_VERSION \
            or receipt.get("certificateDigest") != certificate_digest:
        raise ValueError("source_provenance_receipt_invalid")
    fetch = receipt.get("fetch")
    remote = receipt.get("remote")
    if type(fetch) is not dict or set(fetch) != {
            "requestedCommitSha", "fetchHeadCommitSha", "depth", "noTags",
            "sourcePresentBeforeFetch", "initialCheckoutShallow",
            "postFetchShallow"} \
            or fetch.get("requestedCommitSha") != ACCEPTED_V13_SOURCE \
            or fetch.get("fetchHeadCommitSha") != ACCEPTED_V13_SOURCE \
            or fetch.get("depth") != 1 or fetch.get("noTags") is not True \
            or type(fetch.get("sourcePresentBeforeFetch")) is not bool \
            or type(fetch.get("initialCheckoutShallow")) is not bool \
            or type(fetch.get("postFetchShallow")) is not bool \
            or type(remote) is not dict or set(remote) != {"name", "url"} \
            or remote.get("name") != "origin" \
            or _validate_remote(remote.get("url", ""), allow_local_remote=False) \
            != remote.get("url"):
        raise ValueError("source_provenance_fetch_receipt_invalid")
    expected_release = None
    if release_merge_sha is not None or release_merge_tree is not None:
        if release_merge_sha is None or release_merge_tree is None:
            raise ValueError("release_merge_identity_incomplete")
        expected_release = {"commitSha": release_merge_sha,
                            "treeSha": release_merge_tree,
                            "candidateParentSha": candidate_sha}
    if receipt.get("releaseMerge") != expected_release:
        raise ValueError("source_provenance_release_merge_mismatch")
    semantic = validate_product_semantic_diff(candidate_sha, repo=repo)
    if receipt.get("semanticDiff") != semantic:
        raise ValueError("source_provenance_semantic_diff_mismatch")
    if receipt.get("acceptedFixManifestDigest") != sha256_hex(
            _manifest_identity(repo)):
        raise ValueError("source_provenance_manifest_mismatch")
    receipt["provenanceDigest"] = digest
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--accepted-source", required=True)
    parser.add_argument("--accepted-tree", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--candidate-tree", required=True)
    parser.add_argument("--release-merge-sha", default="")
    parser.add_argument("--release-merge-tree", default="")
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    receipt = acquire_source(
        repo=pathlib.Path(args.repo_root), remote=args.remote,
        accepted_source=args.accepted_source, accepted_tree=args.accepted_tree,
        candidate_sha=args.candidate_sha, candidate_tree=args.candidate_tree,
        certificate_path=pathlib.Path(args.certificate),
        release_merge_sha=args.release_merge_sha or None,
        release_merge_tree=args.release_merge_tree or None)
    _write(pathlib.Path(args.out), receipt)
    print("V13_5_ACCEPTED_SOURCE_PROVENANCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

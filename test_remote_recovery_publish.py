"""Encrypted Remote Journal publication, routes, and immutable ACK tests."""
from __future__ import annotations

import copy
import concurrent.futures
import base64
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import textwrap
import types
from unittest import mock

import pytest

import argus_remote_journal as journal
import argus_remote_receipt_queue as receipt_queue
import argus_remote_recovery as recovery
import argus_state_journal
from scripts.prepare_remote_journal_publish import (
    inspect_sidecar,
    inspect_pair,
    main as publish_main,
    prepare_pair,
    verify_ledger_base_ancestor,
    verify_committed,
)


_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
import sys
sys.modules.setdefault("moomoo", _moomoo)
import scanner


BUILD = "b" * 40
BASE = "c" * 40
COMMIT = "d" * 40
AT = "2026-08-13T01:02:03Z"
TARGET = 4701
KEY_ID = "current-2026-08"
KEY = bytes(range(32))
CHECKPOINT_ID = "rcp-" + "e" * 32


def _event():
    return argus_state_journal.event(
        event_type="mission_completed", aggregate_type="mission",
        aggregate_id="publish-fixture", sequence=1, occurred_at=AT,
        payload={"missionType": "ordinary"})


def _pair(source_checkpoint_hash="f" * 64, *, generated_at=AT):
    event = _event()
    meta = {
        journal.OPS_SEQUENCE_HIGH_WATER_FIELD: 1,
    }
    section = journal.snapshot_journal_section(
        events=[event], meta=meta, compacted=[], now_iso=generated_at)
    durability = {
        "walAppliedSequence": TARGET,
        "remoteWalAppliedSequence": TARGET,
        "verifiedWalSequence": TARGET - 1,
    }
    compact = journal.build_compact_readback_snapshot(
        schema_version=journal.SCHEMA_V3,
        generated_at=generated_at, as_of=generated_at,
        build_identity={"appVersion": "13.4.13", "buildSha": BUILD},
        ops_journal=section["opsJournal"],
        integrity_manifest=section["integrityManifest"], outcomes=[],
        mission_tick_durability=durability,
        market_ledger_state_hash="1" * 16,
        chart_intelligence_state_hash="2" * 16,
        today_intelligence_state_hash="3" * 16,
        market_replay_state_hash="4" * 16)
    targets = {
        "opsJournal": copy.deepcopy(section["opsJournal"]),
        "opsJournalMeta": copy.deepcopy(meta),
        "opsJournalCompacted": [],
        "opsSequenceByAggregate": {"mission:publish-fixture": 1},
        "missions": [], "missionWindows": [], "forecasts": [],
        "outcomes": [], "incidents": [], "soak": {},
        "postmortems": [], "periodicReports": [], "challengerRuns": [],
        "agentQueue": {},
        "missionTickDurability": copy.deepcopy(durability),
    }
    nonce = secrets.token_bytes(12)
    payload = recovery.build_payload(
        compact_readback=compact, targets=targets, generated_at=generated_at,
        build_identity={"appVersion": "13.4.13", "buildSha": BUILD},
        source_checkpoint_hash=source_checkpoint_hash,
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_verified_at=generated_at,
        ledger_base_commit_sha=BASE,
        nonce_authority={
            "schemaVersion": recovery.NONCE_AUTHORITY_SCHEMA,
            "keyMaterialCounters": {
                recovery.nonce_material_domain(KEY):
                    int.from_bytes(nonce, "big"),
            },
        })
    envelope = recovery.encrypt_payload(
        payload, KEY, key_identifier=KEY_ID,
        nonce=nonce,
        generation_id="rrg-" + "a" * 32)
    return compact, recovery.build_sidecar(compact, envelope)


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")


def _rehash_public_envelope(sidecar):
    envelope = sidecar["recovery"]
    unsigned = {key: value for key, value in envelope.items()
                if key != "bundleHash"}
    envelope["bundleHash"] = hashlib.sha256(json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repository, check=True, capture_output=True,
        text=True)
    return completed.stdout.strip()


def test_recovery_base_may_be_ancestor_of_cas_head_but_not_sibling(tmp_path):
    repository = tmp_path / "ledger-repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "test")
    _git(repository, "config", "user.email", "test@example.invalid")
    (repository / "proof").write_text("C", encoding="utf-8")
    _git(repository, "add", "proof")
    _git(repository, "commit", "-m", "checkpoint base C")
    recovery_base = _git(repository, "rev-parse", "HEAD")

    (repository / "unrelated").write_text("X", encoding="utf-8")
    _git(repository, "add", "unrelated")
    _git(repository, "commit", "-m", "unrelated ledger commit X")
    cas_head = _git(repository, "rev-parse", "HEAD")
    verified = verify_ledger_base_ancestor(
        repository=repository, recovery_ledger_base=recovery_base,
        cas_ledger_head=cas_head)
    assert verified == {
        "status": "verified",
        "recoveryLedgerBase": recovery_base,
        "casLedgerHead": cas_head,
    }

    _git(repository, "checkout", "-b", "sibling", recovery_base)
    (repository / "sibling").write_text("Y", encoding="utf-8")
    _git(repository, "add", "sibling")
    _git(repository, "commit", "-m", "sibling Y")
    sibling = _git(repository, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="recovery_ledger_base_not_ancestor"):
        verify_ledger_base_ancestor(
            repository=repository, recovery_ledger_base=sibling,
            cas_ledger_head=cas_head)


def test_prepare_pair_is_exact_cas_bound_and_returns_only_public_metadata(
        tmp_path):
    compact, sidecar = _pair()
    source_readback = tmp_path / "source-readback.json"
    source_recovery = tmp_path / "source-recovery.json"
    ledger_readback = tmp_path / "ledger" / "osint" / "readback.json"
    ledger_recovery = tmp_path / "ledger" / "osint" / "recovery.json"
    _write(source_readback, compact)
    _write(source_recovery, sidecar)

    prepared = prepare_pair(
        source_readback=source_readback,
        source_recovery=source_recovery,
        ledger_readback=ledger_readback,
        ledger_recovery=ledger_recovery,
        ledger_base_commit_sha=BASE)
    assert prepared["status"] == "prepared"
    assert prepared["artifactMode"] == "encrypted_recovery_v1"
    assert prepared["recoveryBundleHash"] == sidecar["recovery"]["bundleHash"]
    envelope = sidecar["recovery"]
    assert envelope["keyDerivation"] == "HKDF-SHA-256"
    salt = envelope["keyDerivationSalt"]
    assert isinstance(salt, str) and len(salt) == 43 and "=" not in salt
    assert len(base64.urlsafe_b64decode(salt + "=")) == 32
    public_result = json.dumps(prepared)
    assert "ciphertext" not in public_result
    assert "keyDerivationSalt" not in public_result
    assert "nonceAuthority" not in public_result
    assert "targets" not in public_result
    assert json.loads(ledger_readback.read_text()) == compact
    assert json.loads(ledger_recovery.read_text()) == sidecar
    verified = verify_committed(
        readback_path=ledger_readback,
        expected_hash=prepared["expectedHash"],
        expected_receipt_hash=prepared["expectedReceiptHash"],
        recovery_path=ledger_recovery,
        expected_recovery_bundle_hash=prepared["recoveryBundleHash"],
        ledger_base_commit_sha=BASE)
    assert verified["artifactMode"] == "encrypted_recovery_v1"
    with pytest.raises(ValueError, match="recovery_ledger_base_commit_mismatch"):
        prepare_pair(
            source_readback=source_readback,
            source_recovery=source_recovery,
            ledger_readback=ledger_readback,
            ledger_recovery=ledger_recovery,
            ledger_base_commit_sha="0" * 40)


def test_endpoint_sidecar_probe_returns_only_scalar_public_identity(
        tmp_path, capsys):
    _compact, sidecar = _pair()
    recovery_path = tmp_path / "recovery.json"
    _write(recovery_path, sidecar)
    inspected = inspect_sidecar(recovery_path=recovery_path)
    assert inspected == {
        "status": "verified",
        "artifactMode": "encrypted_recovery_v1",
        "recoveryBundleHash": sidecar["recovery"]["bundleHash"],
        "recoveryGenerationId": sidecar["recovery"]["generationId"],
        "recoveryKeyId": KEY_ID,
        "ledgerBaseCommitSha": BASE,
    }
    encoded = json.dumps(inspected, sort_keys=True)
    for forbidden in (
            "ciphertext", "keyDerivationSalt", "nonceAuthority", "targets"):
        assert forbidden not in encoded

    assert publish_main([
        "validate-sidecar", "--recovery", str(recovery_path)]) == 0
    command_output = capsys.readouterr().out
    assert json.loads(command_output) == inspected
    for forbidden in (
            "ciphertext", "keyDerivationSalt", "nonceAuthority", "targets"):
        assert forbidden not in command_output


def test_publisher_rejects_pre_hkdf_unknown_or_wrong_kdf_contract(tmp_path):
    compact, original = _pair()
    source_readback = tmp_path / "readback.json"
    source_recovery = tmp_path / "recovery.json"
    _write(source_readback, compact)

    variants = []
    pre_hkdf = copy.deepcopy(original)
    pre_hkdf["recovery"].pop("keyDerivation")
    pre_hkdf["recovery"].pop("keyDerivationSalt")
    _rehash_public_envelope(pre_hkdf)
    variants.append(pre_hkdf)

    extra = copy.deepcopy(original)
    extra["recovery"]["unexpectedKdfField"] = "public-but-unknown"
    _rehash_public_envelope(extra)
    variants.append(extra)

    wrong = copy.deepcopy(original)
    wrong["recovery"]["keyDerivation"] = "PBKDF2-SHA-256"
    _rehash_public_envelope(wrong)
    variants.append(wrong)

    for sidecar in variants:
        _write(source_recovery, sidecar)
        with pytest.raises(ValueError, match="recovery_envelope_invalid"):
            prepare_pair(
                source_readback=source_readback,
                source_recovery=source_recovery,
                ledger_readback=tmp_path / "ledger-readback.json",
                ledger_recovery=tmp_path / "ledger-recovery.json",
                ledger_base_commit_sha=BASE)


def test_publisher_requires_canonical_32_byte_hkdf_salt(tmp_path):
    compact, original = _pair()
    source_readback = tmp_path / "readback.json"
    source_recovery = tmp_path / "recovery.json"
    _write(source_readback, compact)

    canonical = original["recovery"]["keyDerivationSalt"]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(canonical[-1])
    assert final_index % 4 == 0
    noncanonical_same_bytes = canonical[:-1] + alphabet[final_index + 1]
    assert base64.urlsafe_b64decode(noncanonical_same_bytes + "=") == \
        base64.urlsafe_b64decode(canonical + "=")
    malformed = (
        "",
        base64.urlsafe_b64encode(b"s" * 31).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"s" * 32).decode("ascii"),
        "+" + canonical[1:],
        noncanonical_same_bytes,
    )
    for salt in malformed:
        sidecar = copy.deepcopy(original)
        sidecar["recovery"]["keyDerivationSalt"] = salt
        _rehash_public_envelope(sidecar)
        _write(source_recovery, sidecar)
        with pytest.raises(
                ValueError, match="recovery_key_derivation_salt_invalid"):
            prepare_pair(
                source_readback=source_readback,
                source_recovery=source_recovery,
                ledger_readback=tmp_path / "ledger-readback.json",
                ledger_recovery=tmp_path / "ledger-recovery.json",
                ledger_base_commit_sha=BASE)


def test_publisher_bundle_hash_binds_valid_hkdf_salt_tamper(tmp_path):
    compact, sidecar = _pair()
    source_readback = tmp_path / "readback.json"
    source_recovery = tmp_path / "recovery.json"
    _write(source_readback, compact)
    tampered = copy.deepcopy(sidecar)
    tampered["recovery"]["keyDerivationSalt"] = base64.urlsafe_b64encode(
        b"different-public-derivation-salt"[:32]).decode("ascii").rstrip("=")
    assert len(tampered["recovery"]["keyDerivationSalt"]) == 43
    _write(source_recovery, tampered)
    with pytest.raises(ValueError, match="recovery_bundle_hash_mismatch"):
        prepare_pair(
            source_readback=source_readback,
            source_recovery=source_recovery,
            ledger_readback=tmp_path / "ledger-readback.json",
            ledger_recovery=tmp_path / "ledger-recovery.json",
            ledger_base_commit_sha=BASE)


def test_receipt_only_current_readback_publishes_missing_pair_once(tmp_path):
    compact, sidecar = _pair()
    source_readback = tmp_path / "source-readback.json"
    source_recovery = tmp_path / "source-recovery.json"
    ledger_readback = tmp_path / "ledger" / "osint" / "readback.json"
    ledger_recovery = tmp_path / "ledger" / "osint" / "recovery.json"
    _write(source_readback, compact)
    _write(source_recovery, sidecar)
    _write(ledger_readback, compact)

    repaired = prepare_pair(
        source_readback=source_readback,
        source_recovery=source_recovery,
        ledger_readback=ledger_readback,
        ledger_recovery=ledger_recovery,
        ledger_base_commit_sha=BASE)
    assert repaired["status"] == "prepared"
    assert repaired["recoveryPublished"] is True
    assert json.loads(ledger_recovery.read_text()) == sidecar

    replay = prepare_pair(
        source_readback=source_readback,
        source_recovery=source_recovery,
        ledger_readback=ledger_readback,
        ledger_recovery=ledger_recovery,
        ledger_base_commit_sha=BASE)
    assert replay["status"] == "already_committed"
    assert replay["recoveryPublished"] is False


def test_receipt_only_inspects_existing_pair_without_fresh_source_rewrite(
        tmp_path):
    existing_readback, existing_sidecar = _pair(generated_at=AT)
    source_readback, _ = _pair(
        source_checkpoint_hash="9" * 64,
        generated_at="2026-08-13T01:03:03Z")
    assert source_readback["missionTickDurability"] == \
        existing_readback["missionTickDurability"]
    assert source_readback["opsJournal"] == existing_readback["opsJournal"]
    assert source_readback["receiptHash"] != existing_readback["receiptHash"]

    ledger_readback = tmp_path / "ledger" / "osint" / "readback.json"
    ledger_recovery = tmp_path / "ledger" / "osint" / "recovery.json"
    _write(ledger_readback, existing_readback)
    _write(ledger_recovery, existing_sidecar)
    before_readback = ledger_readback.read_bytes()
    before_recovery = ledger_recovery.read_bytes()

    selected = inspect_pair(
        readback_path=ledger_readback, recovery_path=ledger_recovery)
    assert selected["status"] == "verified"
    assert selected["expectedReceiptHash"] == existing_readback["receiptHash"]
    assert selected["expectedReceiptHash"] != source_readback["receiptHash"]
    assert selected["readbackPublished"] is False
    assert selected["recoveryPublished"] is False
    assert ledger_readback.read_bytes() == before_readback
    assert ledger_recovery.read_bytes() == before_recovery


def test_pair_tamper_or_wrong_readback_is_fail_closed(tmp_path):
    compact, sidecar = _pair()
    source_readback = tmp_path / "readback.json"
    source_recovery = tmp_path / "recovery.json"
    ledger_readback = tmp_path / "ledger-readback.json"
    ledger_recovery = tmp_path / "ledger-recovery.json"
    _write(source_readback, compact)
    tampered = copy.deepcopy(sidecar)
    replacement = "A" if tampered["recovery"]["ciphertext"][0] != "A" else "B"
    tampered["recovery"]["ciphertext"] = (
        replacement + tampered["recovery"]["ciphertext"][1:])
    _write(source_recovery, tampered)
    with pytest.raises(ValueError, match="recovery_ciphertext_invalid"):
        prepare_pair(
            source_readback=source_readback,
            source_recovery=source_recovery,
            ledger_readback=ledger_readback,
            ledger_recovery=ledger_recovery,
            ledger_base_commit_sha=BASE)

    wrong = copy.deepcopy(compact)
    wrong["receiptHash"] = "0" * 16
    _write(source_readback, wrong)
    _write(source_recovery, sidecar)
    with pytest.raises(ValueError, match="compact_readback_not_verifiable"):
        prepare_pair(
            source_readback=source_readback,
            source_recovery=source_recovery,
            ledger_readback=ledger_readback,
            ledger_recovery=ledger_recovery,
            ledger_base_commit_sha=BASE)


def test_bounded_routes_require_auth_and_never_return_plaintext_error_detail():
    compact, sidecar = _pair()
    saved_token = scanner._ARGUS_ADMIN_TOKEN
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    try:
        client = scanner.app.test_client()
        assert client.get(
            "/api/argus/admin/remote-journal/recovery-sidecar"
        ).status_code == 401
        with mock.patch.dict(
                scanner._STARTUP, {"state": "ready"}), \
                mock.patch.dict(
                    scanner._OSINT_PERSIST_STATE, {"restored": True}), \
                mock.patch.dict(scanner._DURABLE_STATE, {
                    "lastRestoreAt": AT, "restoreSource": "persistent_local",
                }), \
                mock.patch.object(
                    scanner, "_osint_restore_once",
                    side_effect=AssertionError("endpoint restore forbidden")) \
                as restore, \
                mock.patch.object(
                    scanner, "_validated_local_recovery_export",
                    return_value=sidecar):
            public = client.get("/api/argus/osint/remote-readback")
            private = client.get(
                "/api/argus/admin/remote-journal/recovery-sidecar",
                headers={"X-ARGUS-ADMIN-TOKEN": "admin"})
        assert restore.call_count == 0
        assert public.status_code == 200 and public.get_json() == compact
        assert private.status_code == 200 and private.get_json() == sidecar

        failure = recovery.RecoveryBundleError(
            "recovery_authentication_failed_sensitive_context")
        with mock.patch.dict(
                scanner._STARTUP, {"state": "ready"}), \
                mock.patch.dict(
                    scanner._OSINT_PERSIST_STATE, {"restored": True}), \
                mock.patch.dict(scanner._DURABLE_STATE, {
                    "lastRestoreAt": AT, "restoreSource": "persistent_local",
                }), \
                mock.patch.object(
                    scanner, "_osint_restore_once",
                    side_effect=AssertionError("endpoint restore forbidden")) \
                as restore, \
                mock.patch.object(
                    scanner, "_validated_local_recovery_export",
                    side_effect=failure):
            response = client.get(
                "/api/argus/admin/remote-journal/recovery-sidecar",
                headers={"X-ARGUS-ADMIN-TOKEN": "admin"})
        assert restore.call_count == 0
        assert response.status_code == 503
        assert response.get_json() == {"ok": False, "status": "unavailable"}
        assert "sensitive_context" not in response.get_data(as_text=True)
    finally:
        scanner._ARGUS_ADMIN_TOKEN = saved_token


@pytest.mark.parametrize("startup_state", [
    "bootstrapping", "loading_local", "loading_remote", "reconciling",
    "failed_safe",
])
def test_recovery_export_routes_never_restore_without_boot_authority(
        startup_state):
    saved_token = scanner._ARGUS_ADMIN_TOKEN
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    try:
        client = scanner.app.test_client()
        with mock.patch.dict(
                scanner._STARTUP, {"state": startup_state}), \
                mock.patch.dict(
                    scanner._OSINT_PERSIST_STATE, {"restored": False}), \
                mock.patch.dict(scanner._DURABLE_STATE, {
                    "lastRestoreAt": None, "restoreSource": "none_available",
                }), \
                mock.patch.object(
                    scanner, "_osint_restore_once",
                    side_effect=AssertionError("endpoint restore forbidden")) \
                as restore, \
                mock.patch.object(
                    scanner, "_validated_local_recovery_export",
                    side_effect=AssertionError("export I/O forbidden")) \
                as exported:
            public = client.get("/api/argus/osint/remote-readback")
            private = client.get(
                "/api/argus/admin/remote-journal/recovery-sidecar",
                headers={"X-ARGUS-ADMIN-TOKEN": "admin"})
        assert public.status_code == 503
        assert private.status_code == 503
        assert public.get_json() == {"ok": False, "status": "unavailable"}
        assert private.get_json() == {"ok": False, "status": "unavailable"}
        assert restore.call_count == 0
        assert exported.call_count == 0
    finally:
        scanner._ARGUS_ADMIN_TOKEN = saved_token


def test_bounded_export_streams_exact_checkpoint_and_serializes_concurrent_gets(
        tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    sidecar_path = tmp_path / "recovery.json"
    encoded = json.dumps({
        "localCheckpointIntegrity": {"schemaVersion": "fixture"},
        "padding": "x" * (2 * 1024 * 1024),
        "remoteRecoveryRequired": {
            "schemaVersion": recovery.SIDECAR_SCHEMA,
            "mode": "encrypted_required", "keyId": KEY_ID,
            "checkpointId": CHECKPOINT_ID,
        },
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    checkpoint.write_bytes(encoded)
    compact, sidecar = _pair(hashlib.sha256(encoded).hexdigest())
    _write(sidecar_path, sidecar)
    keys = {"status": "configured",
            "current": {"keyId": KEY_ID, "key": KEY}, "previous": None}

    original_stream = scanner._stream_verified_recovery_checkpoint
    with mock.patch.object(scanner, "_OSINT_PERSIST_FILE", str(checkpoint)), \
            mock.patch.object(scanner, "_REMOTE_RECOVERY_FILE", str(sidecar_path)), \
            mock.patch.object(
                scanner, "_REMOTE_RECOVERY_EXPORT_ATTESTATION", None), \
            mock.patch.object(
                scanner.argus_remote_recovery, "configured_keys",
                return_value=keys), \
            mock.patch.object(
                scanner.argus_persistent_storage, "load_checkpoint",
                side_effect=AssertionError("full checkpoint load forbidden")), \
            mock.patch.object(
                scanner, "_stream_verified_recovery_checkpoint",
                wraps=original_stream) as streamed:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(
                lambda _index: scanner._validated_local_recovery_export(),
                range(3)))
    assert all(result["readback"] == compact for result in results)
    assert streamed.call_count == 1


def test_bounded_export_rejects_checkpoint_replacement_during_stream(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    replacement = tmp_path / "replacement.json"
    encoded = b"a" * (2 * 1024 * 1024)
    checkpoint.write_bytes(encoded)
    replacement.write_bytes(encoded)
    expected = hashlib.sha256(encoded).hexdigest()
    real_read = scanner.os.read
    reads = 0

    def replace_after_first_read(descriptor, size):
        nonlocal reads
        chunk = real_read(descriptor, size)
        reads += 1
        if reads == 1:
            replacement.replace(checkpoint)
        return chunk

    with mock.patch.object(scanner, "_OSINT_PERSIST_FILE", str(checkpoint)), \
            mock.patch.object(scanner.os, "read", replace_after_first_read):
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_export_checkpoint_changed"):
            scanner._stream_verified_recovery_checkpoint(expected)


def test_bounded_export_rejects_symlink_and_wrong_checkpoint_hash(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_bytes(b"{}")
    link = tmp_path / "checkpoint-link.json"
    link.symlink_to(checkpoint)

    with mock.patch.object(scanner, "_OSINT_PERSIST_FILE", str(link)):
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_export_checkpoint_symlink"):
            scanner._stream_verified_recovery_checkpoint(
                hashlib.sha256(b"{}").hexdigest())

    with mock.patch.object(scanner, "_OSINT_PERSIST_FILE", str(checkpoint)):
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_export_checkpoint_mismatch"):
            scanner._stream_verified_recovery_checkpoint("0" * 64)


def test_immutable_ack_fetches_and_authenticates_same_commit_pair():
    compact, sidecar = _pair()
    envelope = sidecar["recovery"]
    selected = {
        "remoteCommitSha": COMMIT,
        "targetWalSequence": TARGET,
        "expectedReceiptHash": compact["receiptHash"],
        "artifactMode": "encrypted_recovery_v1",
        "recoveryBundleHash": envelope["bundleHash"],
        "recoveryGenerationId": envelope["generationId"],
        "recoveryKeyId": envelope["keyId"],
        "ledgerBaseCommitSha": envelope["ledgerBaseCommitSha"],
    }

    def fetch(url, _maximum, name):
        assert COMMIT in url
        if name == "receipt_readback":
            return {"status": "present", "value": compact}
        assert name == "receipt_recovery"
        return {"status": "present", "value": sidecar}

    keys = {"status": "configured",
            "current": {"keyId": KEY_ID, "key": KEY}, "previous": None}
    with mock.patch.object(
            scanner, "_fetch_pinned_recovery_object", side_effect=fetch), \
            mock.patch.object(
                scanner.argus_remote_recovery, "configured_keys",
                return_value=keys), \
            mock.patch.object(
                scanner, "_bounded_ledger_commit_metadata",
                side_effect=[
                    {"sha": COMMIT, "parents": [BASE]},
                    {"sha": BASE, "parents": []},
                ]):
        assert scanner._verified_remote_receipt_artifact(selected) == compact

        wrong = dict(selected, recoveryBundleHash="0" * 64)
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="remote_receipt_recovery_metadata_mismatch"):
            scanner._verified_remote_receipt_artifact(wrong)


def test_immutable_ack_rejects_nonancestor_multiparent_and_stale_replay():
    compact, sidecar = _pair()
    envelope = sidecar["recovery"]
    selected = {
        "remoteCommitSha": COMMIT,
        "targetWalSequence": TARGET,
        "expectedReceiptHash": compact["receiptHash"],
        "artifactMode": "encrypted_recovery_v1",
        "recoveryBundleHash": envelope["bundleHash"],
        "recoveryGenerationId": envelope["generationId"],
        "recoveryKeyId": envelope["keyId"],
        "ledgerBaseCommitSha": envelope["ledgerBaseCommitSha"],
    }

    def fetch(_url, _maximum, name):
        return {"status": "present", "value":
                compact if name == "receipt_readback" else sidecar}

    keys = {"status": "configured",
            "current": {"keyId": KEY_ID, "key": KEY}, "previous": None}
    cases = [
        ([{"sha": COMMIT, "parents": ["e" * 40]},
          {"sha": "e" * 40, "parents": []}],
         "recovery_ledger_commit_nonancestor"),
        ([{"sha": COMMIT, "parents": [BASE, "e" * 40]}],
         "recovery_ledger_commit_multiparent"),
    ]
    for metadata, expected in cases:
        with mock.patch.object(
                scanner, "_fetch_pinned_recovery_object",
                side_effect=fetch), \
                mock.patch.object(
                    scanner.argus_remote_recovery, "configured_keys",
                    return_value=keys), \
                mock.patch.object(
                    scanner, "_bounded_ledger_commit_metadata",
                    side_effect=metadata):
            with pytest.raises(recovery.RecoveryBundleError, match=expected):
                scanner._verified_remote_receipt_artifact(selected)

    def linear_metadata(_owner, _repository, commit):
        value = int(commit, 16)
        return {"sha": commit,
                "parents": [f"{value - 1:040x}"] if value else []}

    stale = dict(selected, remoteCommitSha=f"{4:040x}")
    with mock.patch.object(
            scanner, "_fetch_pinned_recovery_object", side_effect=fetch), \
            mock.patch.object(
                scanner.argus_remote_recovery, "configured_keys",
                return_value=keys), \
            mock.patch.object(
                scanner, "_bounded_ledger_commit_metadata",
                side_effect=linear_metadata), \
            mock.patch.object(scanner, "_LEDGER_ANCESTRY_MAX_COMMITS", 2):
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_ledger_commit_stale_replay"):
            scanner._verified_remote_receipt_artifact(stale)


def test_commit_metadata_fetch_is_immutable_exact_and_bounded():
    response = types.SimpleNamespace(
        status_code=200,
        iter_content=lambda chunk_size: iter((json.dumps({
            "sha": COMMIT, "parents": [{"sha": BASE}],
        }).encode("utf-8"),)),
        close=lambda: None,
    )
    with mock.patch.object(scanner.requests, "get", return_value=response) as get:
        assert scanner._bounded_ledger_commit_metadata(
            "owner", "ledger", COMMIT) == {
                "sha": COMMIT, "parents": [BASE]}
    assert get.call_args.args[0] == (
        "https://api.github.com/repos/owner/ledger/git/commits/" + COMMIT)
    assert get.call_args.kwargs["stream"] is True

    oversized = types.SimpleNamespace(
        status_code=200,
        iter_content=lambda chunk_size: iter((b"x" * 17,)),
        close=lambda: None,
    )
    with mock.patch.object(scanner.requests, "get", return_value=oversized), \
            mock.patch.object(
                scanner, "_LEDGER_COMMIT_METADATA_MAX_BYTES", 16), \
            pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_ledger_commit_metadata_oversized"):
        scanner._bounded_ledger_commit_metadata("owner", "ledger", COMMIT)


def test_immutable_ack_rejects_bare_envelope_even_when_crypto_is_valid():
    compact, sidecar = _pair()
    envelope = sidecar["recovery"]
    selected = {
        "remoteCommitSha": COMMIT,
        "targetWalSequence": TARGET,
        "expectedReceiptHash": compact["receiptHash"],
        "artifactMode": "encrypted_recovery_v1",
        "recoveryBundleHash": envelope["bundleHash"],
        "recoveryGenerationId": envelope["generationId"],
        "recoveryKeyId": envelope["keyId"],
        "ledgerBaseCommitSha": envelope["ledgerBaseCommitSha"],
    }

    def fetch(_url, _maximum, name):
        return {"status": "present", "value":
                compact if name == "receipt_readback" else envelope}

    keys = {"status": "configured",
            "current": {"keyId": KEY_ID, "key": KEY}, "previous": None}
    with mock.patch.object(
            scanner, "_fetch_pinned_recovery_object", side_effect=fetch), \
            mock.patch.object(
                scanner.argus_remote_recovery, "configured_keys",
                return_value=keys), \
            pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_sidecar_schema_invalid"):
        scanner._verified_remote_receipt_artifact(selected)


def test_commit_receipt_requires_and_persists_exact_encrypted_artifact():
    compact, sidecar = _pair()
    envelope = sidecar["recovery"]
    saved_token = scanner._ARGUS_ADMIN_TOKEN
    saved_queue = copy.deepcopy(scanner._REMOTE_RECEIPT_QUEUE)
    scanner._ARGUS_ADMIN_TOKEN = "admin"
    scanner._REMOTE_RECEIPT_QUEUE = receipt_queue.empty_store()

    def persist(store):
        scanner._REMOTE_RECEIPT_QUEUE = copy.deepcopy(store)
        return {"verified": True, "readBackVerified": True}

    payload = {
        "remoteCommitSha": COMMIT,
        "expectedHash": compact["integrityManifest"]["manifestHash"],
        "expectedReceiptHash": compact["receiptHash"],
        "backendBuildSha": BUILD,
        "targetWalSequence": TARGET,
        "artifactMode": "encrypted_recovery_v1",
        "recoveryBundleHash": envelope["bundleHash"],
        "recoveryGenerationId": envelope["generationId"],
        "recoveryKeyId": envelope["keyId"],
        "ledgerBaseCommitSha": envelope["ledgerBaseCommitSha"],
    }
    keys = {"status": "configured",
            "current": {"keyId": KEY_ID, "key": KEY}, "previous": None}
    try:
        with mock.patch.object(scanner, "_backend_exact_sha", return_value=BUILD), \
                mock.patch.object(
                    scanner, "_persist_remote_receipt_queue",
                    side_effect=persist), \
                mock.patch.object(
                    scanner.argus_remote_recovery, "configured_keys",
                    return_value=keys):
            client = scanner.app.test_client()
            response = client.post(
                "/api/argus/admin/remote-journal/commit-receipt",
                headers={"X-ARGUS-ADMIN-TOKEN": "admin",
                         "Idempotency-Key": "recovery-pair-exact-0001"},
                json=payload)
            incomplete = dict(payload)
            incomplete.pop("recoveryBundleHash")
            rejected = client.post(
                "/api/argus/admin/remote-journal/commit-receipt",
                headers={"X-ARGUS-ADMIN-TOKEN": "admin",
                         "Idempotency-Key": "recovery-pair-exact-0002"},
                json=incomplete)
            wrong_key = dict(payload, recoveryKeyId="retired-key")
            wrong_key_response = client.post(
                "/api/argus/admin/remote-journal/commit-receipt",
                headers={"X-ARGUS-ADMIN-TOKEN": "admin",
                         "Idempotency-Key": "recovery-pair-exact-0003"},
                json=wrong_key)
        assert response.status_code == 202
        body = response.get_json()
        assert body["expectedReceiptHash"] == compact["receiptHash"]
        assert body["artifactMode"] == "encrypted_recovery_v1"
        assert body["recoveryBundleHash"] == envelope["bundleHash"]
        assert rejected.status_code == 400
        assert wrong_key_response.status_code == 409
        assert wrong_key_response.get_json()["error"] == \
            "recovery_key_id_unavailable"
        stored = scanner._REMOTE_RECEIPT_QUEUE["receipts"]
        assert len(stored) == 1
        assert stored[0]["remoteCommitSha"] == COMMIT
        assert stored[0]["recoveryGenerationId"] == envelope["generationId"]
    finally:
        scanner._ARGUS_ADMIN_TOKEN = saved_token
        scanner._REMOTE_RECEIPT_QUEUE = saved_queue


def test_dedicated_rearm_job_has_bounded_surface_and_one_write_maximum():
    workflow = Path(".github/workflows/caos-watchtower.yml").read_text()
    job = workflow.split("\n  remote-journal-rearm:\n", 1)[1]
    assert "/api/argus/osint/memory-snapshot" not in job
    assert "/caos-watchtower/refresh" not in job
    assert "translate-visible" not in job
    assert "/caos/patrol-health" not in job
    assert "/api/argus/osint/remote-readback" in job
    assert "/remote-journal/recovery-sidecar" in job
    assert "--max-filesize 1048576" in job
    assert "--max-filesize 8388608" in job
    assert job.count("origin HEAD:ledger") == 1
    assert job.count("--force-with-lease=refs/heads/ledger:") == 1
    assert job.count("/remote-journal/commit-receipt") == 1
    assert job.count("validate-sidecar") == 1
    assert "git pull --rebase" not in job
    assert "while true" not in job
    assert "refresh" not in job.lower()
    assert 'DECISION_ACTION" = "receipt_only"' in job
    inspect_at = job.index("inspect-pair")
    fallback_at = job.index("prepare-pair", inspect_at)
    push_at = job.index("origin HEAD:ledger", fallback_at)
    assert inspect_at < fallback_at < push_at
    assert 'PAIR_STATUS" = "verified"' in job
    assert 'PAIR_NEEDS_COMMIT" = "true"' in job
    assert "verify-ledger-base-ancestor" in job
    assert '--ledger-base-commit-sha "$RECOVERY_LEDGER_BASE"' in job
    assert '--cas-ledger-head "$LEDGER_CAS_BASE"' in job


def test_exact_4gib_encrypted_producer_probe_is_ci_wired_and_scalar_only():
    workflow = Path(".github/workflows/memory-attribution.yml").read_text(
        encoding="utf-8")
    assert workflow.count('"scripts/remote_recovery_resource_probe.py"') == 2
    assert workflow.count('"test_remote_recovery_producer.py"') == 2
    assert workflow.count('"test_remote_recovery_publish.py"') == 2

    job = workflow.split(
        "\n  linux-4gib-encrypted-recovery-producer:\n", 1)[1].split(
        "\n  linux-4gib-normalized-hash:\n", 1)[0]
    assert "--memory 4g --memory-swap 4g" in job
    assert "--require-cgroup-max-bytes 4294967296" in job
    assert "--cycles 8" in job
    assert "cryptography==49.0.0" in job
    assert "--quiet" in job
    assert "set(report) == allowed" in job
    assert '"single-process-temporary-production-path"' in job
    assert "type(report[key]) is bool" in job
    assert "type(value) is int" in job
    assert 'report["cgroupMaxBytes"] == 4294967296' in job
    assert 'report["uniqueNonceCount"] == 8' in job
    assert 'report["oomDelta"] == 0' in job
    assert 'report["oomKillDelta"] == 0' in job
    assert 'report["passed"] is True' in job
    assert "encrypted-recovery-resource-proof-${{ github.sha }}" in job
    assert job.count("if: always()") == 2

    probe_step = job.split(
        "- name: Eight-cycle encrypted producer proof in exact 4 GiB cgroup",
        1)[1].split("- name: Scalar artifact privacy and terminal gates", 1)[0]
    script = textwrap.dedent(probe_step.split("        run: |\n", 1)[1])
    checked = subprocess.run(
        ["bash", "-n"], input=script, text=True,
        capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr

    privacy_step = job.split(
        "- name: Scalar artifact privacy and terminal gates", 1)[1].split(
        "- name: Publish encrypted producer resource proof", 1)[0]
    privacy_script = textwrap.dedent(
        privacy_step.split("        run: |\n", 1)[1])
    checked = subprocess.run(
        ["bash", "-n"], input=privacy_script, text=True,
        capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr

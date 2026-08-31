"""Encrypted Remote Journal publication, routes, and immutable ACK tests."""
from __future__ import annotations

import copy
import concurrent.futures
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import pathlib
import secrets
import subprocess
import tempfile
import textwrap
import types
from unittest import mock

import pytest

import argus_persistent_storage as storage
import argus_remote_journal as journal
import argus_remote_receipt_queue as receipt_queue
import argus_remote_recovery as recovery
import argus_remote_recovery_limits as recovery_limits
import argus_state_journal
import argus_tick_durability as durability
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
from scripts import prepare_remote_journal_publish as publisher
from test_argus_persistent_mission_storage import scanner_storage
from test_remote_recovery_producer import (
    CURRENT_ID as PRODUCER_CURRENT_ID,
    CURRENT_KEY as PRODUCER_CURRENT_KEY,
    _activate_clean_legacy_nonce_authority,
    _append_verified_cycle,
    _key_environment,
    _reset_recovery_targets,
)


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


def _sized_compact_readback(target_bytes):
    """Build one schema-valid production-shaped proof at an exact size."""
    event = _event()
    meta = {journal.OPS_SEQUENCE_HIGH_WATER_FIELD: 1}
    section = journal.snapshot_journal_section(
        events=[event], meta=meta, compacted=[], now_iso=AT)
    durability = {
        "walAppliedSequence": TARGET,
        "remoteWalAppliedSequence": TARGET,
        "verifiedWalSequence": TARGET - 1,
    }
    history = [{
        "from": "unresolved_missing_price", "to": "retry_pending",
        "at": AT, "reason": "missing_price",
    }]
    outcome = {
        "id": "outcome-contract-proof",
        "status": "unresolved",
        "transitionHistory": history,
        "retainedEvidenceA": "",
        "retainedEvidenceB": "",
        "retainedEvidenceC": "",
    }

    def build():
        sealed = dict(outcome)
        sealed["integrityHash"] = journal._h(sealed)
        return journal.build_compact_readback_snapshot(
            schema_version=journal.SCHEMA_V3,
            generated_at=AT, as_of=AT,
            build_identity={"appVersion": "13.5.36", "buildSha": BUILD},
            ops_journal=section["opsJournal"],
            integrity_manifest=section["integrityManifest"],
            outcomes=[sealed], mission_tick_durability=durability,
            market_ledger_state_hash="1" * 16,
            chart_intelligence_state_hash="2" * 16,
            today_intelligence_state_hash="3" * 16,
            market_replay_state_hash="4" * 16)

    baseline = build()
    remaining = target_bytes - journal.compact_readback_serialized_size(
        baseline)
    assert remaining >= 0
    for name in (
            "retainedEvidenceA", "retainedEvidenceB", "retainedEvidenceC"):
        used = min(remaining, 900_000)
        outcome[name] = "x" * used
        remaining -= used
    assert remaining == 0
    exact = build()
    assert journal.compact_readback_serialized_size(exact) == target_bytes
    return exact


def _rehash_compact_readback(compact):
    for outcome in compact.get("outcomes") or []:
        body = {key: value for key, value in outcome.items()
                if key != "integrityHash"}
        outcome["integrityHash"] = journal._h(body)
    body = {key: value for key, value in compact.items()
            if key != "receiptHash"}
    compact["receiptHash"] = journal._h(body)
    return compact


def _minimal_targets_for_compact(compact):
    event = compact["opsJournal"][0]
    aggregate = f"{event['aggregateType']}:{event['aggregateId']}"
    sequence = int(event["sequence"])
    return {
        "opsJournal": copy.deepcopy(compact["opsJournal"]),
        "opsJournalMeta": {
            journal.OPS_SEQUENCE_HIGH_WATER_FIELD: sequence,
        },
        "opsJournalCompacted": [],
        "opsSequenceByAggregate": {aggregate: sequence},
        "missions": [], "missionWindows": [], "forecasts": [],
        "outcomes": copy.deepcopy(compact["outcomes"]),
        "incidents": [], "soak": {}, "postmortems": [],
        "periodicReports": [], "challengerRuns": [], "agentQueue": {},
        "missionTickDurability": copy.deepcopy(
            compact["missionTickDurability"]),
    }


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


def test_immutable_ack_rejects_nonancestor_multiparent_and_incomplete_path():
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
            mock.patch.object(
                scanner, "_LEDGER_ANCESTRY_FAST_PATH_COMMITS", 2), \
            mock.patch.object(
                scanner, "_bounded_ledger_compare",
                side_effect=recovery.RecoveryBundleError(
                    "recovery_ledger_commit_nonancestor")):
        with pytest.raises(
                recovery.RecoveryBundleError,
                match="recovery_ledger_commit_nonancestor"):
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
    assert "MAX_COMPACT_READBACK_BYTES" in job
    assert '--max-filesize "$READBACK_MAX_BYTES"' in job
    assert "--max-filesize 1048576" not in job
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


def test_compact_readback_contract_is_one_shared_finite_authority():
    assert journal.MAX_COMPACT_READBACK_BYTES == 1_572_864
    assert journal.MAX_COMPACT_READBACK_BYTES is \
        recovery_limits.MAX_COMPACT_READBACK_BYTES
    assert recovery.MAX_READBACK_BYTES is journal.MAX_COMPACT_READBACK_BYTES
    assert scanner._DURABLE_READBACK_MAX_BYTES is \
        journal.MAX_COMPACT_READBACK_BYTES
    assert publisher.MAX_READBACK_BYTES is \
        journal.MAX_COMPACT_READBACK_BYTES
    workflow = Path(".github/workflows/caos-watchtower.yml").read_text()
    assert workflow.count("MAX_COMPACT_READBACK_BYTES") == 2
    assert workflow.count('--max-filesize "$READBACK_MAX_BYTES"') == 2
    assert "--max-filesize 1048576" not in workflow


def test_exact_readback_limit_preserves_plaintext_and_sidecar_reserves():
    compact = _sized_compact_readback(journal.MAX_COMPACT_READBACK_BYTES)
    nonce = (1).to_bytes(12, "big")
    payload = recovery.build_payload(
        compact_readback=compact,
        targets=_minimal_targets_for_compact(compact), generated_at=AT,
        build_identity={"appVersion": "13.5.36", "buildSha": BUILD},
        source_checkpoint_hash="f" * 64, checkpoint_id=CHECKPOINT_ID,
        checkpoint_verified_at=AT, ledger_base_commit_sha=BASE,
        nonce_authority={
            "schemaVersion": recovery.NONCE_AUTHORITY_SCHEMA,
            "keyMaterialCounters": {
                recovery.nonce_material_domain(KEY): 1,
            },
        })
    assert len(recovery._canonical(payload)) <= recovery.MAX_PLAINTEXT_BYTES
    envelope = recovery.encrypt_payload(
        payload, KEY, key_identifier=KEY_ID, nonce=nonce,
        generation_id="rrg-" + "a" * 32)
    sidecar = recovery.build_sidecar(compact, envelope)
    assert len(recovery._canonical(sidecar)) <= recovery.MAX_SIDECAR_BYTES


def test_compact_readback_exact_limit_accepts_and_limit_plus_one_rejects():
    exact = _sized_compact_readback(journal.MAX_COMPACT_READBACK_BYTES)
    assert journal.verify_strict_compact_readback_snapshot(exact)

    oversized = copy.deepcopy(exact)
    oversized["outcomes"][0]["retainedEvidenceC"] += "x"
    _rehash_compact_readback(oversized)
    assert journal.compact_readback_serialized_size(oversized) == \
        journal.MAX_COMPACT_READBACK_BYTES + 1
    assert not journal.verify_compact_readback_snapshot(oversized)
    assert not journal.verify_strict_compact_readback_snapshot(oversized)


def test_observed_1065021_byte_legacy_readback_is_canonical_valid():
    observed = _sized_compact_readback(1_065_021)
    assert journal.compact_readback_serialized_size(observed) == 1_065_021
    assert journal.verify_strict_compact_readback_snapshot(observed)


def test_exact_4gib_encrypted_producer_probe_is_ci_wired_and_scalar_only():
    workflow = Path(".github/workflows/memory-attribution.yml").read_text(
        encoding="utf-8")
    assert workflow.count('"scripts/remote_recovery_resource_probe.py"') == 2
    assert workflow.count('"test_remote_recovery_producer.py"') == 2
    assert workflow.count('"test_remote_recovery_publish.py"') == 2

    job = workflow.split(
        "\n  linux-4gib-encrypted-recovery-producer:\n", 1)[1].split(
        "\n  linux-4gib-recovery-measurement:\n", 1)[0]
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


def test_exact_4gib_measurement_gate_is_ci_wired_no_swap_and_attributable():
    workflow = Path(".github/workflows/memory-attribution.yml").read_text(
        encoding="utf-8")
    job = workflow.split(
        "\n  linux-4gib-recovery-measurement:\n", 1)[1].split(
        "\n  linux-4gib-normalized-hash:\n", 1)[0]

    assert "--memory 4g --memory-swap 4g" in job
    assert 'memory.max)" = "4294967296"' in job
    assert 'memory.swap.max)" = "0"' in job
    assert "test_argus_recovery_phase_a_adapter.py" in job
    assert "scripts/recovery_measurement_benchmark.py" in job
    assert "scripts/recovery_measurement_retention_benchmark.py" in job
    assert "round1-workload-exit-code.txt" in job
    assert 'report["memoryMaxBytes"] == 4 * 1024 ** 3' in job
    assert 'report["swapMaxBytes"] == 0' in job
    assert 'report["workloadExitCode"] == 0' in job
    assert 'report["oomDelta"] == 0' in job
    assert 'report["oomKillDelta"] == 0' in job
    assert 'accounting.get("passed") is True' in job
    assert 'retention.get("passed") is True' in job
    assert "round1-recovery-measurement-proof-${{ github.sha }}" in job
    assert job.count("if: always()") == 2

    container_step = job.split(
        "- name: Measurement accounting and retention in exact 4 GiB cgroup",
        1)[1].split("- name: Exact-cgroup and benchmark terminal gates", 1)[0]
    container_script = textwrap.dedent(
        container_step.split("        run: |\n", 1)[1])
    checked = subprocess.run(
        ["bash", "-n"], input=container_script, text=True,
        capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr

    terminal_step = job.split(
        "- name: Exact-cgroup and benchmark terminal gates", 1)[1].split(
        "- name: Publish Round 1 measurement resource proof", 1)[0]
    terminal_script = textwrap.dedent(
        terminal_step.split("        run: |\n", 1)[1])
    checked = subprocess.run(
        ["bash", "-n"], input=terminal_script, text=True,
        capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr


def _checkpoint_v2_validator_source():
    workflow = Path(".github/workflows/checkpoint-v2-gate.yml").read_text(
        encoding="utf-8")
    marker = (
        "cat > artifacts/checkpoint-v2-isolated-proof-validator.py "
        "<<'PY'\n")
    embedded = workflow.split(marker, 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(embedded)


def _live_exact_report():
    original = 8_979
    rows = []
    for index in range(32):
        target = original + (index + 1) * 17
        rows.append({
            "cycle": index + 1,
            "fixtureProcessId": 20_000 + index,
            "originalSourceCursor": original,
            "childPid": 30_000 + index,
            "verified": True,
            "generationBytes": 331_776,
            "rowCount": 51,
            "sectionCount": 51,
            "walLowerSequence": target - 17,
            "walTargetSequence": target,
            "walReconstructedSequence": target,
            "walHashVerified": True,
            "walFramingVerified": True,
            "manifestPromoted": True,
            "childExitCode": 0,
            "pendingGenerationCount": 0,
            "retainedGenerationCount": min(index + 1, 4),
            "stagingOrphanCount": 0,
        })
    return {
        "schemaVersion":
            "argus-checkpoint-v2-isolated-32-cycle-proof-v1",
        "writerMode": "isolated_process",
        "cycles": 32,
        "parentPidUnchanged": True,
        "distinctChildProcessCount": 32,
        "distinctFixtureProcessCount": 32,
        "parentNeverLoadedGenerationSource": True,
        "allVerified": True,
        "allWalExact": True,
        "walStartSequence": rows[0]["walTargetSequence"],
        "walFinalSequence": rows[-1]["walTargetSequence"],
        "originalSourceCursor": original,
        "generationBytesMinimum": 331_776,
        "generationBytesMaximum": 331_776,
        "parentRssCycles3To32GrowthBytes": 1_048_576,
        "cgroupMemoryMax": 4 * 1024 ** 3,
        "cgroupLifetimePeakBytes": 512 * 1024 ** 2,
        "fdGrowth": 0,
        "threadGrowth": 0,
        "connectionGrowth": 0,
        "cursorGrowth": 0,
        "futureGrowth": 0,
        "zombieFree": True,
        "pendingMaximum": 0,
        "retainedMaximum": 4,
        "orphanMaximum": 0,
        "diskFreeMinimumBytes": 2 * 1024 ** 3,
        "cyclesEvidence": rows,
    }


def _production_shape_report():
    report = _live_exact_report()
    report["generationBytesMinimum"] = 144_048_128
    report["generationBytesMaximum"] = 144_048_128
    report["originalSourceCursor"] = 0
    report["walStartSequence"] = 5_017
    report["walFinalSequence"] = 5_017 + 31 * 17
    for index, row in enumerate(report["cyclesEvidence"]):
        target = 5_017 + index * 17
        row["originalSourceCursor"] = 0
        row["walLowerSequence"] = target - 17
        row["walTargetSequence"] = target
        row["walReconstructedSequence"] = target
        row["generationBytes"] = 144_048_128
        row["rowCount"] = 43_350
        row["sectionCount"] = 43
    return report


def _run_checkpoint_v2_validator(tmp_path, mode, report):
    proof = tmp_path / f"{mode}.json"
    proof.write_text(json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-B", "-", mode, str(proof)],
        input=_checkpoint_v2_validator_source(), text=True,
        capture_output=True, check=False)


def test_checkpoint_v2_workflow_separates_live_and_shape_without_gate_loss():
    workflow = Path(".github/workflows/checkpoint-v2-gate.yml").read_text(
        encoding="utf-8")
    isolated_job = workflow.split(
        "\n  isolated-writer-closure-32:\n", 1)[1]
    live_step = isolated_job.split(
        "- name: LIVE_EXACT_STATE 32-cycle fresh-process writer closure",
        1)[1].split(
        "- name: DETERMINISTIC_PRODUCTION_SHAPE 32-cycle threshold closure",
        1)[0]
    shape_step = isolated_job.split(
        "- name: DETERMINISTIC_PRODUCTION_SHAPE 32-cycle threshold closure",
        1)[1].split("- name: Publish isolated writer proof", 1)[0]
    exact_state_job = workflow.split(
        "\n  linux-4gib-cgroup:\n", 1)[1].split(
        "\n  mapping-attribution:\n", 1)[0]

    assert "--source-json artifacts/checkpoint-v2-exact-source.json" in \
        live_step
    assert "--cycles 32" in live_step
    assert "--assert-proof" not in live_step
    assert "LIVE_EXACT_STATE" in live_step
    assert "--source-json" not in shape_step
    assert "--cycles 32 --assert-proof" in shape_step
    assert "DETERMINISTIC_PRODUCTION_SHAPE" in shape_step
    assert "--memory 4g --memory-swap 4g" in live_step
    assert "--memory 4g --memory-swap 4g" in shape_step
    assert "--source-json artifacts/checkpoint-v2-exact-source.json" in \
        exact_state_job
    assert "--memory 4g --memory-swap 4g" in exact_state_job

    probe = Path("scripts/checkpoint_v2_isolated_probe.py").read_text(
        encoding="utf-8")
    assert "127 * 1024 ** 2" in probe
    assert "240 * 1024 ** 2" in probe
    assert "40_000 <= int(row[\"rowCount\"] or 0) <= 90_000" in probe
    assert "35 <= int(row[\"sectionCount\"] or 0) <= 55" in probe


def test_checkpoint_v2_live_exact_below_shape_is_accepted(tmp_path):
    completed = _run_checkpoint_v2_validator(
        tmp_path, "LIVE_EXACT_STATE", _live_exact_report())
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["passed"] is True
    assert result["generationBytesMinimum"] == 331_776
    assert result["rowCountMinimum"] == 51


@pytest.mark.parametrize(("case", "classification"), [
    ("wal", "isolated_live_or_shape_wal_contract_failed"),
    ("verification", "isolated_live_or_shape_32_cycles_unverified"),
    ("child", "isolated_live_or_shape_child_exit_failed"),
    ("zombie", "isolated_live_or_shape_parent_resource_leak"),
    ("orphan", "isolated_live_or_shape_parent_resource_leak"),
    ("pending", "isolated_live_or_shape_generation_retention_failed"),
    ("retention", "isolated_live_or_shape_generation_retention_failed"),
    ("cgroup", "isolated_live_or_shape_cgroup_resource_gate_failed"),
])
def test_checkpoint_v2_live_exact_defects_remain_fail_closed(
        tmp_path, case, classification):
    report = _live_exact_report()
    if case == "wal":
        report["allWalExact"] = False
    elif case == "verification":
        report["allVerified"] = False
    elif case == "child":
        report["cyclesEvidence"][0]["childExitCode"] = 1
    elif case == "zombie":
        report["zombieFree"] = False
    elif case == "orphan":
        report["orphanMaximum"] = 1
    elif case == "pending":
        report["pendingMaximum"] = 1
    elif case == "retention":
        report["retainedMaximum"] = 5
    elif case == "cgroup":
        report["cgroupMemoryMax"] = 0
    completed = _run_checkpoint_v2_validator(
        tmp_path, "LIVE_EXACT_STATE", report)
    assert completed.returncode != 0
    assert classification in completed.stderr


@pytest.mark.parametrize(("case", "classification"), [
    ("generation_below", "isolated_deterministic_generation_shape_failed"),
    ("generation_above", "isolated_deterministic_generation_shape_failed"),
    ("rows_below", "isolated_deterministic_row_shape_failed"),
    ("rows_above", "isolated_deterministic_row_shape_failed"),
    ("sections_below", "isolated_deterministic_section_shape_failed"),
    ("sections_above", "isolated_deterministic_section_shape_failed"),
])
def test_checkpoint_v2_deterministic_shape_thresholds_fail_closed(
        tmp_path, case, classification):
    report = _production_shape_report()
    if case == "generation_below":
        report["generationBytesMinimum"] = 133_169_151
    elif case == "generation_above":
        report["generationBytesMaximum"] = 251_658_241
    elif case == "rows_below":
        report["cyclesEvidence"][0]["rowCount"] = 39_999
    elif case == "rows_above":
        report["cyclesEvidence"][0]["rowCount"] = 90_001
    elif case == "sections_below":
        report["cyclesEvidence"][0]["sectionCount"] = 34
    elif case == "sections_above":
        report["cyclesEvidence"][0]["sectionCount"] = 56
    completed = _run_checkpoint_v2_validator(
        tmp_path, "DETERMINISTIC_PRODUCTION_SHAPE", report)
    assert completed.returncode != 0
    assert classification in completed.stderr


def test_checkpoint_v2_deterministic_shape_exact_boundaries_pass(tmp_path):
    report = _production_shape_report()
    report["generationBytesMinimum"] = 133_169_152
    report["generationBytesMaximum"] = 251_658_240
    report["cyclesEvidence"][0]["rowCount"] = 40_000
    report["cyclesEvidence"][1]["rowCount"] = 90_000
    report["cyclesEvidence"][0]["sectionCount"] = 35
    report["cyclesEvidence"][1]["sectionCount"] = 55
    completed = _run_checkpoint_v2_validator(
        tmp_path, "DETERMINISTIC_PRODUCTION_SHAPE", report)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["passed"] is True


@pytest.mark.parametrize(
    "failure_point",
    ("encrypt", "sidecar", "write", "pair", "installed_readback"),
)
def test_first_activation_sidecar_failure_preserves_legacy_authority(
        failure_point):
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths)
        _activate_clean_legacy_nonce_authority(paths)
        wal_before = pathlib.Path(paths["wal"]).read_bytes()
        checkpoint_before = pathlib.Path(paths["checkpoint"]).read_bytes()
        real_atomic_write = storage.atomic_write_json

        def fail_recovery_write(path, *args, **kwargs):
            if os.path.abspath(path) == os.path.abspath(paths["recovery"]):
                raise storage.PersistentStorageError(
                    "injected_recovery_write_failure")
            return real_atomic_write(path, *args, **kwargs)

        with contextlib.ExitStack() as stack:
            compact = stack.enter_context(mock.patch.object(
                durability, "compact_verified_wal",
                wraps=durability.compact_verified_wal))
            if failure_point == "encrypt":
                stack.enter_context(mock.patch.object(
                    recovery, "encrypt_payload",
                    side_effect=recovery.RecoveryBundleError(
                        "injected_encrypt_failure")))
            elif failure_point == "sidecar":
                stack.enter_context(mock.patch.object(
                    recovery, "build_sidecar",
                    side_effect=recovery.RecoveryBundleError(
                        "injected_sidecar_failure")))
            elif failure_point == "write":
                stack.enter_context(mock.patch.object(
                    storage, "atomic_write_json",
                    side_effect=fail_recovery_write))
            elif failure_point == "pair":
                stack.enter_context(mock.patch.object(
                    recovery, "validate_pair",
                    side_effect=recovery.RecoveryBundleError(
                        "injected_pair_failure")))
            else:
                stack.enter_context(mock.patch.object(
                    scanner, "_read_local_recovery_sidecar",
                    side_effect=ValueError(
                        "injected_installed_readback_failure")))
            with pytest.raises(
                    scanner._RemoteRecoveryCheckpointError,
                    match="remote_recovery_sidecar_failed"):
                scanner._osint_persist()

        assert compact.call_count == 0
        assert pathlib.Path(paths["wal"]).read_bytes() == wal_before
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == \
            checkpoint_before
        preserved = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        assert "remoteRecoveryRequired" not in preserved
        assert scanner._DURABLE_STATE["remoteRecoverySidecar"][
            "status"] == "failed"
        assert not scanner._DURABLE_STATE.get("quarantinedCheckpoint")


@pytest.mark.parametrize("boundary", (
    "after_marker_candidate_checkpoint",
    "after_encrypted_sidecar_creation",
    "after_complete_pair",
))
def test_first_activation_pair_crash_boundaries_restart_safely(boundary):
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths)
        _activate_clean_legacy_nonce_authority(paths)
        checkpoint_before = pathlib.Path(paths["checkpoint"]).read_bytes()
        wal_before = pathlib.Path(paths["wal"]).read_bytes()
        crashed = {"value": False}

        def inject(name):
            if name == boundary and not crashed["value"]:
                crashed["value"] = True
                raise RuntimeError(f"crash:{boundary}")

        with mock.patch.object(
                scanner, "_remote_recovery_crash_boundary",
                side_effect=inject):
            if boundary == "after_encrypted_sidecar_creation":
                with pytest.raises(
                        scanner._RemoteRecoveryCheckpointError,
                        match="remote_recovery_sidecar_failed"):
                    scanner._osint_persist()
            else:
                result = scanner._osint_persist()
                assert result["verified"] is False
        assert crashed["value"] is True
        assert pathlib.Path(paths["wal"]).read_bytes() == wal_before

        canonical = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        if boundary == "after_complete_pair":
            assert "remoteRecoveryRequired" in canonical
            scanner._verify_local_recovery_sidecar(
                canonical, allow_legacy_migration=False)
        else:
            assert pathlib.Path(paths["checkpoint"]).read_bytes() == \
                checkpoint_before
            assert "remoteRecoveryRequired" not in canonical

        restart = scanner._osint_persist()
        assert restart["verified"] is True
        installed = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        scanner._verify_local_recovery_sidecar(
            installed, allow_legacy_migration=False)
        history = scanner._verify_remote_recovery_nonce_authority(
            recovery.configured_keys())
        floor = history["keyMaterialCounters"][
            recovery.nonce_material_domain(PRODUCER_CURRENT_KEY)]
        assert floor >= (
            1 if boundary == "after_marker_candidate_checkpoint" else 2)
        assert scanner._DURABLE_STATE["integrityStatus"] == "ok"
        assert scanner._DURABLE_STATE["remoteRecoveryLocal"][
            "status"] == "verified"


_ORDINARY_PAIR_CRASH_BOUNDARIES = (
    "before_candidate_checkpoint_staging",
    "after_checkpoint_staging",
    "before_nonce_reservation",
    "after_nonce_reservation",
    "before_candidate_sidecar_write",
    "after_candidate_sidecar_write",
    "after_candidate_sidecar_fsync",
    "after_candidate_pair_verification",
    "before_pair_authority_switch",
    "after_pair_authority_switch",
    "before_pair_cleanup",
    "during_pair_cleanup",
)


def _raise_once_at_boundary(boundary):
    state = {"raised": False}

    def inject(name):
        if name == boundary and not state["raised"]:
            state["raised"] = True
            raise RuntimeError(f"crash:{boundary}")

    return state, inject


def _advance_nonce_floor_to_33():
    keys = recovery.configured_keys()
    domain = recovery.nonce_material_domain(PRODUCER_CURRENT_KEY)
    history = scanner._verify_remote_recovery_nonce_authority(keys)
    while int(history["keyMaterialCounters"].get(domain) or 0) < 33:
        scanner._reserve_remote_recovery_nonce(PRODUCER_CURRENT_ID)
        history = scanner._verify_remote_recovery_nonce_authority(keys)
    assert history["generation"] >= 33
    assert history["keyMaterialCounters"][domain] == 33
    return domain


@pytest.mark.parametrize("boundary", _ORDINARY_PAIR_CRASH_BOUNDARIES)
def test_ordinary_keyed_pair_crash_matrix_preserves_one_generation(boundary):
    before_switch = _ORDINARY_PAIR_CRASH_BOUNDARIES.index(boundary) <= 8
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths, sequence=1)
        _activate_clean_legacy_nonce_authority(paths)
        assert scanner._osint_persist()["verified"] is True
        old_checkpoint = pathlib.Path(paths["checkpoint"]).read_bytes()
        old_sidecar = pathlib.Path(paths["recovery"]).read_bytes()
        old_pair = scanner._read_local_recovery_sidecar()
        old_payload = recovery.validate_pair(
            old_pair["readback"], old_pair["recovery"],
            PRODUCER_CURRENT_KEY, key_identifier=PRODUCER_CURRENT_ID)
        domain = _advance_nonce_floor_to_33()
        _append_verified_cycle(paths, sequence=2)
        state, inject = _raise_once_at_boundary(boundary)

        with mock.patch.object(
                scanner, "_remote_recovery_crash_boundary",
                side_effect=inject):
            try:
                scanner._osint_persist()
            except scanner._RemoteRecoveryCheckpointError:
                pass
        assert state["raised"] is True

        canonical = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        authority = scanner._resolve_authoritative_local_recovery_checkpoint(
            canonical, paths["checkpoint"], recovery.configured_keys())
        selected = authority["checkpoint"]
        scanner._verify_local_recovery_sidecar(
            selected, allow_legacy_migration=False,
            sidecar_value=authority["sidecar"])
        if before_switch:
            assert pathlib.Path(paths["checkpoint"]).read_bytes() == \
                old_checkpoint
            assert pathlib.Path(paths["recovery"]).read_bytes() == old_sidecar
            assert authority["payload"]["sourceCheckpointHash"] == \
                old_payload["sourceCheckpointHash"]
        else:
            assert authority["payload"]["sourceCheckpointHash"] != \
                old_payload["sourceCheckpointHash"]
            assert authority["payload"]["targetWalSequence"] == 2
            assert pathlib.Path(scanner._recovery_checkpoint_generation_path(
                paths["checkpoint"], authority["payload"][
                    "sourceCheckpointHash"])).exists()
        history = scanner._verify_remote_recovery_nonce_authority(
            recovery.configured_keys())
        floor = history["keyMaterialCounters"][domain]
        assert floor == (33 if _ORDINARY_PAIR_CRASH_BOUNDARIES.index(
            boundary) <= 2 else 34)
        nonce = recovery._b64_decode(
            authority["sidecar"]["recovery"]["nonce"], "test_invalid")
        assert int.from_bytes(nonce, "big") <= floor


def test_unverified_ordinary_cycle_preserves_previous_authenticated_pair():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths, sequence=1)
        _activate_clean_legacy_nonce_authority(paths)
        assert scanner._osint_persist()["verified"] is True
        old_checkpoint = pathlib.Path(paths["checkpoint"]).read_bytes()
        old_sidecar = pathlib.Path(paths["recovery"]).read_bytes()
        domain = _advance_nonce_floor_to_33()
        durability.append_wal(
            paths["wal"], sequence=2, kind="journal_transition",
            job_id="producer-test", payload={"transitionId": "producer-2"},
            occurred_at=AT)
        scanner._REMOTE_CYCLE.update({
            "remoteCommitSha": None, "receiptCommitSha": None,
            "readBackVerified": False, "walReadBackVerified": False,
            "remoteDurabilityState": "not_started",
            "remoteWalAppliedSequence": 0, "verifiedWalSequence": 0,
            "compactReceiptHash": None,
        })

        with pytest.raises(
                scanner._RemoteRecoveryCheckpointError,
                match="remote_recovery_sidecar_failed"):
            scanner._osint_persist()
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == old_checkpoint
        assert pathlib.Path(paths["recovery"]).read_bytes() == old_sidecar
        canonical = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        authority = scanner._resolve_authoritative_local_recovery_checkpoint(
            canonical, paths["checkpoint"], recovery.configured_keys())
        assert authority["payload"]["targetWalSequence"] == 1
        history = scanner._verify_remote_recovery_nonce_authority(
            recovery.configured_keys())
        assert history["keyMaterialCounters"][domain] == 33


def test_ordinary_keyed_pair_success_switches_exact_next_generation():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths, sequence=1)
        _activate_clean_legacy_nonce_authority(paths)
        first = scanner._osint_persist()
        first_sidecar = scanner._read_local_recovery_sidecar()
        first_payload = recovery.validate_pair(
            first_sidecar["readback"], first_sidecar["recovery"],
            PRODUCER_CURRENT_KEY, key_identifier=PRODUCER_CURRENT_ID)
        domain = _advance_nonce_floor_to_33()
        _append_verified_cycle(paths, sequence=2)

        second = scanner._osint_persist()
        assert second["verified"] is True
        canonical = storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        authority = scanner._resolve_authoritative_local_recovery_checkpoint(
            canonical, paths["checkpoint"], recovery.configured_keys())
        assert authority["payload"]["sourceCheckpointHash"] == \
            second["snapshotHash"]
        assert authority["payload"]["targetWalSequence"] == 2
        assert authority["payload"]["sourceCheckpointHash"] != \
            first_payload["sourceCheckpointHash"]
        assert pathlib.Path(scanner._recovery_checkpoint_generation_path(
            paths["checkpoint"], first_payload[
                "sourceCheckpointHash"])).exists()
        assert pathlib.Path(scanner._recovery_checkpoint_generation_path(
            paths["checkpoint"], second["snapshotHash"])).exists()
        history = scanner._verify_remote_recovery_nonce_authority(
            recovery.configured_keys())
        assert history["keyMaterialCounters"][domain] == 34


def test_failed_first_activation_never_projects_attempt_as_success():
    with tempfile.TemporaryDirectory() as root, scanner_storage(root) as paths, \
            _key_environment(configured=True), \
            mock.patch.object(scanner, "_CHECKPOINT_V2_STAGE1_ENABLED", False):
        _reset_recovery_targets()
        _append_verified_cycle(paths)
        _activate_clean_legacy_nonce_authority(paths)
        prior_success = "2026-08-12T23:59:00Z"
        scanner._DURABLE_STATE["lastSuccessAt"] = prior_success
        checkpoint_before = pathlib.Path(paths["checkpoint"]).read_bytes()
        captured = {}

        def fail_after_capture(checkpoint, *, checkpoint_path=None,
                               authenticated_remote_floor=None):
            candidate = storage.load_checkpoint(
                checkpoint_path, require_seal=True)
            captured.update(candidate["checkpointFailureHistory"])
            raise scanner._RemoteRecoveryCheckpointError(
                "injected_sidecar_failure")

        with mock.patch.object(
                scanner, "_persist_remote_recovery_sidecar",
                side_effect=fail_after_capture), pytest.raises(
                    scanner._RemoteRecoveryCheckpointError,
                    match="injected_sidecar_failure"):
            scanner._osint_persist()

        assert captured["lastSuccessAt"] == prior_success
        assert scanner._DURABLE_STATE["lastSuccessAt"] == prior_success
        assert pathlib.Path(paths["checkpoint"]).read_bytes() == \
            checkpoint_before
        assert "remoteRecoveryRequired" not in storage.load_checkpoint(
            paths["checkpoint"], require_seal=True)
        assert PRODUCER_CURRENT_ID == recovery.configured_keys()[
            "current"]["keyId"]

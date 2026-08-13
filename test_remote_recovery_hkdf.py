"""Per-envelope HKDF isolation and fail-closed recovery crypto tests."""
from __future__ import annotations

import copy
import hashlib
from unittest import mock

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import argus_remote_recovery as recovery
from test_remote_recovery_publish import (
    KEY as CURRENT_ROOT,
    KEY_ID as CURRENT_ID,
    _pair,
)


PREVIOUS_ROOT = bytes(reversed(range(32)))
PREVIOUS_ID = "previous-hkdf-v1"
GENERATION_ID = "rrg-" + "7" * 32


def _fixture():
    compact, sidecar = _pair()
    envelope = sidecar["recovery"]
    payload = recovery.decrypt_envelope(
        envelope, CURRENT_ROOT, key_identifier=CURRENT_ID)
    nonce = recovery._b64_decode(envelope["nonce"], "test_nonce_invalid")
    return compact, payload, nonce


def _rehash(envelope):
    envelope["bundleHash"] = recovery._hash({
        key: value for key, value in envelope.items()
        if key != "bundleHash"
    })
    return envelope


def _for_root(payload, root_key, nonce):
    changed = copy.deepcopy(payload)
    changed["nonceAuthority"]["keyMaterialCounters"][
        recovery.nonce_material_domain(root_key)] = int.from_bytes(
            nonce, "big")
    changed["payloadHash"] = recovery._hash({
        key: value for key, value in changed.items()
        if key != "payloadHash"
    })
    return recovery.validate_payload(changed)


def test_same_checkpoint_and_nonce_use_fresh_salt_and_distinct_data_keys():
    _, payload, nonce = _fixture()
    salt_one = b"\x91" * recovery.KEY_DERIVATION_SALT_BYTES
    salt_two = b"\xa2" * recovery.KEY_DERIVATION_SALT_BYTES
    real_aesgcm = recovery.AESGCM
    used_keys = []

    def capture_data_key(key):
        used_keys.append(key)
        return real_aesgcm(key)

    with mock.patch.object(
            recovery.secrets, "token_bytes",
            side_effect=(salt_one, salt_two)) as random_salt, \
            mock.patch.object(
                recovery, "AESGCM", side_effect=capture_data_key):
        first = recovery.encrypt_payload(
            payload, CURRENT_ROOT, key_identifier=CURRENT_ID,
            nonce=nonce, generation_id=GENERATION_ID)
        second = recovery.encrypt_payload(
            payload, CURRENT_ROOT, key_identifier=CURRENT_ID,
            nonce=nonce, generation_id=GENERATION_ID)

    assert random_salt.call_args_list == [
        mock.call(recovery.KEY_DERIVATION_SALT_BYTES),
        mock.call(recovery.KEY_DERIVATION_SALT_BYTES),
    ]
    assert first["keyDerivation"] == recovery.KEY_DERIVATION
    assert recovery._b64_decode(
        first["keyDerivationSalt"], "test_salt_invalid") == salt_one
    assert recovery._b64_decode(
        second["keyDerivationSalt"], "test_salt_invalid") == salt_two
    assert first["nonce"] == second["nonce"]
    assert first["checkpointId"] == second["checkpointId"]
    assert first["ciphertext"] != second["ciphertext"]
    assert len(used_keys) == 2
    assert used_keys[0] != used_keys[1]
    assert all(len(key) == 32 and key != CURRENT_ROOT for key in used_keys)
    assert recovery.decrypt_envelope(
        first, CURRENT_ROOT, key_identifier=CURRENT_ID) == payload
    assert recovery.decrypt_envelope(
        second, CURRENT_ROOT, key_identifier=CURRENT_ID) == payload


def test_hkdf_uses_sha256_root_salt_and_domain_separated_info():
    _, payload, nonce = _fixture()
    salt = bytes(range(recovery.KEY_DERIVATION_SALT_BYTES))
    real_aesgcm = recovery.AESGCM
    used_keys = []

    def capture_data_key(key):
        used_keys.append(key)
        return real_aesgcm(key)

    with mock.patch.object(
            recovery.secrets, "token_bytes", return_value=salt), \
            mock.patch.object(
                recovery, "AESGCM", side_effect=capture_data_key):
        envelope = recovery.encrypt_payload(
            payload, CURRENT_ROOT, key_identifier=CURRENT_ID,
            nonce=nonce, generation_id=GENERATION_ID)

    header = {key: envelope[key] for key in (
        "schemaVersion", "algorithm", "keyDerivation",
        "keyDerivationSalt", "generatedAt", "buildIdentity",
        "targetWalSequence", "compactReceiptHash", "checkpointVerifiedAt",
        "checkpointId", "ledgerBaseCommitSha", "keyId", "generationId")}
    expected = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt,
        info=recovery._hkdf_info(header)).derive(CURRENT_ROOT)
    assert used_keys == [expected]
    assert recovery.HKDF_INFO_DOMAIN in recovery._hkdf_info(header)
    assert payload["checkpointId"].encode("ascii") in \
        recovery._hkdf_info(header)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("checkpointId", "rcp-" + "8" * 32),
        ("ledgerBaseCommitSha", "9" * 40),
        ("targetWalSequence", 999_999),
    ),
)
def test_semantic_header_tamper_is_authenticated(field, replacement):
    _, sidecar = _pair()
    envelope = copy.deepcopy(sidecar["recovery"])
    envelope[field] = replacement
    _rehash(envelope)
    with pytest.raises(
            recovery.RecoveryBundleError,
            match="recovery_authentication_failed"):
        recovery.decrypt_envelope(
            envelope, CURRENT_ROOT, key_identifier=CURRENT_ID)


def test_salt_tamper_changes_derived_key_and_fails_authentication():
    _, sidecar = _pair()
    envelope = copy.deepcopy(sidecar["recovery"])
    salt = bytearray(recovery._decode_key_derivation_salt(
        envelope["keyDerivationSalt"]))
    salt[0] ^= 0x80
    envelope["keyDerivationSalt"] = recovery._b64_encode(bytes(salt))
    _rehash(envelope)
    with pytest.raises(
            recovery.RecoveryBundleError,
            match="recovery_authentication_failed"):
        recovery.decrypt_envelope(
            envelope, CURRENT_ROOT, key_identifier=CURRENT_ID)


@pytest.mark.parametrize(
    "salt",
    (
        "not!base64",
        recovery._b64_encode(b"s" * 31),
        recovery._b64_encode(b"s" * 33),
        recovery._b64_encode(b"s" * 32) + "=",
    ),
)
def test_malformed_or_noncanonical_kdf_salt_fails_closed(salt):
    _, sidecar = _pair()
    envelope = copy.deepcopy(sidecar["recovery"])
    envelope["keyDerivationSalt"] = salt
    _rehash(envelope)
    with pytest.raises(
            recovery.RecoveryBundleError,
            match="recovery_key_derivation_salt_invalid"):
        recovery.decrypt_envelope(
            envelope, CURRENT_ROOT, key_identifier=CURRENT_ID)


def test_missing_or_unknown_kdf_contract_fails_before_decryption():
    _, sidecar = _pair()
    missing = copy.deepcopy(sidecar["recovery"])
    missing.pop("keyDerivation")
    _rehash(missing)
    with pytest.raises(
            recovery.RecoveryBundleError, match="recovery_envelope_invalid"):
        recovery.decrypt_envelope(
            missing, CURRENT_ROOT, key_identifier=CURRENT_ID)

    unknown = copy.deepcopy(sidecar["recovery"])
    unknown["keyDerivation"] = "PBKDF2-SHA-256"
    _rehash(unknown)
    with pytest.raises(
            recovery.RecoveryBundleError, match="recovery_envelope_invalid"):
        recovery.decrypt_envelope(
            unknown, CURRENT_ROOT, key_identifier=CURRENT_ID)


def test_direct_root_key_ciphertext_is_never_accepted_as_hkdf_envelope():
    _, payload, nonce = _fixture()
    envelope = recovery.encrypt_payload(
        payload, CURRENT_ROOT, key_identifier=CURRENT_ID,
        nonce=nonce, generation_id=GENERATION_ID)
    header = {key: envelope[key] for key in (
        "schemaVersion", "algorithm", "keyDerivation",
        "keyDerivationSalt", "generatedAt", "buildIdentity",
        "targetWalSequence", "compactReceiptHash", "checkpointVerifiedAt",
        "checkpointId", "ledgerBaseCommitSha", "keyId", "generationId")}
    direct_ciphertext = AESGCM(CURRENT_ROOT).encrypt(
        nonce, recovery._padded_plaintext(payload), recovery._aad(header))
    envelope["ciphertext"] = recovery._b64_encode(direct_ciphertext)
    envelope["ciphertextSha256"] = hashlib.sha256(
        direct_ciphertext).hexdigest()
    _rehash(envelope)
    with pytest.raises(
            recovery.RecoveryBundleError,
            match="recovery_authentication_failed"):
        recovery.decrypt_envelope(
            envelope, CURRENT_ROOT, key_identifier=CURRENT_ID)


def test_previous_root_is_decrypt_only_compatible_and_selection_is_exact():
    _, payload, nonce = _fixture()
    previous_payload = _for_root(payload, PREVIOUS_ROOT, nonce)
    previous_envelope = recovery.encrypt_payload(
        previous_payload, PREVIOUS_ROOT, key_identifier=PREVIOUS_ID,
        nonce=nonce, generation_id=GENERATION_ID)
    configured = {
        "status": "configured",
        "current": {"keyId": CURRENT_ID, "key": CURRENT_ROOT},
        "previous": {"keyId": PREVIOUS_ID, "key": PREVIOUS_ROOT},
    }
    assert recovery.decrypt_configured(
        previous_envelope, configured) == previous_payload

    wrong_exact_slot = copy.deepcopy(configured)
    wrong_exact_slot["previous"]["key"] = b"\xff" * 32
    with pytest.raises(
            recovery.RecoveryBundleError,
            match="recovery_authentication_failed"):
        recovery.decrypt_configured(previous_envelope, wrong_exact_slot)


def test_kdf_info_separates_every_semantic_context_even_with_same_salt():
    _, sidecar = _pair()
    envelope = sidecar["recovery"]
    header = {key: envelope[key] for key in (
        "schemaVersion", "algorithm", "keyDerivation",
        "keyDerivationSalt", "generatedAt", "buildIdentity",
        "targetWalSequence", "compactReceiptHash", "checkpointVerifiedAt",
        "checkpointId", "ledgerBaseCommitSha", "keyId", "generationId")}
    original = recovery._derive_data_key(CURRENT_ROOT, header)

    renamed = copy.deepcopy(header)
    renamed["keyId"] = "renamed-hkdf-v1"
    other_checkpoint = copy.deepcopy(header)
    other_checkpoint["checkpointId"] = "rcp-" + "6" * 32
    other_generation = copy.deepcopy(header)
    other_generation["generationId"] = "rrg-" + "5" * 32
    other_ledger = copy.deepcopy(header)
    other_ledger["ledgerBaseCommitSha"] = "4" * 40
    other_wal = copy.deepcopy(header)
    other_wal["targetWalSequence"] += 1
    assert recovery._derive_data_key(CURRENT_ROOT, renamed) != original
    assert recovery._derive_data_key(
        CURRENT_ROOT, other_checkpoint) != original
    assert recovery._derive_data_key(
        CURRENT_ROOT, other_generation) != original
    assert recovery._derive_data_key(CURRENT_ROOT, other_ledger) != original
    assert recovery._derive_data_key(CURRENT_ROOT, other_wal) != original
